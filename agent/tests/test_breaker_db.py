"""The per-site circuit breaker against a real Postgres.

The interesting parts are all transactional — the counter, the pause it
trips, the doubling wait, and the queue going quiet for that site — so they
are tested where they live rather than through a fake. Same harness as
test_jobs_db.py: the throwaway `snagr_test` database, one module-wide event
loop, no pytest-asyncio.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import breaker
import jobs as job_queue
import pytest
from database import AsyncSessionLocal, Base, Categories, Items, JobEvents, Jobs, Sites, engine
from sqlalchemy import select, text

NOW = datetime.now(UTC)

_ALL_TABLES = ", ".join(t.name for t in Base.metadata.sorted_tables)

_LOOP = asyncio.new_event_loop()


def db(coro):
    """Run one coroutine on the module's shared event loop."""
    return _LOOP.run_until_complete(coro)


@pytest.fixture(scope="module", autouse=True)
def _schema():
    async def create():
        async with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                await conn.execute(text(f"DROP TABLE IF EXISTS {table.name} CASCADE"))
            await conn.run_sync(Base.metadata.create_all)

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
    yield

    async def truncate():
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {_ALL_TABLES} RESTART IDENTITY CASCADE"))

    db(truncate())


async def seed_site(name: str = "GameBay") -> int:
    async with AsyncSessionLocal() as session:
        site = Sites(name=name, base_url=f"https://{name.lower()}.test")
        session.add(site)
        await session.flush()
        site_id = site.id
        await session.commit()
    return site_id


async def seed_job(site_id: int, kind: str = "hunt", **overrides) -> int:
    """A pending job on this site, with the item a ground job would need."""
    async with AsyncSessionLocal() as session:
        category = Categories(name="Games", slug="games")
        session.add(category)
        await session.flush()
        item = Items(category_id=category.id, name="Emerald")
        session.add(item)
        await session.flush()
        job = Jobs(kind=kind, site_id=site_id, item_id=item.id, **overrides)
        session.add(job)
        await session.flush()
        job_id = job.id
        await session.commit()
    return job_id


async def read_site(site_id: int) -> dict:
    async with AsyncSessionLocal() as session:
        site = await session.get(Sites, site_id)
        return {
            "consecutive_errors": site.consecutive_errors,
            "paused_until": site.paused_until,
            "paused_reason": site.paused_reason,
        }


async def fail(site_id: int, times: int, **kwargs) -> breaker.Pause | None:
    """Fail this site `times` times in a row; returns the last trip, if any."""
    pause = None
    for _ in range(times):
        pause = await breaker.record_outcome(site_id, False, **kwargs) or pause
    return pause


class TestCounting:
    def test_four_bad_reads_are_not_a_wall(self):
        async def scenario():
            site_id = await seed_site()
            pause = await fail(site_id, 4)
            return pause, await read_site(site_id)

        pause, site = db(scenario())
        assert pause is None
        assert site["consecutive_errors"] == 4
        assert site["paused_until"] is None

    def test_one_good_read_wipes_the_count(self):
        async def scenario():
            site_id = await seed_site()
            await fail(site_id, 4)
            await breaker.record_outcome(site_id, True)
            return await read_site(site_id)

        assert db(scenario())["consecutive_errors"] == 0

    def test_a_site_that_never_answers_is_paused(self):
        async def scenario():
            site_id = await seed_site()
            pause = await fail(site_id, 5, detail="challenge page")
            return pause, await read_site(site_id)

        pause, site = db(scenario())
        assert pause is not None
        assert pause.reason == "5 consecutive read errors: challenge page"
        assert site["paused_reason"] == pause.reason
        assert (
            timedelta(minutes=55) < site["paused_until"] - datetime.now(UTC) <= timedelta(hours=1)
        )


class TestDoubling:
    """The trip count is read off the error counter: only a success resets it,
    so five more failures after a pause means this site has now tripped twice
    without ever answering."""

    def test_a_wall_that_is_still_there_costs_twice_as_long(self):
        async def scenario():
            site_id = await seed_site()
            await fail(site_id, 5)
            await fail(site_id, 5)
            return await read_site(site_id)

        site = db(scenario())
        assert timedelta(hours=1, minutes=55) < site["paused_until"] - datetime.now(UTC)
        assert site["paused_until"] - datetime.now(UTC) <= timedelta(hours=2)

    def test_the_wait_stops_growing_at_the_cap(self):
        async def scenario():
            site_id = await seed_site()
            # 60 · 120 · 240 · 480 · 960 · 1920 — the sixth trip would pass the
            # 24-hour cap
            await fail(site_id, 30)
            return await read_site(site_id)

        site = db(scenario())
        assert site["paused_until"] - datetime.now(UTC) <= timedelta(days=1)
        assert site["paused_until"] - datetime.now(UTC) > timedelta(hours=23)


class TestTheQueueGoesQuiet:
    def test_a_paused_sites_work_is_not_claimed(self):
        # the whole point: no browser opens and no model is asked to look
        async def scenario():
            site_id = await seed_site()
            await seed_job(site_id)
            await fail(site_id, 5)
            return await job_queue.claim("w1", ("hunt", "ground"))

        assert db(scenario()) is None

    def test_pending_work_waits_for_the_pause_to_lift(self):
        async def scenario():
            site_id = await seed_site()
            job_id = await seed_job(site_id, run_after=NOW)
            await fail(site_id, 5)
            async with AsyncSessionLocal() as session:
                job = await session.get(Jobs, job_id)
                return job.run_after, job.reason, (await read_site(site_id))["paused_until"]

        run_after, reason, paused_until = db(scenario())
        assert run_after == paused_until
        assert reason == "paused"

    def test_a_persons_own_request_waits_but_stays_theirs(self):
        # the reason is what tells a "hunt now" apart when a watch's hunting
        # is switched off; relabelled 'paused', it would be cancelled
        async def scenario():
            site_id = await seed_site()
            job_id = await seed_job(site_id, run_after=NOW, reason="user", priority=100)
            await fail(site_id, 5)
            async with AsyncSessionLocal() as session:
                job = await session.get(Jobs, job_id)
                return job.run_after, job.reason, (await read_site(site_id))["paused_until"]

        run_after, reason, paused_until = db(scenario())
        assert run_after == paused_until
        assert reason == "user"

    def test_another_sites_work_is_untouched(self):
        async def scenario():
            paused_id = await seed_site("GameBay")
            other_id = await seed_site("CardBay")
            await seed_job(other_id)
            await fail(paused_id, 5)
            return await job_queue.claim("w1", ("hunt", "ground"))

        claimed = db(scenario())
        assert claimed is not None

    def test_the_llm_fallback_asks_first(self):
        async def scenario():
            site_id = await seed_site()
            before = await breaker.is_paused(site_id)
            await fail(site_id, 5)
            return before, await breaker.is_paused(site_id)

        before, after = db(scenario())
        assert before is None
        assert after is not None


class TestTheTripIsAnnounced:
    def test_the_job_that_tripped_it_says_so(self):
        async def scenario():
            site_id = await seed_site()
            job_id = await seed_job(site_id)
            await fail(site_id, 5, job_id=job_id, detail="challenge page")
            async with AsyncSessionLocal() as session:
                events = (
                    (await session.execute(select(JobEvents).where(JobEvents.job_id == job_id)))
                    .scalars()
                    .all()
                )
                return [(e.level, e.event_type, e.message, e.payload) for e in events]

        events = db(scenario())
        assert len(events) == 1
        level, event_type, message, payload = events[0]
        assert (level, event_type) == ("warn", "site_paused")
        assert "GameBay paused until" in message
        assert payload["paused_reason"] == "5 consecutive read errors: challenge page"

    def test_a_read_that_did_not_trip_it_says_nothing(self):
        async def scenario():
            site_id = await seed_site()
            job_id = await seed_job(site_id)
            await fail(site_id, 4, job_id=job_id)
            async with AsyncSessionLocal() as session:
                return await session.scalar(select(JobEvents.id))

        assert db(scenario()) is None
