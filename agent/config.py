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
# tool is not registered and scan prompts are byte-identical to before.
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

# Target-hit notifications need no delivery config here: the agent only
# queues notification_outbox rows — the backend's dispatcher owns delivery
# and the per-user channels. This is the spam floor under the edge trigger:
# a watch that just queued a target-hit stays quiet this long even if its
# price crosses the target again.
NOTIFY_COOLDOWN_HOURS = int(os.getenv("NOTIFY_COOLDOWN_HOURS", "24"))

# Observability (both optional). LangSmith is read by langchain itself from LANGSMITH_*;
# Langfuse only needs an on/off signal here — its SDK reads its own vars.
LANGFUSE_ENABLED = bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))
