"""Agent orchestration: builds the LLM agent (model + Playwright MCP browser
tools + database tools) and runs one search per (watch, site) pair.

TODO (Phase 3, D3 — become the run-queue consumer): today this is a bare batch
job with no notion of agent_runs. It still needs to:
  - claim a queued agent_runs row (SELECT ... FOR UPDATE SKIP LOCKED) and limit
    the two passes below to that run's scope/scope_id;
  - write run_events rows + keep status/stats/last_seq updated as it works;
  - re-check the run's status between listings / (watch, site) pairs and abort
    once the API has flipped it to 'cancelled' — cancel_run() in
    backend/app/services/runs.py only flips the row (cancellation is
    cooperative), and bailing early is what stops mid-run LLM token burn.
"""

import logging
import uuid

from config import AI_API_KEY, AI_MODEL, AI_PROVIDER, AI_URL, LANGFUSE_ENABLED, PLAYWRIGHT_MCP_URL
from database import get_checked_urls, get_listed_items, get_market_price, get_watched_item_list
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient
from langfuse import get_client
from langfuse.langchain import CallbackHandler
from pricing import ground_stale
from prompt import generate_prompt, generate_recheck_prompt
from tools import disable_listing, log_listing_check, save_listing, save_price_check

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


async def run():
    """
    Run one full scrape job: connect to the Playwright MCP server, build the
    agent, then for every (watch, site) pair from get_watched_item_list()
    generate a prompt and stream the agent through the search. A failure on
    one pair is logged and skipped so the remaining pairs still run.
    """
    session_id = str(uuid.uuid4())
    log.info(f"Job session {session_id}")

    # Grounding pre-pass: refresh stale market prices first so this run's
    # scan prompts read stats from minutes ago, not last night's. Isolation
    # per the spec: grounding failure must never block the scrape.
    try:
        await ground_stale()
    except Exception as e:
        log.error(f"Grounding pre-pass failed, scraping ungrounded: {e}")

    client = MultiServerMCPClient(
        {
            "playwright": {
                "url": PLAYWRIGHT_MCP_URL,
                "transport": "streamable_http",
            }
        }
    )

    # Here we get the current listing for tracked listings and check if active and updateprice
    log.info("Starting scan on current listings")

    tools = await client.get_tools()
    tools = tools + [save_price_check, disable_listing]

    agent = create_agent(llm, tools)
    listed_items_list = await get_listed_items()
    current_listing_urls = []
    for row in listed_items_list:
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

        try:
            async for step in agent.astream(
                {"messages": [{"role": "user", "content": prompt}]},
                config=agent_config(session_id, user_id),
                stream_mode="values",
            ):
                step["messages"][-1].pretty_print()

            current_listing_urls.append(listing_url)
            log.info(f"Finished recheck for listing {listing_id}")
        except Exception as e:
            log.error(f"Recheck failed for listing {listing_id}: {e}")
            continue

    # We scan the sites and ingore all the already seen and currently tracked listings
    log.info("Starting scan for new items")

    tools = await client.get_tools()
    tools = tools + [save_price_check, save_listing, log_listing_check]

    agent = create_agent(llm, tools)
    watch_site_list = await get_watched_item_list()
    markets: dict[int, dict | None] = {}
    for row in watch_site_list:
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

        if item_id not in markets:
            market_row = await get_market_price(item_id)
            markets[item_id] = dict(market_row) if market_row else None

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
            known_urls=current_listing_urls,
            rejected_checks=rejected_checks,
            market=markets[item_id],
            expected_price=str(expected_price) if expected_price is not None else None,
            condition_hint=condition_hint,
        )
        try:
            async for step in agent.astream(
                {"messages": [{"role": "user", "content": prompt}]},
                config=agent_config(session_id, user_id),
                stream_mode="values",
            ):
                step["messages"][-1].pretty_print()
            log.info(f"Finished {item_name} on site {site_name}")
        except Exception as e:
            log.error(f"Item {item_name} on site {site_name} failed: {e}")
            continue

    # Langfuse queues events on a background thread; flush before this batch
    # job exits or the tail of the run's traces is silently dropped.
    if LANGFUSE_ENABLED:
        get_client().flush()
