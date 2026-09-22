"""Migration 015, up and down, against a scratch database.

The rest of the suite runs on a schema built by Base.metadata.create_all, so
nothing else ever executes a revision. This one does: 015 drops three tables
and rewrites stored token scopes, and both of those are only reversible if the
downgrade really puts them back. It builds its own database (`snagr_test_...`)
rather than touching the suite's, and drops it again on the way out.
"""

import os
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest
from app.config import settings

BACKEND = Path(__file__).resolve().parents[1]
ALEMBIC = Path(sys.executable).with_name("alembic")
SCRATCH = "snagr_test_migrations"
# alembic wants the SQLAlchemy URL (driver tag and all); asyncpg wants a plain
# postgres:// DSN, the same split services/events.py makes
SERVER = settings.DATABASE_URL.rsplit("/", 1)[0]
DSN = SERVER.replace("+asyncpg", "")


def _alembic(*args: str) -> None:
    """Run one alembic command against the scratch database."""
    result = subprocess.run(
        [str(ALEMBIC), *args],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": f"{SERVER}/{SCRATCH}"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stderr}"


@pytest.fixture
async def scratch():
    """An empty database at revision 014, with a token minted for runs."""
    admin = await asyncpg.connect(f"{DSN}/postgres")
    await admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}" WITH (FORCE)')
    await admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    await admin.close()

    conn = await asyncpg.connect(f"{DSN}/{SCRATCH}")
    # migration 009 refuses to run without it, and says so rather than guessing
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    _alembic("upgrade", "014")
    user_id = await conn.fetchval("INSERT INTO users (email) VALUES ('mig@test') RETURNING id")
    await conn.execute(
        "INSERT INTO api_tokens (user_id, name, token_hash, scopes) "
        "VALUES ($1, 'runner', 'hash', '[\"read\", \"runs\"]'::jsonb)",
        user_id,
    )
    try:
        yield conn
    finally:
        await conn.close()
        admin = await asyncpg.connect(f"{DSN}/postgres")
        await admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}" WITH (FORCE)')
        await admin.close()


async def _table(conn, name: str) -> bool:
    return await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", name)


async def test_015_replaces_the_run_tables_with_the_job_queue(scratch):
    _alembic("upgrade", "015")

    assert await _table(scratch, "jobs")
    assert await _table(scratch, "job_events")
    assert not await _table(scratch, "agent_runs")
    assert not await _table(scratch, "run_events")
    assert not await _table(scratch, "run_schedules")

    # the indexes the claim query and the "one open job per target" rule need
    indexes = {
        row["indexname"]
        for row in await scratch.fetch("SELECT indexname FROM pg_indexes WHERE tablename = 'jobs'")
    }
    assert {"uq_jobs_open", "ix_jobs_due", "ix_jobs_watch"} <= indexes

    triggers = [
        row["tgname"]
        for row in await scratch.fetch("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
    ]
    assert {
        "jobs_insert_notify",
        "jobs_status_notify",
        "job_events_notify",
        "price_checks_notify",
    } <= set(triggers)

    # a token minted to trigger runs keeps its power under the new name
    assert await scratch.fetchval("SELECT scopes::text FROM api_tokens") == '["read", "jobs"]'


async def test_015_downgrade_gives_the_run_tables_back_empty(scratch):
    _alembic("upgrade", "015")
    _alembic("downgrade", "014")

    assert await _table(scratch, "agent_runs")
    assert await _table(scratch, "run_events")
    assert await _table(scratch, "run_schedules")
    # empty on purpose: nothing can reconstruct run history, and a half-restored
    # one would be worse than none
    assert await scratch.fetchval("SELECT count(*) FROM agent_runs") == 0

    assert not await _table(scratch, "jobs")
    assert not await _table(scratch, "job_events")
    assert await scratch.fetchval("SELECT scopes::text FROM api_tokens") == '["read", "runs"]'

    # migration 007's own downgrade drops these; leaving them out would strand
    # anyone going further back
    functions = await scratch.fetchval(
        "SELECT count(*) FROM pg_proc WHERE proname IN ('notify_run_event', 'notify_run_status')"
    )
    assert functions == 2
