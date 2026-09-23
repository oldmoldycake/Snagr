"""The work queue against a real Postgres: the claim's FOR UPDATE SKIP
LOCKED, the partial unique index that keeps one job open per target, the
successor a finished check leaves behind, the reaper, retention, the locked
last_seq bump behind uq_job_seq, the per-unit lookups the pools work from,
and the tools' writes — SQL that the seam tests in test_run_consumer.py
can't exercise.

Needs the same reachable Postgres the backend suite uses. conftest.py
force-rewrites DATABASE_URL to the throwaway `snagr_test` database, so live
data is never touched — building the schema here is a test-harness
affordance, not the agent migrating anything (D1 still holds). Don't run
this suite concurrently with backend/tests: both truncate snagr_test.

No pytest-asyncio here (it isn't a dependency): tests are sync and drive
their coroutines through db(), which runs everything on one module-wide
event loop — asyncpg connections are loop-bound, and keeping a single loop
lets the engine's pool reuse them (a fresh connection to the LAN server
costs seconds; per-test reconnects made the module take minutes).
"""

import asyncio
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import jobs as job_queue
import observations
import pytest
import tools
from conftest import OPEN_JOB_INDEX, unit_runtime
from database import (
    AsyncSessionLocal,
    Base,
    Categories,
    Items,
    JobEvents,
    Jobs,
    ListingChecks,
    Listings,
    NotificationOutbox,
    PriceChecks,
    SiteCategories,
    Sites,
    User,
    Watches,
    WatchSites,
    clear_static_ok,
    deactivate_listing,
    engine,
    get_active_listing_count,
    get_hunt_unit,
    get_known_listing_urls,
    get_recheck_unit,
    has_verified_locator,
    note_locator_failure,
    save_locator,
)
from locators import Locator, site_consensus
from sqlalchemy import func, select, text

NOW = datetime.now(UTC)

_ALL_TABLES = ", ".join(t.name for t in Base.metadata.sorted_tables)


_LOOP = asyncio.new_event_loop()


def db(coro):
    """Run one coroutine on the module's shared event loop."""
    return _LOOP.run_until_complete(coro)


async def _create_schema():
    async with engine.begin() as conn:
        # CASCADE, because a crashed backend suite can leave its superset
        # schema behind, with tables FK-ing into the ones dropped here
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f"DROP TABLE IF EXISTS {table.name} CASCADE"))
        await conn.run_sync(Base.metadata.create_all)
        # the queue's central rule is not in any model — see conftest
        await conn.execute(text(OPEN_JOB_INDEX))


async def _drop_schema():
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f"DROP TABLE IF EXISTS {table.name} CASCADE"))


async def _truncate():
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {_ALL_TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="module", autouse=True)
def _schema():
    """Create the agent's schema in snagr_test once, drop it when done."""
    db(_create_schema())
    yield
    db(_drop_schema())
    db(engine.dispose())
    _LOOP.close()


@pytest.fixture(autouse=True)
def _clean_tables():
    """Every test starts from an empty database."""
    yield
    db(_truncate())


def unit_a(ids, **overrides):
    """The runtime a tool call gets inside one of watch A's units on GameBay.

    site_base_url is GameBay's, because the URL guard (S2) checks every URL a
    tool is handed against the site the unit is for."""
    return unit_runtime(
        watch_id=ids["watch_a"],
        item_id=ids["item_a"],
        site_id=ids["site_a"],
        site_base_url="https://gamebay.test",
        **overrides,
    )


async def seed(*rows) -> list[int]:
    """Insert any model rows; returns their ids (captured before commit expires
    them; None for composite-key rows like watch_sites)."""
    async with AsyncSessionLocal() as session:
        session.add_all(rows)
        await session.flush()
        ids = [getattr(row, "id", None) for row in rows]
        await session.commit()
    return ids


class RecordingClock:
    """A `datetime` stand-in that answers now() truthfully and remembers which
    timezone each caller asked for — None being the naive local answer."""

    def __init__(self):
        self.zones = []

    def now(self, tz=None):
        self.zones.append(tz)
        return datetime.now(tz)

    @contextmanager
    def installed(self):
        """Swap this in for both modules that stamp a row for the duration of
        the body: log_listing_check stamps in tools, and every price check
        now stamps in observations, the one writer of them."""
        real_tools, real_observations = tools.datetime, observations.datetime
        tools.datetime = self
        observations.datetime = self
        try:
            yield
        finally:
            tools.datetime = real_tools
            observations.datetime = real_observations


async def seed_scope_graph() -> dict:
    """Two disjoint (category, site, item, watch, listing) chains, so each
    scope can prove it returns one chain and not the other."""
    async with AsyncSessionLocal() as session:
        cat_a = Categories(name="Games", slug="games")
        cat_b = Categories(name="Cards", slug="cards")
        site_a = Sites(name="GameBay", base_url="https://gamebay.test")
        site_b = Sites(name="CardBay", base_url="https://cardbay.test")
        user = User(email="agent@test.local")
        session.add_all([cat_a, cat_b, site_a, site_b, user])
        await session.flush()

        session.add_all(
            [
                SiteCategories(site_id=site_a.id, category_id=cat_a.id),
                SiteCategories(site_id=site_b.id, category_id=cat_b.id),
            ]
        )
        item_a = Items(category_id=cat_a.id, name="Emerald")
        item_b = Items(category_id=cat_b.id, name="Charizard")
        session.add_all([item_a, item_b])
        await session.flush()

        watch_a = Watches(user_id=user.id, item_id=item_a.id)
        watch_b = Watches(user_id=user.id, item_id=item_b.id)
        session.add_all([watch_a, watch_b])
        await session.flush()

        listing_a = Listings(
            watch_id=watch_a.id, item_id=item_a.id, site_id=site_a.id, url="https://gamebay.test/l1"
        )
        listing_b = Listings(
            watch_id=watch_b.id, item_id=item_b.id, site_id=site_b.id, url="https://cardbay.test/l1"
        )
        session.add_all([listing_a, listing_b])
        await session.flush()

        ids = {
            "cat_a": cat_a.id,
            "cat_b": cat_b.id,
            "site_a": site_a.id,
            "site_b": site_b.id,
            "item_a": item_a.id,
            "item_b": item_b.id,
            "watch_a": watch_a.id,
            "watch_b": watch_b.id,
            "listing_a": listing_a.id,
            "listing_b": listing_b.id,
        }
        await session.commit()
    return ids


def pending_job(ids, kind="recheck", **overrides):
    """A pending job for watch A on GameBay; override any column."""
    fields = {
        "kind": kind,
        "watch_id": ids["watch_a"],
        "item_id": ids["item_a"],
        "site_id": ids["site_a"],
        "listing_id": ids["listing_a"] if kind == "recheck" else None,
        **overrides,
    }
    return Jobs(**fields)


async def read_job(job_id: int) -> dict:
    async with AsyncSessionLocal() as session:
        job = await session.get(Jobs, job_id)
        return {
            "kind": job.kind,
            "status": job.status,
            "priority": job.priority,
            "run_after": job.run_after,
            "attempts": job.attempts,
            "locked_by": job.locked_by,
            "started_at": job.started_at,
            "heartbeat_at": job.heartbeat_at,
            "finished_at": job.finished_at,
            "error": job.error,
            "stats": job.stats,
            "last_seq": job.last_seq,
        }


async def read_jobs(**filters) -> list[dict]:
    """Every job matching the filters, oldest id first."""
    async with AsyncSessionLocal() as session:
        stmt = select(Jobs).order_by(Jobs.id)
        for column, value in filters.items():
            stmt = stmt.where(getattr(Jobs, column) == value)
        return [
            {"id": j.id, "kind": j.kind, "status": j.status, "run_after": j.run_after}
            for j in (await session.execute(stmt)).scalars().all()
        ]


class TestClaim:
    def test_an_empty_queue_returns_none(self):
        assert db(job_queue.claim("w1", ("recheck",))) is None

    def test_a_users_request_jumps_the_queue(self):
        # priority first, then oldest due — a "check prices" click is 100 and
        # must not wait behind an hour of routine checks
        async def scenario():
            ids = await seed_scope_graph()
            routine, urgent = await seed(
                pending_job(ids, run_after=NOW - timedelta(hours=1)),
                pending_job(ids, kind="hunt", priority=100, run_after=NOW),
            )
            return routine, urgent, await job_queue.claim("w1", ("recheck", "hunt"))

        routine, urgent, claimed = db(scenario())
        assert claimed["id"] == urgent
        assert claimed["priority"] == 100

    def test_the_longest_wait_wins_at_equal_priority(self):
        async def scenario():
            ids = await seed_scope_graph()
            older, _ = await seed(
                pending_job(ids, run_after=NOW - timedelta(hours=2)),
                pending_job(ids, kind="hunt", run_after=NOW - timedelta(minutes=1)),
            )
            return older, await job_queue.claim("w1", ("recheck", "hunt"))

        older, claimed = db(scenario())
        assert claimed["id"] == older

    def test_a_job_due_later_waits(self):
        async def scenario():
            ids = await seed_scope_graph()
            await seed(pending_job(ids, run_after=NOW + timedelta(minutes=5)))
            return await job_queue.claim("w1", ("recheck",))

        assert db(scenario()) is None

    def test_a_pool_only_claims_its_own_kinds(self):
        # the check pool runs no model, so it must never pick up a hunt
        async def scenario():
            ids = await seed_scope_graph()
            await seed(pending_job(ids, kind="hunt"))
            return await job_queue.claim("checks", ("recheck",))

        assert db(scenario()) is None

    def test_claiming_stamps_the_worker_and_spends_an_attempt(self):
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(pending_job(ids))
            claimed = await job_queue.claim("check-worker", ("recheck",))
            return claimed, await read_job(job_id)

        claimed, row = db(scenario())
        assert claimed["listing_id"] is not None
        assert row["status"] == "running"
        assert row["locked_by"] == "check-worker"
        assert row["attempts"] == 1
        assert row["started_at"] is not None
        assert row["heartbeat_at"] is not None

    def test_concurrent_claims_have_exactly_one_winner(self):
        # SKIP LOCKED: the loser sees no unlocked due row and gets None
        async def scenario():
            ids = await seed_scope_graph()
            await seed(pending_job(ids))
            return await asyncio.gather(
                job_queue.claim("w1", ("recheck",)), job_queue.claim("w2", ("recheck",))
            )

        results = db(scenario())
        assert sorted(r is None for r in results) == [False, True]

    def test_a_finished_job_is_never_claimed_again(self):
        async def scenario():
            ids = await seed_scope_graph()
            await seed(
                pending_job(ids, status="done", finished_at=NOW),
                pending_job(ids, kind="hunt", status="cancelled", finished_at=NOW),
            )
            return await job_queue.claim("w1", ("recheck", "hunt", "ground"))

        assert db(scenario()) is None


class TestOneOpenJobPerTarget:
    """Migration 015's partial unique index. It is the reason "check now" is a
    bump rather than an insert, and the reason every insert here can be ON
    CONFLICT DO NOTHING."""

    def test_a_second_open_check_for_the_same_listing_is_dropped(self):
        async def scenario():
            ids = await seed_scope_graph()
            await seed(pending_job(ids))
            async with AsyncSessionLocal() as session:
                await job_queue.enqueue_recheck(
                    session,
                    listing_id=ids["listing_a"],
                    watch_id=ids["watch_a"],
                    item_id=ids["item_a"],
                    site_id=ids["site_a"],
                )
                await session.commit()
            return await read_jobs(kind="recheck")

        assert len(db(scenario())) == 1

    def test_a_finished_job_no_longer_holds_the_slot(self):
        async def scenario():
            ids = await seed_scope_graph()
            await seed(pending_job(ids, status="done", finished_at=NOW))
            async with AsyncSessionLocal() as session:
                await job_queue.enqueue_recheck(
                    session,
                    listing_id=ids["listing_a"],
                    watch_id=ids["watch_a"],
                    item_id=ids["item_a"],
                    site_id=ids["site_a"],
                )
                await session.commit()
            return await read_jobs(kind="recheck")

        rows = db(scenario())
        assert [r["status"] for r in rows] == ["done", "pending"]


class TestCompletion:
    """A listing always has exactly one check ahead of it — the chain is what
    keeps it watched, so it is closed in the same transaction that ends the
    check before it."""

    def test_a_finished_check_queues_the_next_one(self):
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(pending_job(ids))
            await job_queue.claim("w1", ("recheck",))
            await job_queue.complete(job_id, {"listings_checked": 1, "prices_found": 1})
            return await read_job(job_id), await read_jobs(status="pending")

        row, pending = db(scenario())
        assert row["status"] == "done"
        assert row["stats"] == {"listings_checked": 1, "prices_found": 1}
        assert len(pending) == 1
        due_in = pending[0]["run_after"] - datetime.now(UTC)
        assert timedelta(minutes=25) < due_in <= timedelta(minutes=30)

    def test_an_untracked_listing_ends_the_chain(self):
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(pending_job(ids))
            await job_queue.claim("w1", ("recheck",))
            async with AsyncSessionLocal() as session:
                listing = await session.get(Listings, ids["listing_a"])
                listing.active = False
                await session.commit()
            await job_queue.complete(job_id, {})
            return await read_jobs(status="pending")

        assert db(scenario()) == []

    def test_a_successor_never_lands_inside_a_pause(self):
        # a paused site is not read whatever the queue says, so a due time
        # inside the pause is a time this check cannot be run at
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(pending_job(ids))
            await job_queue.claim("w1", ("recheck",))
            async with AsyncSessionLocal() as session:
                site = await session.get(Sites, ids["site_a"])
                site.paused_until = NOW + timedelta(hours=3)
                site.paused_reason = "5 consecutive read errors"
                await session.commit()
            await job_queue.complete(job_id, {})
            return await read_jobs(status="pending")

        (successor,) = db(scenario())
        assert successor["run_after"] > NOW + timedelta(hours=2)

    def _successor_due_in(self, interval):
        """Finish one check of a watch whose interval is `interval`; how far
        ahead its successor was queued."""

        async def scenario():
            ids = await seed_scope_graph()
            async with AsyncSessionLocal() as session:
                watch = await session.get(Watches, ids["watch_a"])
                watch.recheck_interval_minutes = interval
                await session.commit()
            (job_id,) = await seed(pending_job(ids))
            await job_queue.claim("w1", ("recheck",))
            await job_queue.complete(job_id, {})
            return await read_jobs(status="pending")

        (successor,) = db(scenario())
        return successor["run_after"] - datetime.now(UTC)

    def test_a_successor_follows_the_watchs_own_interval(self):
        due_in = self._successor_due_in(120)
        assert timedelta(minutes=115) < due_in <= timedelta(minutes=120)

    def test_a_watch_with_no_interval_follows_the_instance_default(self):
        due_in = self._successor_due_in(None)
        assert timedelta(minutes=25) < due_in <= timedelta(minutes=30)

    def test_an_interval_below_the_floor_is_floored(self):
        # the backend refuses one, but a row written by hand still must not
        # turn the hunter into a tight loop against one site
        due_in = self._successor_due_in(1)
        assert timedelta(minutes=4) < due_in <= timedelta(minutes=5)

    def test_a_hunt_leaves_no_successor(self):
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(pending_job(ids, kind="hunt"))
            await job_queue.claim("w1", ("hunt",))
            await job_queue.complete(job_id, {"new_listings": 0})
            return await read_jobs(status="pending")

        assert db(scenario()) == []

    def test_a_cancelled_job_keeps_its_terminal_state(self):
        # the API wrote 'cancelled' while the worker was finishing; the worker
        # must not overwrite it — but the listing still needs its next check
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(pending_job(ids))
            await job_queue.claim("w1", ("recheck",))
            async with AsyncSessionLocal() as session:
                job = await session.get(Jobs, job_id)
                job.status = "cancelled"
                await session.commit()
            wrote = await job_queue.complete(job_id, {"listings_checked": 1})
            return wrote, await read_job(job_id), await read_jobs(status="pending")

        wrote, row, pending = db(scenario())
        assert wrote is False
        assert row["status"] == "cancelled"
        assert row["stats"] is None
        assert len(pending) == 1


class TestFailure:
    def test_a_first_failure_goes_straight_back_in_the_queue(self):
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(pending_job(ids))
            await job_queue.claim("w1", ("recheck",))
            outcome = await job_queue.fail_or_retry(job_id, "the page timed out")
            return outcome, await read_job(job_id)

        outcome, row = db(scenario())
        assert outcome == "pending"
        assert row["status"] == "pending"
        assert row["locked_by"] is None
        assert row["attempts"] == 1
        assert row["error"] == "the page timed out"
        assert row["run_after"] <= datetime.now(UTC)

    def test_a_failed_check_still_queues_the_next_one(self):
        # a page being unreadable today is not a reason to stop watching it
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(pending_job(ids, attempts=2))
            await job_queue.claim("w1", ("recheck",))
            outcome = await job_queue.fail_or_retry(job_id, "challenge page")
            return outcome, await read_job(job_id), await read_jobs(status="pending")

        outcome, row, pending = db(scenario())
        assert outcome == "failed"
        assert row["status"] == "failed"
        assert row["finished_at"] is not None
        assert len(pending) == 1

    def test_a_job_that_already_finished_is_left_alone(self):
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(pending_job(ids, status="cancelled", finished_at=NOW))
            outcome = await job_queue.fail_or_retry(job_id, "too late")
            return outcome, await read_job(job_id)

        outcome, row = db(scenario())
        assert outcome == "cancelled"
        assert row["error"] is None


class TestRelease:
    """Shutdown, not failure: `docker compose stop` costs a restart, not a
    retry budget."""

    def test_an_in_flight_job_goes_back_to_the_queue_due_now(self):
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(pending_job(ids))
            await job_queue.claim("w1", ("recheck",))
            released = await job_queue.release(job_id)
            return released, await read_job(job_id)

        released, row = db(scenario())
        assert released is True
        assert row["status"] == "pending"
        assert row["locked_by"] is None
        assert row["started_at"] is None
        assert row["run_after"] <= datetime.now(UTC)

    def test_a_job_that_is_not_running_is_left_alone(self):
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(pending_job(ids, status="done", finished_at=NOW))
            return await job_queue.release(job_id), await read_job(job_id)

        released, row = db(scenario())
        assert released is False
        assert row["status"] == "done"


class TestReaper:
    """A row abandoned by a SIGKILL holds its target's open-job slot forever,
    and the unique index would refuse every replacement — so nothing else
    would ever notice."""

    def test_a_silent_worker_loses_its_job(self):
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(
                pending_job(
                    ids,
                    status="running",
                    started_at=NOW - timedelta(hours=1),
                    heartbeat_at=NOW - timedelta(minutes=30),
                    attempts=1,
                    locked_by="dead-worker",
                )
            )
            reaped = await job_queue.reap()
            return job_id, reaped, await read_job(job_id)

        job_id, reaped, row = db(scenario())
        assert reaped == [job_id]
        assert row["status"] == "pending"
        assert "no heartbeat" in row["error"]

    def test_a_beating_worker_keeps_its_job(self):
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(
                pending_job(
                    ids, status="running", started_at=NOW - timedelta(hours=1), heartbeat_at=NOW
                )
            )
            return await job_queue.reap(), await read_job(job_id)

        reaped, row = db(scenario())
        assert reaped == []
        assert row["status"] == "running"

    def test_a_job_that_has_died_too_often_is_failed_for_good(self):
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(
                pending_job(
                    ids,
                    kind="hunt",
                    status="running",
                    started_at=NOW - timedelta(hours=1),
                    heartbeat_at=NOW - timedelta(hours=1),
                    attempts=3,
                )
            )
            await job_queue.reap()
            return await read_job(job_id)

        assert db(scenario())["status"] == "failed"


class TestRetention:
    """Jobs are not the price history — price_checks is. A check is a
    heartbeat, kept for days; a hunt is a story, kept for months."""

    def test_old_checks_go_and_take_their_events_with_them(self):
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(
                pending_job(ids, status="done", finished_at=NOW - timedelta(days=8))
            )
            await seed(
                JobEvents(
                    job_id=job_id,
                    seq=1,
                    ts=NOW - timedelta(days=8),
                    level="info",
                    event_type="job_started",
                    message="…",
                )
            )
            pruned = await job_queue.prune()
            async with AsyncSessionLocal() as session:
                events = await session.scalar(select(func.count()).select_from(JobEvents))
            return pruned, await read_jobs(), events

        pruned, remaining, events = db(scenario())
        assert pruned == 1
        assert remaining == []
        assert events == 0

    def test_a_hunt_outlives_a_check_by_months(self):
        async def scenario():
            ids = await seed_scope_graph()
            await seed(
                pending_job(ids, kind="hunt", status="done", finished_at=NOW - timedelta(days=8)),
                pending_job(ids, status="failed", finished_at=NOW - timedelta(days=8)),
            )
            await job_queue.prune()
            return [r["kind"] for r in await read_jobs()]

        assert db(scenario()) == ["hunt"]

    def test_unfinished_work_is_never_pruned(self):
        async def scenario():
            ids = await seed_scope_graph()
            await seed(pending_job(ids, run_after=NOW - timedelta(days=30)))
            return await job_queue.prune(), await read_jobs()

        pruned, remaining = db(scenario())
        assert pruned == 0
        assert len(remaining) == 1


class TestAppendEvent:
    def test_appends_with_the_next_seq_and_bumps_last_seq(self):
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(pending_job(ids, kind="hunt"))
            first = await job_queue.append_event(job_id, "info", "job_started", "Hunting GameBay…")
            second = await job_queue.append_event(
                job_id, "success", "listing_discovered", "Saved a listing"
            )
            async with AsyncSessionLocal() as session:
                seqs = list(
                    (
                        await session.execute(
                            select(JobEvents.seq)
                            .where(JobEvents.job_id == job_id)
                            .order_by(JobEvents.seq)
                        )
                    )
                    .scalars()
                    .all()
                )
            return first, second, seqs, await read_job(job_id)

        first, second, seqs, row = db(scenario())
        assert (first, second) == (1, 2)
        assert seqs == [1, 2]
        assert row["last_seq"] == 2

    def test_a_missing_job_returns_none(self):
        assert db(job_queue.append_event(9999, "info", "job_started", "…")) is None


class TestQueueHelpers:
    def test_a_saved_listing_is_watched_from_the_moment_it_is_saved(self):
        async def scenario():
            ids = await seed_scope_graph()
            async with AsyncSessionLocal() as session:
                await job_queue.enqueue_recheck(
                    session,
                    listing_id=ids["listing_a"],
                    watch_id=ids["watch_a"],
                    item_id=ids["item_a"],
                    site_id=ids["site_a"],
                )
                await session.commit()
            return await read_jobs(kind="recheck")

        rows = db(scenario())
        assert len(rows) == 1
        assert rows[0]["status"] == "pending"
        assert rows[0]["run_after"] <= datetime.now(UTC)

    def test_bumping_moves_a_pending_check_and_leaves_a_running_one(self):
        # a running check is seconds from writing its own observation; its
        # successor will honour the new cadence anyway
        async def scenario():
            ids = await seed_scope_graph()
            pending_id, running_id = await seed(
                pending_job(ids, run_after=NOW + timedelta(minutes=30)),
                pending_job(
                    ids,
                    listing_id=ids["listing_b"],
                    watch_id=ids["watch_b"],
                    item_id=ids["item_b"],
                    site_id=ids["site_b"],
                    status="running",
                    run_after=NOW + timedelta(minutes=30),
                ),
            )
            async with AsyncSessionLocal() as session:
                await job_queue.bump_rechecks(
                    session, ids["listing_a"], delay_minutes=5, priority=90
                )
                await job_queue.bump_rechecks(
                    session, ids["listing_b"], delay_minutes=5, priority=90
                )
                await session.commit()
            return await read_job(pending_id), await read_job(running_id)

        bumped, running = db(scenario())
        assert bumped["priority"] == 90
        assert bumped["run_after"] < NOW + timedelta(minutes=10)
        assert running["priority"] == 0
        assert running["run_after"] > NOW + timedelta(minutes=20)

    def test_untracking_a_listing_drops_its_pending_check(self):
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(pending_job(ids))
            async with AsyncSessionLocal() as session:
                await job_queue.cancel_recheck(session, ids["listing_a"])
                await session.commit()
            return await read_job(job_id)

        row = db(scenario())
        assert row["status"] == "cancelled"
        assert row["finished_at"] is not None

    def test_grounding_is_queued_once_per_item(self):
        async def scenario():
            ids = await seed_scope_graph()
            first = await job_queue.enqueue_ground(ids["item_a"])
            second = await job_queue.enqueue_ground(ids["item_a"])
            return first, second, await read_jobs(kind="ground")

        first, second, rows = db(scenario())
        assert (first, second) == (True, False)
        assert len(rows) == 1


class TestUnitLookups:
    """What a pool loads once it has claimed a job. A job outlives the
    decision that queued it, so both lookups answer None rather than raising
    when the world moved on — the worker treats that as "nothing to do"."""

    def test_a_recheck_unit_carries_everything_the_ladder_needs(self):
        async def scenario():
            ids = await seed_scope_graph()
            return ids, await get_recheck_unit(ids["listing_a"])

        ids, unit = db(scenario())
        assert unit["listing_id"] == ids["listing_a"]
        assert unit["listing_url"] == "https://gamebay.test/l1"
        assert unit["watch_id"] == ids["watch_a"]
        assert unit["site_base_url"] == "https://gamebay.test"
        assert unit["item_name"] == "Emerald"
        assert (unit["price_locator"], unit["locator_kind"]) == (None, None)
        assert unit["static_ok"] is False

    def test_an_untracked_listing_has_nothing_to_re_read(self):
        async def scenario():
            ids = await seed_scope_graph()
            async with AsyncSessionLocal() as session:
                listing = await session.get(Listings, ids["listing_a"])
                listing.active = False
                await session.commit()
            return await get_recheck_unit(ids["listing_a"])

        assert db(scenario()) is None

    def test_a_missing_listing_has_nothing_to_re_read(self):
        assert db(get_recheck_unit(9999)) is None

    def test_a_hunt_unit_carries_the_watchs_own_settings(self):
        async def scenario():
            ids = await seed_scope_graph()
            return ids, await get_hunt_unit(ids["watch_a"], ids["site_a"])

        ids, unit = db(scenario())
        assert (unit["watch_id"], unit["site_id"]) == (ids["watch_a"], ids["site_a"])
        assert unit["item_name"] == "Emerald"
        assert unit["base_url"] == "https://gamebay.test"
        assert unit["selection_mode"] == "cheapest"
        assert unit["max_listings"] == 3

    def test_a_site_the_watchs_category_does_not_carry_is_not_a_pair(self):
        # CardBay sells cards; the Emerald watch has no business there, even
        # if a stale job says otherwise
        async def scenario():
            ids = await seed_scope_graph()
            return await get_hunt_unit(ids["watch_a"], ids["site_b"])

        assert db(scenario()) is None


async def pairs_by_watch(ids) -> dict[int, list[int]]:
    """{watch_id: sorted site_ids} — every pair get_hunt_unit still accepts.

    Probed one at a time because that is how the hunter asks: a hunt job names
    exactly one pair, and the lookup's whole job is to say whether that pair is
    still one the watch searches."""
    out: dict[int, list[int]] = {}
    for watch_id in (ids["watch_a"], ids["watch_b"]):
        sites = [
            site_id
            for site_id in (ids["site_a"], ids["site_b"])
            if await get_hunt_unit(watch_id, site_id) is not None
        ]
        if sites:
            out[watch_id] = sorted(sites)
    return out


class TestWatchSiteSubset:
    """The API's site_ids: a watch may pin a subset of its category's sites,
    stored as watch_sites rows. CardBay is linked to Games as well here so the
    Games watch has two sites to choose between."""

    async def _games_on_both_sites(self) -> dict:
        ids = await seed_scope_graph()
        await seed(SiteCategories(site_id=ids["site_b"], category_id=ids["cat_a"]))
        return ids

    def test_a_watch_with_no_pins_searches_every_site_in_its_category(self):
        async def scenario():
            ids = await self._games_on_both_sites()
            return ids, await pairs_by_watch(ids)

        ids, pairs = db(scenario())
        assert pairs[ids["watch_a"]] == sorted([ids["site_a"], ids["site_b"]])
        assert pairs[ids["watch_b"]] == [ids["site_b"]]

    def test_a_watch_with_pins_searches_only_those_sites(self):
        async def scenario():
            ids = await self._games_on_both_sites()
            await seed(WatchSites(watch_id=ids["watch_a"], site_id=ids["site_a"]))
            return ids, await pairs_by_watch(ids)

        ids, pairs = db(scenario())
        assert pairs[ids["watch_a"]] == [ids["site_a"]]
        # the other watch is unpinned and unaffected
        assert pairs[ids["watch_b"]] == [ids["site_b"]]

    def test_a_pin_on_a_site_outside_the_category_yields_no_pair(self):
        async def scenario():
            ids = await seed_scope_graph()
            # GameBay does not carry Cards: the pin names a site the watch's
            # category can't be searched on (the API forbids it; a later
            # unlink could still leave the row behind)
            await seed(WatchSites(watch_id=ids["watch_b"], site_id=ids["site_a"]))
            return ids, await pairs_by_watch(ids)

        ids, pairs = db(scenario())
        assert ids["watch_b"] not in pairs
        assert pairs[ids["watch_a"]] == [ids["site_a"]]


class TestNotifyDoesNotGateDiscovery:
    def test_a_watch_with_notifications_off_still_gets_scanned(self):
        # notify is the "tell me" switch, not a pause: the UI labels it
        # "Notify me when the target price is hit", so a muted watch must
        # keep discovering listings and just stay quiet about them
        async def scenario():
            ids = await seed_scope_graph()
            async with AsyncSessionLocal() as session:
                watch = await session.get(Watches, ids["watch_a"])
                watch.notify = False
                await session.commit()
            return ids, await pairs_by_watch(ids)

        ids, pairs = db(scenario())
        assert pairs[ids["watch_a"]] == [ids["site_a"]]


class TestActiveListingCount:
    def test_counts_only_the_watch_s_active_listings_across_sites(self):
        async def scenario():
            ids = await seed_scope_graph()
            await seed(
                # a second site's listing still counts against the same watch
                Listings(
                    watch_id=ids["watch_a"],
                    item_id=ids["item_a"],
                    site_id=ids["site_b"],
                    url="https://cardbay.test/emerald",
                ),
                # a retired listing has freed its slot
                Listings(
                    watch_id=ids["watch_a"],
                    item_id=ids["item_a"],
                    site_id=ids["site_a"],
                    url="https://gamebay.test/sold",
                    active=False,
                ),
            )
            return (
                await get_active_listing_count(ids["watch_a"]),
                await get_active_listing_count(ids["watch_b"]),
                await get_active_listing_count(99999),
            )

        assert db(scenario()) == (2, 1, 0)


def tally(runtime) -> dict[str, int]:
    """The unit's own counters, read back off the runtime the tools were
    handed. The tally lives on the unit, not in a module global, because
    workers run several jobs at once and a job's stats have to be its own."""
    return runtime.config["configurable"]["unit"].stats


class TestUnitTally:
    def test_save_price_check_tallies_checks_and_prices(self):
        async def scenario():
            ids = await seed_scope_graph()
            runtime = unit_a(ids)
            result = await tools.save_price_check(
                ids["listing_a"], True, "ok", 49.99, runtime=runtime
            )
            return result, tally(runtime)

        result, counted = db(scenario())
        assert result.startswith("Successfully")
        assert counted["listings_checked"] == 1
        assert counted["prices_found"] == 1

    def test_an_unpriced_check_tallies_no_price(self):
        async def scenario():
            ids = await seed_scope_graph()
            runtime = unit_a(ids)
            result = await tools.save_price_check(ids["listing_a"], False, "sold", runtime=runtime)
            return result, tally(runtime)

        result, counted = db(scenario())
        assert result.startswith("Successfully")
        assert counted["listings_checked"] == 1
        assert counted["prices_found"] == 0

    def test_save_listing_tallies_only_genuinely_new_rows(self):
        async def scenario():
            ids = await seed_scope_graph()
            runtime = unit_a(ids)
            args = ("https://gamebay.test/new", "title", 80, "fits")
            first = await tools.save_listing(*args, runtime=runtime)
            second = await tools.save_listing(*args, runtime=runtime)
            return first, second, tally(runtime)

        first, second, counted = db(scenario())
        assert isinstance(first, int)
        assert first == second  # the duplicate returns the existing listing_id
        assert counted["new_listings"] == 1

    def test_a_saved_listing_is_queued_for_its_first_check(self):
        # the discovery is watched before the hunt that found it has finished
        async def scenario():
            ids = await seed_scope_graph()
            listing_id = await tools.save_listing(
                "https://gamebay.test/fresh", "title", 80, "fits", runtime=unit_a(ids)
            )
            return listing_id, await read_jobs(kind="recheck")

        listing_id, queued = db(scenario())
        assert isinstance(listing_id, int)
        assert len(queued) == 1
        assert queued[0]["status"] == "pending"

    def test_an_untracked_listing_drops_out_of_the_queue(self):
        async def scenario():
            ids = await seed_scope_graph()
            (job_id,) = await seed(pending_job(ids))
            result = await tools.disable_listing(ids["listing_a"], "sold", runtime=unit_a(ids))
            return result, await read_job(job_id)

        result, row = db(scenario())
        assert result.startswith("Listing")
        assert row["status"] == "cancelled"

    @pytest.mark.parametrize("reason", ["sold", "ended", "auction"])
    def test_a_disabled_listing_records_why(self, reason):
        async def scenario():
            ids = await seed_scope_graph()
            result = await tools.disable_listing(ids["listing_a"], reason, runtime=unit_a(ids))
            async with AsyncSessionLocal() as session:
                listing = await session.get(Listings, ids["listing_a"])
                return result, listing.active, listing.inactive_reason

        result, active, stored = db(scenario())
        assert result.startswith("Listing")
        assert (active, stored) == (False, reason)

    def test_a_listing_a_recheck_saw_end_records_why_too(self):
        # the code path's twin of disable_listing: a deterministic recheck
        # that reads "sold" ends tracking without a model in the loop
        async def scenario():
            ids = await seed_scope_graph()
            await deactivate_listing(ids["listing_a"], "sold")
            async with AsyncSessionLocal() as session:
                listing = await session.get(Listings, ids["listing_a"])
                return listing.active, listing.inactive_reason

        assert db(scenario()) == (False, "sold")


class TestListingOwnership:
    """save_price_check and disable_listing take a listing_id the model typed
    by hand; the bound unit is what makes a typo harmless."""

    def test_a_price_check_on_another_watchs_listing_is_refused(self):
        async def scenario():
            ids = await seed_scope_graph()
            runtime = unit_a(ids)
            result = await tools.save_price_check(
                ids["listing_b"], True, "ok", 49.99, runtime=runtime
            )
            async with AsyncSessionLocal() as session:
                checks = (await session.execute(select(PriceChecks))).scalars().all()
            return result, len(checks), tally(runtime)

        result, checks, counted = db(scenario())
        assert result.startswith("Error:")
        assert checks == 0
        assert counted["listings_checked"] == 0

    def test_a_recheck_writes_only_to_the_listing_it_is_about(self):
        async def scenario():
            ids = await seed_scope_graph()
            (other_id,) = await seed(
                Listings(
                    watch_id=ids["watch_a"],
                    item_id=ids["item_a"],
                    site_id=ids["site_a"],
                    url="https://gamebay.test/other",
                )
            )
            runtime = unit_a(ids, listing_id=ids["listing_a"])
            refused = await tools.save_price_check(other_id, True, "ok", 10, runtime=runtime)
            accepted = await tools.save_price_check(
                ids["listing_a"], True, "ok", 10, runtime=runtime
            )
            return refused, accepted

        refused, accepted = db(scenario())
        assert refused.startswith("Error:")
        assert "listing_id=" in refused
        assert accepted.startswith("Successfully")

    def test_disabling_another_watchs_listing_is_refused(self):
        async def scenario():
            ids = await seed_scope_graph()
            result = await tools.disable_listing(ids["listing_b"], "sold", runtime=unit_a(ids))
            async with AsyncSessionLocal() as session:
                return result, await session.scalar(
                    select(Listings.active).where(Listings.id == ids["listing_b"])
                )

        result, active = db(scenario())
        assert result.startswith("Error:")
        assert active is True


class TestInactiveListingSave:
    def test_a_known_inactive_listing_is_skipped_not_resurrected(self):
        url = "https://gamebay.test/sold"

        async def scenario():
            ids = await seed_scope_graph()
            await seed(
                Listings(
                    watch_id=ids["watch_a"],
                    item_id=ids["item_a"],
                    site_id=ids["site_a"],
                    url=url,
                    active=False,
                )
            )
            runtime = unit_a(ids)
            result = await tools.save_listing(url, "title", 80, "fits", runtime=runtime)
            async with AsyncSessionLocal() as session:
                active = await session.scalar(select(Listings.active).where(Listings.url == url))
                outbox = (await session.execute(select(NotificationOutbox))).scalars().all()
            return result, active, len(outbox), tally(runtime)

        result, active, outbox, counted = db(scenario())
        assert result.startswith("SKIPPED:")
        assert active is False
        assert outbox == 0
        assert counted["new_listings"] == 0


class TestKnownListingUrls:
    def test_returns_the_pairs_urls_active_or_not(self):
        async def scenario():
            ids = await seed_scope_graph()
            await seed(
                Listings(
                    watch_id=ids["watch_a"],
                    item_id=ids["item_a"],
                    site_id=ids["site_a"],
                    url="https://gamebay.test/sold",
                    active=False,
                ),
                # same watch, other site: not this pair's
                Listings(
                    watch_id=ids["watch_a"],
                    item_id=ids["item_a"],
                    site_id=ids["site_b"],
                    url="https://cardbay.test/emerald",
                ),
            )
            return (
                list(await get_known_listing_urls(ids["watch_a"], ids["site_a"])),
                list(await get_known_listing_urls(ids["watch_b"], ids["site_a"])),
            )

        pair_a, none = db(scenario())
        assert pair_a == ["https://gamebay.test/l1", "https://gamebay.test/sold"]
        assert none == []


class TestCheckedAtIsUtc:
    """Both checked_at columns are timestamptz and the house rule is that every
    DB datetime is timezone-aware UTC.

    Asserted at the clock, not on the row, because the row can't tell: asyncpg
    reads a naive stamp as local time and converts it, and datetime.now() sets
    `fold`, so today a naive write lands on the very same instant an aware one
    would — DST changeovers included. That equivalence is the driver's
    convention, not ours; psycopg (what vision/ uses) and a plain `timestamp`
    column both read a naive value as already-UTC and would shift it by the
    host's offset. Pin the rule where it's visible.
    """

    def test_save_price_check_asks_for_utc(self):
        clock = RecordingClock()

        async def scenario():
            ids = await seed_scope_graph()
            with clock.installed():
                await tools.save_price_check(
                    ids["listing_a"], True, "ok", 49.99, runtime=unit_a(ids)
                )
            async with AsyncSessionLocal() as session:
                return await session.scalar(select(PriceChecks.checked_at))

        stored = db(scenario())
        assert clock.zones == [UTC]
        assert abs(stored - datetime.now(UTC)) < timedelta(minutes=1)

    def test_log_listing_check_asks_for_utc(self):
        clock = RecordingClock()

        async def scenario():
            ids = await seed_scope_graph()
            with clock.installed():
                await tools.log_listing_check(
                    "https://gamebay.test/nope", "poor_fit", runtime=unit_a(ids)
                )
            async with AsyncSessionLocal() as session:
                return await session.scalar(select(ListingChecks.checked_at))

        stored = db(scenario())
        assert clock.zones == [UTC]
        assert abs(stored - datetime.now(UTC)) < timedelta(minutes=1)


class TestLocatorLifecycle:
    """listings' locator columns are a small state machine: learned and
    verified, counted down as it misses, cleared so the next LLM read can
    learn a fresh one. Getting the clearing wrong is what would leave a site
    burning a browser load per recheck on a selector that will never match
    again."""

    async def _listing(self, ids):
        async with AsyncSessionLocal() as session:
            return await session.get(Listings, ids["listing_a"])

    def test_a_learned_locator_is_stored_verified_and_counted_from_zero(self):
        async def scenario():
            ids = await seed_scope_graph()
            await note_locator_failure(ids["listing_a"], 3)
            await save_locator(ids["listing_a"], "jsonld", "offers.price", static_ok=True)
            return await self._listing(ids)

        listing = db(scenario())
        assert (listing.locator_kind, listing.price_locator) == ("jsonld", "offers.price")
        assert listing.locator_verified_at is not None
        assert (listing.locator_failures, listing.static_ok) == (0, True)

    def test_misses_accumulate_until_the_locator_is_dropped(self):
        async def scenario():
            ids = await seed_scope_graph()
            await save_locator(ids["listing_a"], "css", "span.price", static_ok=False)
            cleared = [await note_locator_failure(ids["listing_a"], 3) for _ in range(3)]
            return cleared, await self._listing(ids)

        cleared, listing = db(scenario())
        assert cleared == [False, False, True]
        assert (listing.price_locator, listing.locator_kind) == (None, None)
        assert (listing.locator_verified_at, listing.locator_failures) == (None, 0)

    def test_clearing_a_locator_also_sends_the_listing_back_to_the_browser(self):
        # static_ok describes a locator that no longer exists
        async def scenario():
            ids = await seed_scope_graph()
            await save_locator(ids["listing_a"], "jsonld", "offers.price", static_ok=True)
            await note_locator_failure(ids["listing_a"], 1)
            return await self._listing(ids)

        assert db(scenario()).static_ok is False

    def test_clear_static_ok_leaves_the_locator_alone(self):
        # the locator still works in the browser; only the GET was pointless
        async def scenario():
            ids = await seed_scope_graph()
            await save_locator(ids["listing_a"], "jsonld", "offers.price", static_ok=True)
            await clear_static_ok(ids["listing_a"])
            return await self._listing(ids)

        listing = db(scenario())
        assert (listing.static_ok, listing.price_locator) == (False, "offers.price")

    def test_has_verified_locator_answers_for_the_post_unit_learn(self):
        async def scenario():
            ids = await seed_scope_graph()
            before = await has_verified_locator(ids["listing_a"])
            await save_locator(ids["listing_a"], "meta", "product:price:amount")
            return before, await has_verified_locator(ids["listing_a"])

        assert db(scenario()) == (False, True)

    def test_a_relearn_replaces_the_previous_locator(self):
        async def scenario():
            ids = await seed_scope_graph()
            await save_locator(ids["listing_a"], "css", "span.old", static_ok=True)
            await save_locator(ids["listing_a"], "jsonld", "offers.price", static_ok=False)
            return await self._listing(ids)

        listing = db(scenario())
        assert (listing.locator_kind, listing.price_locator) == ("jsonld", "offers.price")
        assert listing.static_ok is False


class TestSiteConsensus:
    """One marketplace serves one page template, so the locator most of a
    site's listings agree on is the best guess for one that has never been
    learned — and one relearn after a redesign fixes the whole site."""

    async def _agree(self, ids, *locators):
        """Give watch A's listing and some siblings on the same site a locator
        each, then answer what the site agrees on."""
        async with AsyncSessionLocal() as session:
            for index, (kind, locator) in enumerate(locators):
                listing = Listings(
                    watch_id=ids["watch_a"],
                    item_id=ids["item_a"],
                    site_id=ids["site_a"],
                    url=f"https://gamebay.test/sibling{index}",
                    price_locator=locator,
                    locator_kind=kind,
                    locator_verified_at=datetime.now(UTC),
                )
                session.add(listing)
            await session.commit()
        async with AsyncSessionLocal() as session:
            return await site_consensus(session, ids["site_a"])

    def test_the_most_common_verified_locator_wins(self):
        async def scenario():
            ids = await seed_scope_graph()
            return await self._agree(
                ids,
                ("jsonld", "offers.price"),
                ("jsonld", "offers.price"),
                ("css", "span.price"),
            )

        assert db(scenario()) == Locator("jsonld", "offers.price")

    def test_a_site_with_nothing_learned_yet_agrees_on_nothing(self):
        async def scenario():
            ids = await seed_scope_graph()
            async with AsyncSessionLocal() as session:
                return await site_consensus(session, ids["site_a"])

        assert db(scenario()) is None

    def test_an_unverified_locator_does_not_vote(self):
        async def scenario():
            ids = await seed_scope_graph()
            async with AsyncSessionLocal() as session:
                listing = await session.get(Listings, ids["listing_a"])
                listing.locator_kind, listing.price_locator = "css", "span.unverified"
                await session.commit()
            async with AsyncSessionLocal() as session:
                return await site_consensus(session, ids["site_a"])

        assert db(scenario()) is None

    def test_another_sites_locators_do_not_vote(self):
        async def scenario():
            ids = await seed_scope_graph()
            async with AsyncSessionLocal() as session:
                listing = await session.get(Listings, ids["listing_b"])
                listing.locator_kind = "css"
                listing.price_locator = "span.cardbay"
                listing.locator_verified_at = datetime.now(UTC)
                await session.commit()
            async with AsyncSessionLocal() as session:
                return await site_consensus(session, ids["site_a"])

        assert db(scenario()) is None
