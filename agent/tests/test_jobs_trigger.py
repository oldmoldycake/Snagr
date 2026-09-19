"""The wake-up, end to end: a committed row reaching a LISTEN connection.

This is the only test in the repo that proves migration 015's triggers
actually announce anything — and the daemon's whole idle cost rests on them
(one LISTEN connection, no polling). A raw asyncpg connection listens, the
ORM writes, and the payload is read off the wire exactly as worker.py and the
backend's SSE hub read it.

Same harness as test_jobs_db.py: the throwaway `snagr_test` database, one
module-wide event loop, no pytest-asyncio. The trigger DDL comes from
conftest, because create_all knows nothing about triggers.
"""

import asyncio
import json
from datetime import UTC, datetime

import asyncpg
import pytest
from conftest import JOB_NOTIFY_DDL
from database import (
    DATABASE_URL,
    AsyncSessionLocal,
    Base,
    Categories,
    Items,
    JobEvents,
    Jobs,
    Listings,
    PriceChecks,
    Sites,
    User,
    Watches,
    engine,
)
from sqlalchemy import text

# how long to give a notification before calling it lost — generous, because
# a busy machine is not a broken trigger
DELIVERY_TIMEOUT_SECONDS = 5

_ALL_TABLES = ", ".join(t.name for t in Base.metadata.sorted_tables)

_LOOP = asyncio.new_event_loop()


def db(coro):
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    async def create():
        async with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                await conn.execute(text(f"DROP TABLE IF EXISTS {table.name} CASCADE"))
            await conn.run_sync(Base.metadata.create_all)
            for ddl in JOB_NOTIFY_DDL:
                await conn.execute(text(ddl))

    async def drop():
        async with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                await conn.execute(text(f"DROP TABLE IF EXISTS {table.name} CASCADE"))

    db(create())
    yield
    db(drop())
    db(engine.dispose())
    _LOOP.close()


@pytest.fixture(autouse=True)
def _clean_tables():
    """Every test starts from an empty database."""
    yield

    async def truncate():
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {_ALL_TABLES} RESTART IDENTITY CASCADE"))

    db(truncate())


class Heard:
    """A raw LISTEN connection, holding whatever arrived."""

    def __init__(self, conn, channel: str):
        self.conn = conn
        self.channel = channel
        self.payloads: asyncio.Queue[str] = asyncio.Queue()

    async def next(self) -> dict:
        """The next payload, decoded. Fails the test rather than hanging when
        nothing arrives — a silent trigger is the bug this file exists for."""
        try:
            raw = await asyncio.wait_for(self.payloads.get(), timeout=DELIVERY_TIMEOUT_SECONDS)
        except TimeoutError:
            raise AssertionError(f"nothing was announced on {self.channel}") from None
        return json.loads(raw)

    def empty(self) -> bool:
        return self.payloads.empty()


async def listening(channel: str) -> Heard:
    # asyncpg wants a plain postgres:// DSN, without SQLAlchemy's driver tag
    conn = await asyncpg.connect(DATABASE_URL.replace("+asyncpg", ""))
    heard = Heard(conn, channel)
    await conn.add_listener(channel, lambda *args: heard.payloads.put_nowait(args[-1]))
    return heard


async def seed_graph() -> dict:
    """A user, item, site, watch and listing — enough for any of the rows a
    trigger fires on."""
    async with AsyncSessionLocal() as session:
        category = Categories(name="Games", slug="games")
        site = Sites(name="GameBay", base_url="https://gamebay.test")
        user = User(email="agent@test.local")
        session.add_all([category, site, user])
        await session.flush()
        item = Items(category_id=category.id, name="Emerald")
        session.add(item)
        await session.flush()
        watch = Watches(user_id=user.id, item_id=item.id)
        session.add(watch)
        await session.flush()
        listing = Listings(
            watch_id=watch.id, item_id=item.id, site_id=site.id, url="https://gamebay.test/l1"
        )
        session.add(listing)
        await session.flush()
        ids = {
            "item": item.id,
            "site": site.id,
            "watch": watch.id,
            "listing": listing.id,
        }
        await session.commit()
    return ids


async def insert_job(ids: dict, **overrides) -> int:
    async with AsyncSessionLocal() as session:
        fields = {
            "kind": "recheck",
            "watch_id": ids["watch"],
            "item_id": ids["item"],
            "site_id": ids["site"],
            "listing_id": ids["listing"],
            **overrides,
        }
        job = Jobs(**fields)
        session.add(job)
        await session.flush()
        job_id = job.id
        await session.commit()
    return job_id


class TestJobsChannel:
    """'snagr_jobs' is what wakes the daemon. An insert has to announce
    itself — a job born pending never fires an UPDATE for its own arrival."""

    def test_a_new_job_announces_itself(self):
        async def scenario():
            heard = await listening("snagr_jobs")
            try:
                ids = await seed_graph()
                job_id = await insert_job(ids)
                return job_id, await heard.next()
            finally:
                await heard.conn.close()

        job_id, note = db(scenario())
        assert note == {"id": job_id, "kind": "recheck", "status": "pending"}

    def test_a_status_change_announces_itself(self):
        async def scenario():
            ids = await seed_graph()
            job_id = await insert_job(ids)
            heard = await listening("snagr_jobs")
            try:
                async with AsyncSessionLocal() as session:
                    job = await session.get(Jobs, job_id)
                    job.status = "running"
                    await session.commit()
                return job_id, await heard.next()
            finally:
                await heard.conn.close()

        job_id, note = db(scenario())
        assert note == {"id": job_id, "kind": "recheck", "status": "running"}

    def test_a_change_that_is_not_the_status_says_nothing(self):
        # heartbeats are the loudest write in the system; announcing them
        # would wake every worker several times a minute for nothing
        async def scenario():
            ids = await seed_graph()
            job_id = await insert_job(ids)
            heard = await listening("snagr_jobs")
            try:
                async with AsyncSessionLocal() as session:
                    job = await session.get(Jobs, job_id)
                    job.heartbeat_at = datetime.now(UTC)
                    await session.commit()
                await asyncio.sleep(0.2)
                return heard.empty()
            finally:
                await heard.conn.close()

        assert db(scenario()) is True


class TestJobEventsChannel:
    """'snagr_job_events' is what puts a hunt's log and every price check on
    the Activity page as they happen."""

    def test_a_job_event_announces_its_job_and_seq(self):
        async def scenario():
            ids = await seed_graph()
            job_id = await insert_job(ids, kind="hunt", listing_id=None)
            heard = await listening("snagr_job_events")
            try:
                async with AsyncSessionLocal() as session:
                    session.add(
                        JobEvents(
                            job_id=job_id,
                            seq=1,
                            ts=datetime.now(UTC),
                            level="info",
                            event_type="job_started",
                            message="Hunting GameBay…",
                        )
                    )
                    await session.commit()
                return job_id, await heard.next()
            finally:
                await heard.conn.close()

        job_id, note = db(scenario())
        assert note == {"job_id": job_id, "seq": 1}

    def test_a_price_check_announces_itself_whoever_wrote_it(self):
        # the frame carries the check's id and nothing else: the hub re-reads
        # the row, so the announcement can never outrun what is readable
        async def scenario():
            ids = await seed_graph()
            heard = await listening("snagr_job_events")
            try:
                async with AsyncSessionLocal() as session:
                    check = PriceChecks(
                        listing_id=ids["listing"],
                        price=49.99,
                        currency="USD",
                        in_stock=True,
                        status="ok",
                        method="jsonld",
                        checked_at=datetime.now(UTC),
                    )
                    session.add(check)
                    await session.flush()
                    check_id = check.id
                    await session.commit()
                return check_id, await heard.next()
            finally:
                await heard.conn.close()

        check_id, note = db(scenario())
        assert note == {"check": check_id}
