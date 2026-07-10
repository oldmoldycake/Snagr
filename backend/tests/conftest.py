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
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app import models  # noqa: F401 — registers every table on Base.metadata
from app.database import Base, _sessionmaker
from app.main import app

# every mutating request must carry the CSRF header, like the frontend does
CSRF = {"X-Snagr-Csrf": "1"}

_ALL_TABLES = ", ".join(t.name for t in Base.metadata.sorted_tables)


def _engine():
    return _sessionmaker().kw["bind"]


@pytest.fixture(scope="session", autouse=True)
async def _schema():
    """Create the full schema in snagr_test once, drop it when the run ends."""
    async with _engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)   # clear leftovers from a crashed run
        await conn.run_sync(Base.metadata.create_all)
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
