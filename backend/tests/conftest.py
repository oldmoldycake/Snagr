"""Shared pytest fixtures.

Tests run against a throwaway `snagr_test` database (same server, different
DB name) so they NEVER touch the live data the agent writes to. The redirect
happens by exporting DATABASE_URL *before* any `app.*` import below — that's
what pydantic-settings resolves first, beating the value in .env.

Schema comes from Base.metadata.create_all — `alembic check` keeps the models
and migrations in agreement, so this matches what migrations would build.
"""

import os
from pathlib import Path

from dotenv import dotenv_values

# --- MUST run before any `app.*` import --------------------------------------
_env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
_live_url = os.environ.get("DATABASE_URL") or _env["DATABASE_URL"]
_test_url = _live_url.rsplit("/", 1)[0] + "/snagr_test"
assert _test_url != _live_url, "test DB must not be the live DB"
os.environ["DATABASE_URL"] = _test_url
# ------------------------------------------------------------------------------

import pytest
from app import models  # noqa: F401 — registers every table on Base.metadata
from app.database import Base, _sessionmaker
from app.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

# every mutating request must carry the CSRF header, like the frontend does
CSRF = {"X-Snagr-Csrf": "1"}

_ALL_TABLES = ", ".join(t.name for t in Base.metadata.sorted_tables)

# create_all knows nothing about triggers, so the pg_notify plumbing the SSE
# hub and the notification dispatcher listen to is installed here by hand —
# keep in sync with migrations/versions/007_run_notify_triggers.py and
# migrations/versions/010_notification_channels_outbox.py
_NOTIFY_DDL = [
    """
    CREATE OR REPLACE FUNCTION notify_run_event() RETURNS trigger AS $$
    BEGIN
        PERFORM pg_notify(
            'snagr_run_events',
            json_build_object('kind', 'event', 'run_id', NEW.run_id, 'seq', NEW.seq)::text
        );
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE OR REPLACE FUNCTION notify_run_status() RETURNS trigger AS $$
    BEGIN
        PERFORM pg_notify(
            'snagr_run_events',
            json_build_object('kind', 'status', 'run_id', NEW.id, 'status', NEW.status)::text
        );
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER run_events_notify
        AFTER INSERT ON run_events
        FOR EACH ROW EXECUTE FUNCTION notify_run_event()
    """,
    """
    CREATE TRIGGER agent_runs_insert_notify
        AFTER INSERT ON agent_runs
        FOR EACH ROW EXECUTE FUNCTION notify_run_status()
    """,
    """
    CREATE TRIGGER agent_runs_status_notify
        AFTER UPDATE OF status ON agent_runs
        FOR EACH ROW
        WHEN (OLD.status IS DISTINCT FROM NEW.status)
        EXECUTE FUNCTION notify_run_status()
    """,
    """
    CREATE OR REPLACE FUNCTION notify_outbox() RETURNS trigger AS $$
    BEGIN
        PERFORM pg_notify(
            'snagr_notifications',
            json_build_object('outbox_id', NEW.id)::text
        );
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER notification_outbox_notify
        AFTER INSERT ON notification_outbox
        FOR EACH ROW EXECUTE FUNCTION notify_outbox()
    """,
]


def _engine():
    return _sessionmaker().kw["bind"]


@pytest.fixture(scope="session", autouse=True)
async def _schema():
    """Create the full schema in snagr_test once, drop it when the run ends."""
    async with _engine().begin() as conn:
        # pgvector is a project-wide prerequisite (migration 009). Dev test
        # roles typically own snagr_test, so creating the extension here works;
        # when it can't, fail with the migration's pointer — never skip silently.
        try:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception as exc:
            raise RuntimeError(
                "Snagr tests require the pgvector extension in snagr_test and could not "
                "create it. Run `CREATE EXTENSION vector;` there as your Postgres admin "
                "(see README → Requirements), then re-run pytest."
            ) from exc
        await conn.run_sync(Base.metadata.drop_all)  # clear leftovers from a crashed run
        await conn.run_sync(Base.metadata.create_all)
        for ddl in _NOTIFY_DDL:
            await conn.execute(text(ddl))
    yield
    async with _engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine().dispose()


@pytest.fixture(autouse=True)
async def _clean_tables():
    """Every test starts from an empty database."""
    yield
    async with _engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {_ALL_TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def make_client():
    """Factory for extra clients — each has its own cookie jar, so tests can
    act as several people (admin + invitee) at once."""
    clients: list[AsyncClient] = []

    async def _make() -> AsyncClient:
        c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(c)
        return c

    yield _make
    for c in clients:
        await c.aclose()


@pytest.fixture
def db_session():
    """Direct DB access for seeding data the API can't create yet."""
    return _sessionmaker()


@pytest.fixture
async def sc(db_session):
    """A Scenario builder on an open session — see tests/factories.py.

    The aggregates live below the HTTP layer, so those tests call the service
    functions directly with `sc.db` rather than going through a client.
    """
    from tests.factories import Scenario

    async with db_session() as session:
        scenario = Scenario(session)
        await scenario.user()  # so sc.user_id is usable without ceremony
        yield scenario
