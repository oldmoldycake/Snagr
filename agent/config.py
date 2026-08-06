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

# Observability (both optional). LangSmith is read by langchain itself from LANGSMITH_*;
# Langfuse only needs an on/off signal here — its SDK reads its own vars.
LANGFUSE_ENABLED = bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))
