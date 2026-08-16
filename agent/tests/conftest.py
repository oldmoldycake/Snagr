"""Environment shims so the agent modules import — and connect — safely.

config.py and database.py read the environment at import time (database
asserts DATABASE_URL exists, pricing constructs a chat model). Most tests
monkeypatch every seam and never open a connection or call a model, but
test_run_queue_db.py really connects — so DATABASE_URL is force-rewritten to
the throwaway `snagr_test` database (same server, different DB name) before
any module import, exactly like backend/tests/conftest.py, and an exported
live URL can never leak in. The AI_* and MCP values only need to exist, not
work.
"""

import os
from pathlib import Path

from dotenv import dotenv_values

# --- MUST run before any agent-module import ----------------------------------
_here = Path(__file__).resolve()
# agent/.env often keeps .env.example's placeholder URL because deployments
# inject DATABASE_URL — an unedited copy doesn't count as configuration.
_PLACEHOLDER = "postgresql+asyncpg://user:password@host:5432/dbname"


def _configured_url() -> str:
    """First usable URL: env var, agent/.env, then backend/.env (both suites
    share the one Postgres server), then a localhost default."""
    candidates = [
        os.environ.get("DATABASE_URL"),
        dotenv_values(_here.parents[1] / ".env").get("DATABASE_URL"),
        dotenv_values(_here.parents[2] / "backend" / ".env").get("DATABASE_URL"),
    ]
    for url in candidates:
        if url and url != _PLACEHOLDER:
            return url
    return "postgresql+asyncpg://snagr:snagr@localhost:5432/snagr"


_live_url = _configured_url()
_test_url = _live_url.rsplit("/", 1)[0] + "/snagr_test"
assert _test_url != _live_url, "test DB must not be the live DB"
os.environ["DATABASE_URL"] = _test_url
# ------------------------------------------------------------------------------

os.environ.setdefault("AI_PROVIDER", "openai")
os.environ.setdefault("AI_MODEL", "test-model")
os.environ.setdefault("AI_API_KEY", "test-key")
os.environ.setdefault("PLAYWRIGHT_MCP_URL", "http://localhost:9999/mcp")
