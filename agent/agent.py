"""Agent orchestration: the browser and model seams, and the two units of work
that need a model — a hunt over one (watch, site) pair, and the LLM fallback
when code could not read a listing's price.

Nothing here decides what to work on. agent/worker.py claims a job and calls
in; this module only knows how to do one unit and how to say what happened.

Importing this module builds neither a browser session nor a chat model; both
come from factories. The check pool opens browser sessions all day and asks for
a model only when the deterministic ladder gives up, so neither may be a
module-level side effect.

Every job opens its own MCP session, which with `--isolated` is its own
browser context: a hung page in one hunt cannot block a check in another, and
"check prices now" never waits behind a hunt. That is why the server has to
run with `--isolated`: with a persistent profile the second session is refused
outright.

The tool list handed to the model is filtered. Code execution, file
upload and tab control are not things a price scraper needs, and a page that
talks the model into using them is a different class of problem from one that
lies about a price. browser_navigate is wrapped so the URL guard runs before
any navigation, not only before a URL is stored.
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager

from config import (
    AGENT_MAX_STEPS,
    AGENT_UNIT_TIMEOUT_SECONDS,
    PLAYWRIGHT_MCP_URL,
    VISION_SIDECAR_URL,
)
from database import (
    get_active_listing_count,
    get_checked_urls,
    get_known_listing_urls,
    get_market_price,
    get_price_context,
    get_tracked_listings,
    has_verified_locator,
)
from jobs import append_event, status
from langchain.agents import create_agent
from langchain.agents.middleware import ClearToolUsesEdit, ContextEditingMiddleware
from langchain_core.messages import ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from llm import callbacks
from locators import PageReader, reply_text
from observations import UnitContext
from prompt import generate_prompt, generate_recheck_prompt
from tools import (
    check_images,
    disable_listing,
    learn_locator,
    log_listing_check,
    save_listing,
    save_price_check,
    unit_of,
)
from validation import url_allowed

log = logging.getLogger(__name__)

# Nothing a price scraper does needs these, and each is a way for a page to
# turn a bad read into something worse: arbitrary JS in the browser context,
# a file picker, and windows the orchestrator is not watching.
BLOCKED_BROWSER_TOOLS = frozenset(
    {"browser_run_code_unsafe", "browser_run_code", "browser_file_upload", "browser_tabs"}
)

# How many of a hunt's latest tool results the model still sees in full. A
# page snapshot runs to tens of thousands of tokens and every model turn
# re-sends the whole history, so keeping them all would pay for the first
# page again on every later turn — a hunt's cost would grow with the square
# of the pages it reads. Three is the page in hand plus the tool calls made
# on it; the prompt tells the model to note its candidates down rather than
# rely on a results page it has moved away from.
PAGES_KEPT = 3

# The DB tools' replies are a line or two each and are the model's record of
# what it has saved and rejected, so they are never cleared.
HUNT_RECORD_TOOLS = (
    "save_listing",
    "save_price_check",
    "log_listing_check",
    "disable_listing",
    "check_images",
)

# How often a running hunt asks whether it has been cancelled. Between model
# steps, not inside the stream — a cancel is a request to stop soon, not to
# tear down a call in flight.
CANCEL_POLL_SECONDS = 5


class Cancelled(Exception):
    """The job was cancelled while its unit was running."""


def agent_config(
    kind: str, unit: UnitContext, *, user_id: int, site_name: str, category: str
) -> dict:
    """
    Build the per-call runnable config for one unit's agent invocation.

    Every hunt and model recheck on one watch shares the session
    watch-<watch_id> and carries the owner's user id, so a watch's traces read
    as one timeline in the tracing UI and cost can be broken down per user.
    The job kind is the trace name; it, the site and the category are tags
    (agent/llm.py says why); the ids the unit is bound to ride along as
    metadata. The plain session_id key is what LangSmith groups threads by;
    the langfuse_* keys are read by the Langfuse handler, which applies them
    to the trace because an agent run's outermost runnable is a chain.

    recursion_limit caps one unit's graph steps: create_agent's own default is
    effectively unlimited, and a per-call value overrides it. A unit that hits
    the cap raises and fails like any other unit.

    The unit itself rides on `configurable`, where the DB tools read it back
    through their injected runtime (tools.UnitContext): the watch, item, site
    and (on a recheck) listing a tool writes under are bound here, never typed
    by the model. Only primitive configurable values are copied into tracer
    metadata, so the dataclass stays out of the traces.

    Args:
      kind: The job kind, "hunt" or "recheck" — also the trace name.
      unit: What this call is about — the ids every tool call is bound to.
      user_id: Owner of the watch this call is working on.
      site_name: The site the unit is on, for the site tag.
      category: The item's category slug, for the category tag.
    """
    tags = [f"kind:{kind}", f"site:{site_name}", f"category:{category}"]
    if unit.swap:
        tags.append("swap")
    session_id = f"watch-{unit.watch_id}"
    metadata = {
        "job_id": unit.job_id,
        "watch_id": unit.watch_id,
        "item_id": unit.item_id,
        "site_id": unit.site_id,
        "session_id": session_id,
        "user_id": str(user_id),
        "langfuse_session_id": session_id,
        "langfuse_user_id": str(user_id),
        "langfuse_tags": tags,
    }
    if unit.listing_id is not None:
        metadata["listing_id"] = unit.listing_id
    return {
        "callbacks": callbacks,
        "run_name": kind,
        "recursion_limit": AGENT_MAX_STEPS,
        "configurable": {"unit": unit},
        "metadata": metadata,
    }


@asynccontextmanager
async def open_browser_session():
    """Open one MCP session and yield its filtered tools and a page reader.

    One session per job: with `--isolated` the server gives each session its
    own browser context, so this is also the isolation boundary between
    concurrent jobs. The session must span the whole job — tools loaded
    without one open a fresh session per call.

    The reader is what lets code drive the same browser the model is using
    without the model in the loop: the deterministic recheck reads pages
    through it, and the learn step replays a locator through it. Its calls
    carry no tokens, because the text never enters a prompt.
    """
    assert PLAYWRIGHT_MCP_URL is not None, "PLAYWRIGHT_MCP_URL not set"
    client = MultiServerMCPClient(
        {"playwright": {"url": PLAYWRIGHT_MCP_URL, "transport": "streamable_http"}}
    )
    async with client.session("playwright") as session:
        loaded = await load_mcp_tools(session)
        by_name = {tool.name: tool for tool in loaded}
        browser = PageReader(by_name["browser_navigate"], by_name["browser_evaluate"])

        dropped = sorted(BLOCKED_BROWSER_TOOLS & by_name.keys())
        if dropped:
            log.info(f"Withholding browser tools from the model: {', '.join(dropped)}")
        safe = [tool for tool in loaded if tool.name not in BLOCKED_BROWSER_TOOLS]
        # the model still gets a tool named browser_navigate, but it is the
        # guarded wrapper, not the MCP tool that goes anywhere it is pointed
        safe = [tool for tool in safe if tool.name != "browser_navigate"]
        safe.append(guarded_navigate(by_name["browser_navigate"]))
        yield safe, browser


def guarded_navigate(navigate):
    """Wrap the MCP browser_navigate so the URL guard runs before it does.

    Storing a URL is guarded by save_listing; navigating needs the same guard,
    because the browser is pointed at whatever a marketplace page suggested far
    more often than a URL is stored. The refusal is spelled out because the
    model can act on it — "not part of ebay.com" usually means it followed an
    advert off-site and should go back.
    """

    async def browser_navigate(url: str, *, runtime) -> str:
        """Navigate to a URL and return the page. The URL must be on the site
        you are searching — anywhere else is refused.

        Args:
          url: The full http(s) URL of a page on THIS site.
        Returns:
          The page as the browser sees it, or a string starting with "Error:"
          saying why the URL was refused.
        """
        unit = unit_of(runtime)
        refused = url_allowed(url, unit.site_base_url)
        if refused:
            return (
                f"Error: refusing to open {url} — {refused}. Go back to the site you are "
                f"searching and continue from there."
            )
        if unit.job_id is not None and unit.is_hunt:
            await append_event(unit.job_id, "info", "listing_check", f"Reading {url}", {"url": url})
        return reply_text(await navigate.ainvoke({"url": url}))

    return browser_navigate


def build_recheck_agent(llm, browser_tools: list):
    """The fallback reader: price and availability tools only."""
    return create_agent(llm, [*browser_tools, save_price_check, disable_listing])


def build_hunt_agent(llm, browser_tools: list):
    """The hunter: discovery tools too.

    disable_listing is in this toolset because the hunt prompt tells the model
    to call it after a sold/ended save_price_check.

    A hunt walks page after page, so all but its latest few page reads are
    cleared from what the model is sent (PAGES_KEPT). A recheck reads one
    page and needs no trimming.
    """
    tools = [*browser_tools, save_price_check, save_listing, log_listing_check, disable_listing]
    # Hunts only (rechecks never scan images), and only when the sidecar is
    # configured: with the URL unset the tool is not registered and vision is
    # fully off.
    if VISION_SIDECAR_URL:
        tools.append(check_images)
    # Only what is sent to the model is trimmed; the run's own messages keep
    # every result, which is what _require_browser_success reads.
    trim_pages = ContextEditingMiddleware(
        edits=[
            ClearToolUsesEdit(
                trigger=0,
                keep=PAGES_KEPT,
                exclude_tools=HUNT_RECORD_TOOLS,
                placeholder="[page cleared from view — open it again if you still need it]",
            )
        ]
    )
    return create_agent(llm, tools, middleware=[trim_pages])


def tokens_spent(messages: list) -> tuple[int, int]:
    """Input and output tokens across one unit's model turns, for the job's
    stats. Providers that report no usage simply contribute nothing."""
    spent_in = spent_out = 0
    for message in messages:
        usage = getattr(message, "usage_metadata", None) or {}
        spent_in += usage.get("input_tokens") or 0
        spent_out += usage.get("output_tokens") or 0
    return spent_in, spent_out


def _require_browser_success(messages: list) -> None:
    """
    Raise when every browser_* tool call in a unit's transcript errored — the
    model ends such a unit with a graceful "couldn't browse" summary, which
    would otherwise count as a clean unit. Playwright MCP tools all share the
    browser_ name prefix, so the DB tools never match; mixed results stay
    non-fatal (a failed click the model recovered from is normal browsing).
    """
    results = [
        m for m in messages if isinstance(m, ToolMessage) and (m.name or "").startswith("browser_")
    ]
    if results and all(m.status == "error" for m in results):
        raise RuntimeError(f"every browser call failed: {results[0].content}")


async def _stream(agent, prompt: str, config: dict, job_id: int | None) -> list:
    """Run one model stream to the end and return its messages.

    A running job is polled for cancellation between steps rather than inside
    the stream: cancelling is a request to stop soon, and tearing down a call
    in flight would lose whatever it was about to record.
    """
    final: dict = {}
    checked_at = time.monotonic()
    async for step in agent.astream(
        {"messages": [{"role": "user", "content": prompt}]},
        config=config,
        stream_mode="values",
    ):
        step["messages"][-1].pretty_print()
        final = step
        if job_id is not None and time.monotonic() - checked_at > CANCEL_POLL_SECONDS:
            checked_at = time.monotonic()
            if await status(job_id) == "cancelled":
                raise Cancelled(f"job {job_id} was cancelled")
    return final.get("messages", [])


async def recheck_listing(agent, row, browser, job_id=None) -> dict:
    """One listing, re-read by the model because code could not read it.

    Reached only when the deterministic ladder could not read the page
    (agent/recheck.py). Afterwards a locator is learned from whatever the model
    confirmed, so the next check of this listing does not need a model at all.
    Raises on failure — the worker counts it.

    Returns:
      The unit's tally plus the tokens it spent, the same shape a hunt
      returns. A model that could not read the page reports that by recording
      status="error", which lands in the tally as an error rather than as an
      exception — and that is how the breaker hears about a site that has
      stopped answering.
    """
    listing_id = int(row["listing_id"])
    listing_url = row["listing_url"]
    user_id = int(row["user_id"])

    log.info(
        f"Rechecking listing {listing_id} for item {row['item_id']} ({row['item_name']}) "
        f"on site {row['site_id']} ({row['site_name']}) for user {user_id}"
    )

    prompt = await generate_recheck_prompt(
        listing_id=listing_id,
        listing_url=listing_url,
        watch_id=row["watch_id"],
        site_id=row["site_id"],
        site_name=row["site_name"],
        item_id=row["item_id"],
        item_name=row["item_name"],
    )
    unit = UnitContext(
        watch_id=int(row["watch_id"]),
        item_id=int(row["item_id"]),
        site_id=int(row["site_id"]),
        site_base_url=row["site_base_url"],
        listing_id=listing_id,
        browser=browser,
        job_id=job_id,
    )

    config = agent_config(
        "recheck",
        unit,
        user_id=user_id,
        site_name=row["site_name"],
        category=row["category_slug"],
    )
    messages = await _stream(agent, prompt, config, None)
    _require_browser_success(messages)
    await _learn_after_unit(unit, listing_id, listing_url)
    spent_in, spent_out = tokens_spent(messages)
    return {**unit.stats, "tokens_in": spent_in, "tokens_out": spent_out}


async def _learn_after_unit(unit: UnitContext, listing_id: int, listing_url: str) -> None:
    """Learn this listing's locator once the model has finished with it.

    save_price_check already tries while the model is still on the page; this
    is the fallback for when it had browsed elsewhere by then, and it costs
    one navigation. Skipped entirely once the listing has a verified locator,
    and when the unit recorded no believed price there is nothing to learn
    from. Never fatal: a job must not fail because an optimisation did.
    """
    if unit.browser is None or await has_verified_locator(listing_id):
        return
    price = (await get_price_context(listing_id))["last_price"]
    if price is None:
        return
    try:
        await learn_locator(unit, listing_id, price, url=listing_url)
    except Exception as e:
        log.warning(f"Post-unit locator learn failed for listing {listing_id}: {e}")


async def run_hunt_job(agent, job_id: int, row, browser) -> dict:
    """One hunt: search a site for listings that fit one watch.

    The model is told how many of the watch's slots are already in use and
    which URLs this pair already knows, so it neither re-judges a rejection
    nor over-fills the watch. Raises on failure — the worker counts it.

    A hunt that finds its watch full is a swap hunt: the model is shown the
    tracked listings weakest first, and every save trades the weakest for
    something better. That is how a site searched after another filled the
    watch still gets its say. The queue never adds a hunt for a full watch,
    so this costs one pass over each site that was already queued, not a
    standing hunt. Should a slot have freed since it was queued, it is an
    ordinary hunt.

    Returns:
      The unit's tally plus the tokens it spent, which becomes the job's stats.
    """
    watch_id = row["watch_id"]
    user_id = int(row["user_id"])
    site_id = row["site_id"]
    site_name = row["site_name"]
    item_id = row["item_id"]
    item_name = row["item_name"]
    max_listings = int(row["max_listings"])
    mode = "best match" if row["selection_mode"] == "best_match" else "cheapest"

    # Re-read right before searching: a slot can fill between the moment the
    # job was queued and the moment it runs, and a hunt on a full watch can
    # only trade, so it needs to know what it would be trading away.
    tracked = await get_active_listing_count(watch_id)
    open_slots = max_listings - tracked
    swap_listings = None
    if open_slots <= 0:
        swap_listings = await get_tracked_listings(watch_id, row["selection_mode"])
        started = (
            f'Hunting {site_name} for something better than "{item_name}"\'s weakest '
            f"tracked listings — all {max_listings} slots filled, {mode} mode"
        )
    else:
        started = (
            f'Hunting {site_name} for "{item_name}" — {open_slots} open '
            f"slot{'' if open_slots == 1 else 's'}, {mode} mode"
        )

    log.info(
        f"Hunting {site_name} for watch {watch_id} (user {user_id}): "
        f"item {item_id} ({item_name}) at {row['base_url']}"
        + (" — swap hunt" if swap_listings is not None else "")
    )
    await append_event(
        job_id,
        "info",
        "job_started",
        started,
        {"item_id": int(item_id), "site_id": int(site_id)},
    )

    known_urls = list(await get_known_listing_urls(watch_id, site_id))
    rejected_checks = [
        {"url": c["url"], "reason": c["reason"], "notes": c["notes"]}
        for c in await get_checked_urls(watch_id, site_id)
    ]
    market_row = await get_market_price(item_id)
    expected_price = row["expected_price"]

    prompt = await generate_prompt(
        watch_id=watch_id,
        site_id=site_id,
        site_name=site_name,
        item_id=item_id,
        item_name=item_name,
        base_url=row["base_url"],
        criteria=row["criteria"],
        selection_mode=row["selection_mode"],
        max_listings=max_listings,
        allow_reproductions=bool(row["allow_reproductions"]),
        tracked_listings=tracked,
        vision_enabled=bool(VISION_SIDECAR_URL),
        known_urls=known_urls,
        rejected_checks=rejected_checks,
        market=dict(market_row) if market_row else None,
        expected_price=str(expected_price) if expected_price is not None else None,
        condition_hint=row["condition_hint"],
        swap_listings=swap_listings,
    )
    unit = UnitContext(
        watch_id=int(watch_id),
        item_id=int(item_id),
        site_id=int(site_id),
        site_base_url=row["base_url"],
        browser=browser,
        job_id=job_id,
        swap=swap_listings is not None,
    )

    config = agent_config(
        "hunt", unit, user_id=user_id, site_name=site_name, category=row["category_slug"]
    )
    messages = await _stream(agent, prompt, config, job_id)
    _require_browser_success(messages)
    spent_in, spent_out = tokens_spent(messages)
    return {**unit.stats, "tokens_in": spent_in, "tokens_out": spent_out}


async def bounded(unit):
    """
    Run one unit under the wall-clock budget. A unit that outlives it is
    cancelled — which is what actually stops the LLM stream — and fails with
    a message the job's events can show; asyncio's TimeoutError carries none
    of its own.
    """
    try:
        async with asyncio.timeout(AGENT_UNIT_TIMEOUT_SECONDS):
            return await unit
    except TimeoutError:
        raise RuntimeError(f"unit exceeded the {AGENT_UNIT_TIMEOUT_SECONDS}s budget") from None
