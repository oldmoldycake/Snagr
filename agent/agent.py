"""Agent orchestration: builds the LLM agent (model + Playwright MCP browser
tools + database tools) and runs one search per (watch, site) pair.

Runs are recorded in agent_runs (Phase 3, D3): the scheduled sweep (run())
inserts its own global row; consume() claims API-enqueued rows oldest-first
— or, when the queue is empty, fires a due run_schedules row — and limits
both passes to the claimed run's scope. Progress lands in run_events,
totals in agent_runs.stats, and cancellation is cooperative — the run's
status is re-checked between units of work because the API's cancel only
flips the row, and bailing early is what stops mid-run LLM token burn.

A run must never be left 'running' by a process that is no longer driving
it: while alive it heartbeats (agent_runs.heartbeat_at), a shutdown signal
arrives as task cancellation and the row is failed on the way out, and every
tick first reaps runs whose heartbeat went silent (a crash, an OOM kill).
Each unit is also bounded — a step cap and a wall-clock cap — so one looping
LLM stream can't hold a run open indefinitely.
"""

import asyncio
import contextlib
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

from config import (
    AGENT_MAX_STEPS,
    AGENT_UNIT_TIMEOUT_SECONDS,
    AI_API_KEY,
    AI_MODEL,
    AI_PROVIDER,
    AI_URL,
    CHEAP_RECHECK,
    LANGFUSE_ENABLED,
    PLAYWRIGHT_MCP_URL,
    RUN_HEARTBEAT_INTERVAL_SECONDS,
    RUN_STALE_AFTER_SECONDS,
    VISION_SIDECAR_URL,
)
from database import (
    append_run_event,
    beat_run,
    claim_due_schedule,
    claim_queued_run,
    create_global_run,
    finish_run,
    get_active_listing_count,
    get_checked_urls,
    get_known_listing_urls,
    get_listed_items,
    get_market_price,
    get_price_context,
    get_run_status,
    get_watched_item_list,
    has_verified_locator,
    reap_stale_runs,
)
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langfuse import get_client
from langfuse.langchain import CallbackHandler
from locators import PageReader
from observations import UnitContext
from pricing import ground_stale
from prompt import generate_prompt, generate_recheck_prompt
from recheck import recheck_deterministic
from tools import (
    check_images,
    disable_listing,
    learn_locator,
    log_listing_check,
    read_run_stats,
    reset_run_stats,
    save_listing,
    save_price_check,
)

log = logging.getLogger(__name__)

# LangSmith traces globally on its own when LANGSMITH_TRACING/LANGSMITH_API_KEY are
# set; Langfuse hooks in per-call, so only build its handler when keys are configured.
callbacks = [CallbackHandler()] if LANGFUSE_ENABLED else []

assert PLAYWRIGHT_MCP_URL is not None, "PLAYWRIGHT_MCP_URL not set"

if AI_API_KEY:
    llm = init_chat_model(f"{AI_PROVIDER}:{AI_MODEL}", base_url=AI_URL, api_key=AI_API_KEY)
else:
    llm = init_chat_model(f"{AI_PROVIDER}:{AI_MODEL}", base_url=AI_URL)


def agent_config(session_id: str, user_id: int, unit: UnitContext) -> dict:
    """
    Build the per-call runnable config for one unit's agent invocation.

    Every trace from a single job invocation shares session_id and carries the
    owning user's id, so runs group together in the tracing UI and cost/latency
    can be broken down per user. Langfuse reads the `langfuse_*` metadata keys;
    the unprefixed copies are what LangSmith filters on.

    recursion_limit caps one unit's graph steps: create_agent's own default is
    effectively unlimited, and a per-call value overrides it. A unit that hits
    the cap raises and fails like any other unit.

    The unit itself rides on `configurable`, where the DB tools read it back
    through their injected runtime (tools.UnitContext): the watch, item, site
    and listing a tool writes under are bound here, never typed by the model.
    Only primitive configurable values are copied into tracer metadata, so
    the dataclass stays out of the traces.

    Args:
      session_id: Identifier for the whole job run, shared by every call.
      user_id: Owner of the watch this call is working on.
      unit: What this call is about — the ids every tool call is bound to.
    """
    return {
        "callbacks": callbacks,
        "recursion_limit": AGENT_MAX_STEPS,
        "configurable": {"unit": unit},
        "metadata": {
            "session_id": session_id,
            "user_id": str(user_id),
            "langfuse_session_id": session_id,
            "langfuse_user_id": str(user_id),
        },
    }


@asynccontextmanager
async def build_pass_agents():
    """
    Connect to the Playwright MCP server and build the two per-pass agents
    plus the page reader: the recheck agent (price/availability tools only),
    the scan agent (discovery tools too), and a PageReader over the session's
    raw browser tools. The one seam for everything LLM/browser-shaped.

    The reader is what lets code drive the same browser the model is using
    without the model in the loop — the deterministic recheck reads pages
    through it, and the learn step replays a locator through it. Its tool
    calls carry no tokens: the text never enters a prompt.

    A context manager because the MCP session must span the whole run: tools
    loaded without one open a fresh session per tool call, and those sessions
    race for the server's single persistent browser profile ("Browser is
    already in use for /profile").
    """
    client = MultiServerMCPClient(
        {
            "playwright": {
                "url": PLAYWRIGHT_MCP_URL,
                "transport": "streamable_http",
            }
        }
    )

    async with client.session("playwright") as session:
        tools = await load_mcp_tools(session)
        by_name = {tool.name: tool for tool in tools}
        browser = PageReader(by_name["browser_navigate"], by_name["browser_evaluate"])

        recheck_agent = create_agent(llm, tools + [save_price_check, disable_listing])
        # disable_listing is in the scan toolset because the scan prompt tells
        # the model to call it after a sold/ended save_price_check.
        scan_tools = tools + [save_price_check, save_listing, log_listing_check, disable_listing]
        # Discovery pass only (D-V9), and only when the sidecar is configured —
        # with the URL unset the tool is not registered and vision is fully off.
        if VISION_SIDECAR_URL:
            scan_tools.append(check_images)
        scan_agent = create_agent(llm, scan_tools)
        yield recheck_agent, scan_agent, browser


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


async def recheck_listing(agent, session_id: str, row, browser=None) -> None:
    """One pass-1 unit: revisit a tracked listing and record its current
    price/availability with the LLM. Raises on failure — the orchestrator
    counts it.

    Reached only when the deterministic ladder could not read the page
    (agent/recheck.py). Afterwards the orchestrator learns a locator from
    whatever the model confirmed, so the next recheck of this listing does
    not need a model at all.
    """
    listing_id = int(row["listing_id"])
    listing_url = row["listing_url"]
    watch_id = row["watch_id"]
    user_id = int(row["user_id"])
    site_id = row["site_id"]
    site_name = row["site_name"]
    item_id = row["item_id"]
    item_name = row["item_name"]

    log.info(
        f"Rechecking listing {listing_id} for item {item_id} ({item_name}) "
        f"on site {site_id} ({site_name}) for user {user_id}"
    )

    prompt = await generate_recheck_prompt(
        listing_id=listing_id,
        listing_url=listing_url,
        watch_id=watch_id,
        site_id=site_id,
        site_name=site_name,
        item_id=item_id,
        item_name=item_name,
    )
    unit = UnitContext(
        watch_id=int(watch_id),
        item_id=int(item_id),
        site_id=int(site_id),
        site_base_url=row["site_base_url"],
        listing_id=listing_id,
        browser=browser,
    )

    final: dict = {}
    async for step in agent.astream(
        {"messages": [{"role": "user", "content": prompt}]},
        config=agent_config(session_id, user_id, unit),
        stream_mode="values",
    ):
        step["messages"][-1].pretty_print()
        final = step
    _require_browser_success(final.get("messages", []))
    await _learn_after_unit(unit, listing_id, listing_url)


async def _learn_after_unit(unit: UnitContext, listing_id: int, listing_url: str) -> None:
    """Learn this listing's locator once the model has finished with it.

    save_price_check already tries while the model is still on the page; this
    is the fallback for when it had browsed elsewhere by then, and it costs
    one navigation. Skipped entirely once the listing has a verified locator,
    and when the unit recorded no believed price there is nothing to learn
    from. Never fatal: a run must not fail because an optimisation did.
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


async def scan_pair(
    agent, session_id: str, row, market: dict | None, tracked_listings: int, browser=None
) -> None:
    """One pass-2 unit: search a site for new listings for one watch, telling
    the model how many of the watch's slots are already in use and which
    URLs this pair already knows. Raises on failure — the orchestrator counts
    it."""
    watch_id = row["watch_id"]
    user_id = int(row["user_id"])
    site_id = row["site_id"]
    site_name = row["site_name"]
    item_id = row["item_id"]
    item_name = row["item_name"]
    base_url = row["base_url"]
    criteria = row["criteria"]
    expected_price = row["expected_price"]
    condition_hint = row["condition_hint"]
    selection_mode = row["selection_mode"]
    max_listings = int(row["max_listings"])
    allow_reproductions = bool(row["allow_reproductions"])

    log.info(
        f"Starting search for watch {watch_id} (user {user_id}): "
        f"item {item_id} ({item_name}) on site {site_id} ({site_name}) at {base_url}"
    )

    known_urls = list(await get_known_listing_urls(watch_id, site_id))
    checked_urls_list = await get_checked_urls(watch_id, site_id)
    rejected_checks = [
        {"url": c["url"], "reason": c["reason"], "notes": c["notes"]} for c in checked_urls_list
    ]

    prompt = await generate_prompt(
        watch_id=watch_id,
        site_id=site_id,
        site_name=site_name,
        item_id=item_id,
        item_name=item_name,
        base_url=base_url,
        criteria=criteria,
        selection_mode=selection_mode,
        max_listings=max_listings,
        allow_reproductions=allow_reproductions,
        tracked_listings=tracked_listings,
        vision_enabled=bool(VISION_SIDECAR_URL),
        known_urls=known_urls,
        rejected_checks=rejected_checks,
        market=market,
        expected_price=str(expected_price) if expected_price is not None else None,
        condition_hint=condition_hint,
    )
    unit = UnitContext(
        watch_id=int(watch_id),
        item_id=int(item_id),
        site_id=int(site_id),
        site_base_url=base_url,
        browser=browser,
    )

    final: dict = {}
    async for step in agent.astream(
        {"messages": [{"role": "user", "content": prompt}]},
        config=agent_config(session_id, user_id, unit),
        stream_mode="values",
    ):
        step["messages"][-1].pretty_print()
        final = step
    _require_browser_success(final.get("messages", []))


async def _recheck_unit(agent, session_id: str, row, browser) -> None:
    """One pass-1 unit, cheapest path first.

    The deterministic ladder gets first refusal: when it reads the page, the
    unit is done and no model ran at all. Only when it cannot — the locator
    is gone, the page is blocked, the reading is implausible — does the full
    agentic recheck run, and that read is what relearns the locator.

    The whole unit is bounded, not just the LLM half: a wedged browser call
    on the cheap path would otherwise hold the run open with no model to
    blame. CHEAP_RECHECK=false skips the ladder entirely and puts every
    recheck back through the LLM, which is how the agent behaved before
    locators existed.
    """
    listing_id = row["listing_id"]
    if CHEAP_RECHECK:
        outcome = await recheck_deterministic(browser, row)
        if outcome.handled:
            log.info(
                f"Listing {listing_id} read by {outcome.method} over {outcome.transport}"
                + (f" ({outcome.note})" if outcome.note else "")
            )
            return
        log.info(f"Listing {listing_id} needs the model; falling back to the agentic recheck")

    await recheck_listing(agent, session_id, row, browser)


async def _bounded(unit) -> None:
    """
    Run one unit under the wall-clock budget. A unit that outlives it is
    cancelled — which is what actually stops the LLM stream — and fails with
    a message the run's events can show; asyncio's TimeoutError carries none
    of its own.
    """
    try:
        async with asyncio.timeout(AGENT_UNIT_TIMEOUT_SECONDS):
            await unit
    except TimeoutError:
        raise RuntimeError(f"unit exceeded the {AGENT_UNIT_TIMEOUT_SECONDS}s budget") from None


async def execute_run(run: dict) -> dict | None:
    """
    Execute a claimed run: the two scrape passes, limited to the run's scope,
    emitting run_events as work progresses and polling for cooperative
    cancellation between units (each unit is one full LLM stream — the finest
    granularity that doesn't hook into the stream itself).

    Returns the run's stats on completion, or None if the run was cancelled —
    the API already wrote the terminal state in that case, so the caller must
    not write another. Raises when every attempted unit failed, so _drive
    marks the run failed instead of succeeded-with-zeroed-stats.
    """
    run_id = run["id"]
    session_id = str(uuid.uuid4())
    log.info(f"Job session {session_id} (run {run_id})")

    reset_run_stats()
    errors = 0
    origin = " (scheduled)" if run.get("scheduled") else ""
    await append_run_event(
        run_id, "info", "run_started", f"Run started — {run['scope_label']}{origin}"
    )

    # Grounding pre-pass: refresh stale market prices first so this run's
    # scan prompts read stats from minutes ago, not last night's. Global runs
    # only — the candidate pool is instance-wide, and a scoped run shouldn't
    # spend the per-run refresh budget on out-of-scope items. Isolation per
    # the spec: grounding failure must never block the scrape.
    if run["scope"] == "global":
        try:
            await ground_stale()
        except Exception as e:
            log.error(f"Grounding pre-pass failed, scraping ungrounded: {e}")

    units = 0
    async with build_pass_agents() as (recheck_agent, scan_agent, browser):
        log.info("Starting scan on current listings")

        listed_items_list = await get_listed_items(run["scope"], run["scope_id"])
        for row in listed_items_list:
            if await get_run_status(run_id) == "cancelled":
                log.info(f"Run {run_id} cancelled; stopping before listing {row['listing_id']}")
                return None

            units += 1
            try:
                await _bounded(_recheck_unit(recheck_agent, session_id, row, browser))
                log.info(f"Finished recheck for listing {row['listing_id']}")
            except Exception as e:
                log.error(f"Recheck failed for listing {row['listing_id']}: {e}")
                errors += 1
                await append_run_event(
                    run_id,
                    "error",
                    "error",
                    f"Recheck failed for listing {row['listing_id']}: {e}",
                    {"listing_id": int(row["listing_id"])},
                )
                continue

        log.info("Starting scan for new items")

        watch_site_list = await get_watched_item_list(run["scope"], run["scope_id"])
        markets: dict[int, dict | None] = {}
        for row in watch_site_list:
            if await get_run_status(run_id) == "cancelled":
                log.info(f"Run {run_id} cancelled; stopping before watch {row['watch_id']}")
                return None

            item_id = row["item_id"]
            if item_id not in markets:
                market_row = await get_market_price(item_id)
                markets[item_id] = dict(market_row) if market_row else None

            # max_listings is one budget per watch across every site and run,
            # and a scan only sees its own site — so the slots are metered
            # here. Re-read right before each search: the previous site may
            # have just filled the last slot, and a full watch should cost no
            # browser time or tokens. Skipped pairs are not units: nothing was
            # attempted, so they must not mask an all-failed run.
            tracked = await get_active_listing_count(row["watch_id"])
            if tracked >= int(row["max_listings"]):
                log.info(
                    f"Skipping {row['site_name']} for {row['item_name']}: "
                    f"all {row['max_listings']} slots in use"
                )
                continue

            await append_run_event(
                run_id,
                "info",
                "item_started",
                f'Searching {row["site_name"]} for "{row["item_name"]}"…',
                {"item_id": int(item_id), "site_id": int(row["site_id"])},
            )
            units += 1
            try:
                await _bounded(
                    scan_pair(scan_agent, session_id, row, markets[item_id], tracked, browser)
                )
                log.info(f"Finished {row['item_name']} on site {row['site_name']}")
            except Exception as e:
                log.error(f"Item {row['item_name']} on site {row['site_name']} failed: {e}")
                errors += 1
                await append_run_event(
                    run_id,
                    "error",
                    "error",
                    f"Search for {row['item_name']} on {row['site_name']} failed: {e}",
                    {"item_id": int(item_id), "site_id": int(row["site_id"])},
                )
                continue

    # a run that attempted work and got nothing done is a failure, not a
    # success with zeroed stats — the per-unit events carry the detail
    if units and errors == units:
        raise RuntimeError(f"every unit failed ({errors}/{units}) — see the run's events")

    stats = read_run_stats()
    stats["errors"] += errors
    return stats


async def _heartbeat(run_id: int) -> None:
    """Stamp the run's heartbeat every RUN_HEARTBEAT_INTERVAL_SECONDS until
    cancelled — what keeps reap_stale_runs off a run that is merely slow.
    The claim already stamped the first beat, hence sleep-then-beat."""
    while True:
        await asyncio.sleep(RUN_HEARTBEAT_INTERVAL_SECONDS)
        await beat_run(run_id)


async def _drive(run_row: dict) -> None:
    """
    Execute a run and own its terminal write — main.py's catch only logs, so
    an agent_runs row must never leave here still 'running'. That includes a
    shutdown: SIGTERM/SIGINT arrive as cancellation (see main.py), and the row
    is failed on the way out rather than left for the reaper to find.
    """
    run_id = run_row["id"]
    heartbeat = asyncio.create_task(_heartbeat(run_id))
    try:
        stats = await execute_run(run_row)
    except asyncio.CancelledError:
        await finish_run(run_id, "failed", error="Agent shut down mid-run")
        raise
    except Exception as e:
        await finish_run(run_id, "failed", error=str(e))
        raise
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        # Langfuse queues events on a background thread; flush before this
        # batch job exits or the tail of the run's traces is silently dropped.
        if LANGFUSE_ENABLED:
            get_client().flush()

    # stats None = cancelled: the API already wrote the terminal state
    if stats is not None:
        await finish_run(run_id, "succeeded", stats=stats)


async def _reap() -> None:
    """Fail runs whose driver died, before claiming any new work — the only
    place a wedged row is ever noticed."""
    reaped = await reap_stale_runs(timedelta(seconds=RUN_STALE_AFTER_SECONDS))
    if reaped:
        log.warning(f"Reaped stale runs: {reaped}")


async def run() -> None:
    """
    The scheduled full sweep: record a global agent_runs row for this
    invocation, then execute it. It kicks off even if an API-triggered run is
    active — the one-active-run guard belongs to the API's enqueue; a
    conditional skip here would let one stale 'running' row silently stop
    every future sweep.
    """
    await _reap()
    await _drive(await create_global_run())


async def consume() -> None:
    """
    One run-queue tick: reap dead runs, then claim the oldest queued run —
    user clicks beat schedules — else fire the most-overdue due run_schedules
    row as a fresh run; exit immediately when neither exists. Cron this every
    minute so UI-triggered runs start promptly and schedules fire on time.
    """
    await _reap()
    claimed = await claim_queued_run()
    if claimed is None:
        claimed = await claim_due_schedule()
    if claimed is None:
        log.info("No queued runs or due schedules")
        return
    await _drive(claimed)
