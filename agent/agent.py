"""Agent orchestration: builds the LLM agent (model + Playwright MCP browser
tools + database tools) and runs one search per (watch, site) pair.

Runs are recorded in agent_runs (Phase 3, D3): the scheduled sweep (run())
inserts its own global row; consume() claims API-enqueued rows oldest-first
— or, when the queue is empty, fires a due run_schedules row — and limits
both passes to the claimed run's scope. Progress lands in run_events,
totals in agent_runs.stats, and cancellation is cooperative — the run's
status is re-checked between units of work because the API's cancel only
flips the row, and bailing early is what stops mid-run LLM token burn.
"""

import logging
import uuid

from config import AI_API_KEY, AI_MODEL, AI_PROVIDER, AI_URL, LANGFUSE_ENABLED, PLAYWRIGHT_MCP_URL
from database import (
    append_run_event,
    claim_due_schedule,
    claim_queued_run,
    create_global_run,
    finish_run,
    get_checked_urls,
    get_listed_items,
    get_market_price,
    get_run_status,
    get_watched_item_list,
)
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient
from langfuse import get_client
from langfuse.langchain import CallbackHandler
from pricing import ground_stale
from prompt import generate_prompt, generate_recheck_prompt
from tools import (
    disable_listing,
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


def agent_config(session_id: str, user_id: int) -> dict:
    """
    Build the per-call runnable config for one watch's agent invocation.

    Every trace from a single job invocation shares session_id and carries the
    owning user's id, so runs group together in the tracing UI and cost/latency
    can be broken down per user. Langfuse reads the `langfuse_*` metadata keys;
    the unprefixed copies are what LangSmith filters on.

    Args:
      session_id: Identifier for the whole job run, shared by every call.
      user_id: Owner of the watch this call is working on.
    """
    return {
        "callbacks": callbacks,
        "metadata": {
            "session_id": session_id,
            "user_id": str(user_id),
            "langfuse_session_id": session_id,
            "langfuse_user_id": str(user_id),
        },
    }


async def build_pass_agents() -> tuple:
    """
    Connect to the Playwright MCP server and build the two per-pass agents:
    the recheck agent (price/availability tools only) and the scan agent
    (discovery tools too). The one seam for everything LLM/browser-shaped.
    """
    client = MultiServerMCPClient(
        {
            "playwright": {
                "url": PLAYWRIGHT_MCP_URL,
                "transport": "streamable_http",
            }
        }
    )

    tools = await client.get_tools()
    recheck_agent = create_agent(llm, tools + [save_price_check, disable_listing])

    tools = await client.get_tools()
    scan_agent = create_agent(llm, tools + [save_price_check, save_listing, log_listing_check])

    return recheck_agent, scan_agent


async def recheck_listing(agent, session_id: str, row) -> None:
    """One pass-1 unit: revisit a tracked listing and record its current
    price/availability. Raises on failure — the orchestrator counts it."""
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

    async for step in agent.astream(
        {"messages": [{"role": "user", "content": prompt}]},
        config=agent_config(session_id, user_id),
        stream_mode="values",
    ):
        step["messages"][-1].pretty_print()


async def scan_pair(agent, session_id: str, row, known_urls: list, market: dict | None) -> None:
    """One pass-2 unit: search a site for new listings for one watch. Raises
    on failure — the orchestrator counts it."""
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
        known_urls=known_urls,
        rejected_checks=rejected_checks,
        market=market,
        expected_price=str(expected_price) if expected_price is not None else None,
        condition_hint=condition_hint,
    )

    async for step in agent.astream(
        {"messages": [{"role": "user", "content": prompt}]},
        config=agent_config(session_id, user_id),
        stream_mode="values",
    ):
        step["messages"][-1].pretty_print()


async def execute_run(run: dict) -> dict | None:
    """
    Execute a claimed run: the two scrape passes, limited to the run's scope,
    emitting run_events as work progresses and polling for cooperative
    cancellation between units (each unit is one full LLM stream — the finest
    granularity that doesn't hook into the stream itself).

    Returns the run's stats on completion, or None if the run was cancelled —
    the API already wrote the terminal state in that case, so the caller must
    not write another.
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

    recheck_agent, scan_agent = await build_pass_agents()

    # Here we get the current listing for tracked listings and check if active and updateprice
    log.info("Starting scan on current listings")

    listed_items_list = await get_listed_items(run["scope"], run["scope_id"])
    current_listing_urls = []
    for row in listed_items_list:
        if await get_run_status(run_id) == "cancelled":
            log.info(f"Run {run_id} cancelled; stopping before listing {row['listing_id']}")
            return None

        try:
            await recheck_listing(recheck_agent, session_id, row)
            current_listing_urls.append(row["listing_url"])
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

    # We scan the sites and ingore all the already seen and currently tracked listings
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

        await append_run_event(
            run_id,
            "info",
            "item_started",
            f'Searching {row["site_name"]} for "{row["item_name"]}"…',
            {"item_id": int(item_id), "site_id": int(row["site_id"])},
        )
        try:
            await scan_pair(scan_agent, session_id, row, current_listing_urls, markets[item_id])
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

    stats = read_run_stats()
    stats["errors"] += errors
    return stats


async def _drive(run_row: dict) -> None:
    """
    Execute a run and own its terminal write — main.py's catch only logs, so
    an agent_runs row must never leave here still 'running'.
    """
    try:
        stats = await execute_run(run_row)
    except Exception as e:
        await finish_run(run_row["id"], "failed", error=str(e))
        raise
    finally:
        # Langfuse queues events on a background thread; flush before this
        # batch job exits or the tail of the run's traces is silently dropped.
        if LANGFUSE_ENABLED:
            get_client().flush()

    # stats None = cancelled: the API already wrote the terminal state
    if stats is not None:
        await finish_run(run_row["id"], "succeeded", stats=stats)


async def run() -> None:
    """
    The scheduled full sweep: record a global agent_runs row for this
    invocation, then execute it. It kicks off even if an API-triggered run is
    active — the one-active-run guard belongs to the API's enqueue; a
    conditional skip here would let one stale 'running' row silently stop
    every future sweep.
    """
    await _drive(await create_global_run())


async def consume() -> None:
    """
    One run-queue tick: claim the oldest queued run — user clicks beat
    schedules — else fire the most-overdue due run_schedules row as a fresh
    run; exit immediately when neither exists. Cron this every minute so
    UI-triggered runs start promptly and schedules fire on time.
    """
    claimed = await claim_queued_run()
    if claimed is None:
        claimed = await claim_due_schedule()
    if claimed is None:
        log.info("No queued runs or due schedules")
        return
    await _drive(claimed)
