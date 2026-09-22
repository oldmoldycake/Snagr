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


# --- schema the models don't describe ----------------------------------------
# create_all builds tables and their own constraints. The queue's central rule
# is a partial unique index over coalesce() expressions, and its wake-up is a
# set of triggers; the backend owns both (D1), so the DB-backed tests install
# them by hand — the same thing backend/tests/conftest.py does with the
# trigger DDL. Keep in sync with
# backend/migrations/versions/015_jobs_daemon.py.

OPEN_JOB_INDEX = """
    CREATE UNIQUE INDEX uq_jobs_open ON jobs (
        kind,
        coalesce(listing_id, 0),
        coalesce(watch_id, 0),
        coalesce(site_id, 0),
        coalesce(item_id, 0)
    ) WHERE status IN ('pending', 'running')
"""

JOB_NOTIFY_DDL = [
    """
    CREATE OR REPLACE FUNCTION notify_job() RETURNS trigger AS $$
    BEGIN
        PERFORM pg_notify(
            'snagr_jobs',
            json_build_object('id', NEW.id, 'kind', NEW.kind, 'status', NEW.status)::text
        );
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE OR REPLACE FUNCTION notify_job_event() RETURNS trigger AS $$
    BEGIN
        PERFORM pg_notify(
            'snagr_job_events',
            json_build_object('job_id', NEW.job_id, 'seq', NEW.seq)::text
        );
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE OR REPLACE FUNCTION notify_price_check() RETURNS trigger AS $$
    BEGIN
        PERFORM pg_notify('snagr_job_events', json_build_object('check', NEW.id)::text);
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER jobs_insert_notify
        AFTER INSERT ON jobs
        FOR EACH ROW EXECUTE FUNCTION notify_job()
    """,
    """
    CREATE TRIGGER jobs_status_notify
        AFTER UPDATE OF status ON jobs
        FOR EACH ROW
        WHEN (OLD.status IS DISTINCT FROM NEW.status)
        EXECUTE FUNCTION notify_job()
    """,
    """
    CREATE TRIGGER job_events_notify
        AFTER INSERT ON job_events
        FOR EACH ROW EXECUTE FUNCTION notify_job_event()
    """,
    """
    CREATE TRIGGER price_checks_notify
        AFTER INSERT ON price_checks
        FOR EACH ROW EXECUTE FUNCTION notify_price_check()
    """,
]


# The site every seeded scenario is on. Tool URLs are checked against the
# site's own registrable domain (S2), so a test URL has to live on it.
SITE_BASE_URL = "https://example.test"


def unit_runtime(**overrides):
    """A ToolRuntime the way the tool node injects it, carrying a UnitContext
    on the run config — watch 1 / item 1 / site 1 on SITE_BASE_URL unless
    overridden, which is what a freshly seeded scenario gets after RESTART
    IDENTITY. The tools read nothing else off it."""
    # imported here, not at module top: the env block above must run before
    # any agent module is imported
    from langchain.tools import ToolRuntime
    from observations import UnitContext

    context = UnitContext(
        **{
            "watch_id": 1,
            "item_id": 1,
            "site_id": 1,
            "site_base_url": SITE_BASE_URL,
            **overrides,
        }
    )
    return ToolRuntime(
        state={},
        context=None,
        config={"configurable": {"unit": context}},
        stream_writer=lambda _: None,
        tool_call_id=None,
        store=None,
    )
