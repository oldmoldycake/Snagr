"""Environment-driven configuration for the LLM provider and the Playwright
MCP server, loaded from .env."""

import os

from dotenv import load_dotenv

load_dotenv()

# AI
AI_PROVIDER = os.getenv("AI_PROVIDER", "open_router")
AI_URL = os.getenv("AI_URL", "http://localhost:11434")
AI_MODEL = os.getenv("AI_MODEL", "qwen3.6:35b")
AI_API_KEY = os.getenv("AI_API_KEY", None)

# MCP
PLAYWRIGHT_MCP_URL = os.getenv("PLAYWRIGHT_MCP_URL")

# Visual authenticity (vision sidecar). None = feature off: the check_images
# tool is not registered and the scan prompt carries no photo-check block.
VISION_SIDECAR_URL = os.getenv("VISION_SIDECAR_URL")
# Hard cap on one sidecar call — a wedged sidecar must never stall a run.
VISION_TIMEOUT_SECONDS = int(os.getenv("VISION_TIMEOUT_SECONDS", "90"))

# Market grounding. Prices in other currencies are recorded but never mixed
# into stats - a $226/€208 blend is a number with no meaning.
EXPECTED_CURRENCY = os.getenv("EXPECTED_CURRENCY", "USD")
SEARXNG_URL = os.getenv("SEAR_XNG_URL")
# One knob governs both staleness and retry backoff: stats older than the TTL
# refresh, and an item attempted within it is not attempted again.
MARKET_PRICE_TTL_HOURS = int(os.getenv("MARKET_PRICE_TTL_HOURS", "24"))
MARKET_PRICE_MAX_REFRESH_PER_RUN = int(os.getenv("MARKET_PRICE_MAX_REFRESH_PER_RUN", "10"))

# Run lifecycle. The heartbeat is the liveness signal the stale-run reaper
# judges by: a 'running' agent_runs row whose heartbeat is older than
# RUN_STALE_AFTER_SECONDS was left behind by a dead process (SIGKILL, OOM,
# power loss) and is failed on the next consumer tick — left alone it would
# block every enqueue (409 run_in_progress) and every schedule forever.
RUN_HEARTBEAT_INTERVAL_SECONDS = int(os.getenv("RUN_HEARTBEAT_INTERVAL_SECONDS", "30"))
RUN_STALE_AFTER_SECONDS = int(os.getenv("RUN_STALE_AFTER_SECONDS", "300"))
# Per-unit budgets. One unit is one LLM stream (a listing recheck or a site
# scan); a model looping on a blocked page is otherwise bounded only by
# prompt text. Tripping either cap fails that unit and the run moves on.
# Steps are graph steps — roughly two per tool call.
AGENT_MAX_STEPS = int(os.getenv("AGENT_MAX_STEPS", "200"))
AGENT_UNIT_TIMEOUT_SECONDS = int(os.getenv("AGENT_UNIT_TIMEOUT_SECONDS", "900"))

# Target-hit notifications need no delivery config here: the agent only
# queues notification_outbox rows — the backend's dispatcher owns delivery
# and the per-user channels. This is the spam floor under the edge trigger:
# a watch that just queued a target-hit stays quiet this long even if its
# price crosses the target again.
NOTIFY_COOLDOWN_HOURS = int(os.getenv("NOTIFY_COOLDOWN_HOURS", "24"))

# Observability (both optional). LangSmith is read by langchain itself from LANGSMITH_*;
# Langfuse only needs an on/off signal here — its SDK reads its own vars.
LANGFUSE_ENABLED = bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))

# Deterministic rechecks. CHEAP_RECHECK is the kill switch: false puts
# every recheck back through the LLM, which is how the agent behaved before
# locators existed. A locator that stops resolving is not trusted forever —
# after LOCATOR_MAX_FAILURES misses it is cleared so the next LLM read learns
# a fresh one. STATIC_FETCH governs only the browserless rung: a listing whose
# learn-time probe found the same price in the raw HTML is re-read with a
# plain GET, and turning this off costs a page load, never a reading.
CHEAP_RECHECK = os.getenv("CHEAP_RECHECK", "true").lower() != "false"
LOCATOR_MAX_FAILURES = int(os.getenv("LOCATOR_MAX_FAILURES", "3"))
STATIC_FETCH = os.getenv("STATIC_FETCH", "true").lower() != "false"

# Price plausibility bands. A read outside one is anomalous — recorded, but
# never notified and never charted until a second read agrees with it (§4.3):
# the page that says "$4.49" for a $449 item must not wake a buying bot.
# LOW/HIGH bound the ratio against this listing's own last price; FLOOR bounds
# it against the item's market median. Any of them set to 0 disables that band.
PRICE_BAND_LOW = float(os.getenv("PRICE_BAND_LOW", "0.2"))
PRICE_BAND_HIGH = float(os.getenv("PRICE_BAND_HIGH", "5"))
PRICE_MARKET_FLOOR = float(os.getenv("PRICE_MARKET_FLOOR", "0.1"))
