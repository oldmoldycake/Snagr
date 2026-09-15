"""The run-queue DB helpers against a real Postgres: the claim's FOR UPDATE
SKIP LOCKED, the locked last_seq bump behind uq_run_seq, terminal writes, the
schedule-firing claim, the scope-filtered planning queries, and the tools
tally — SQL that the seam tests in test_run_consumer.py can't exercise.

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

import pytest
import tools
from conftest import unit_runtime
from database import (
    AgentRuns,
    AsyncSessionLocal,
    Base,
    Categories,
    Items,
    ListingChecks,
    Listings,
    NotificationOutbox,
    PriceChecks,
    RunEvents,
    RunSchedules,
    SiteCategories,
    Sites,
    User,
    Watches,
    WatchSites,
    append_run_event,
    beat_run,
    claim_due_schedule,
    claim_queued_run,
    create_global_run,
    engine,
    finish_run,
    get_active_listing_count,
    get_known_listing_urls,
    get_listed_items,
    get_watched_item_list,
    reap_stale_runs,
)
from sqlalchemy import select, text

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
    """The runtime a tool call gets inside one of watch A's units on GameBay."""
    return unit_runtime(
        watch_id=ids["watch_a"], item_id=ids["item_a"], site_id=ids["site_a"], **overrides
    )


def queued_run(days_ago=0.0, **overrides):
    """A queued run `days_ago` days back; override any column."""
    fields = {
        "scope": "global",
        "scope_id": None,
        "scope_label": "Everything",
        "status": "queued",
        "created_at": NOW - timedelta(days=days_ago),
        **overrides,
    }
    return AgentRuns(**fields)


async def seed(*rows) -> list[int]:
    """Insert any model rows; returns their ids (captured before commit expires
    them; None for composite-key rows like watch_sites)."""
    async with AsyncSessionLocal() as session:
        session.add_all(rows)
        await session.flush()
        ids = [getattr(row, "id", None) for row in rows]
        await session.commit()
    return ids


async def read_run(run_id: int) -> dict:
    async with AsyncSessionLocal() as session:
        run = await session.get(AgentRuns, run_id)
        return {
            "user_id": run.user_id,
            "scope": run.scope,
            "scope_id": run.scope_id,
            "scope_label": run.scope_label,
            "status": run.status,
            "started_at": run.started_at,
            "heartbeat_at": run.heartbeat_at,
            "finished_at": run.finished_at,
            "stats": run.stats,
            "error": run.error,
            "last_seq": run.last_seq,
        }


def due_schedule(minutes_overdue=5.0, **overrides):
    """A recurring hourly schedule due `minutes_overdue` ago; override any column."""
    fields = {
        "scope": "global",
        "scope_id": None,
        "scope_label": "Everything",
        "next_due_at": NOW - timedelta(minutes=minutes_overdue),
        "interval_minutes": 60,
        "enabled": True,
        **overrides,
    }
    return RunSchedules(**fields)


async def read_schedule(schedule_id: int) -> dict:
    async with AsyncSessionLocal() as session:
        row = await session.get(RunSchedules, schedule_id)
        return {
            "next_due_at": row.next_due_at,
            "interval_minutes": row.interval_minutes,
            "enabled": row.enabled,
            "last_fired_at": row.last_fired_at,
        }


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
        """Swap this in for `tools.datetime` for the duration of the body."""
        real = tools.datetime
        tools.datetime = self
        try:
            yield
        finally:
            tools.datetime = real


async def read_events(run_id: int) -> list[dict]:
    async with AsyncSessionLocal() as session:
        stmt = select(RunEvents).where(RunEvents.run_id == run_id).order_by(RunEvents.seq)
        rows = (await session.execute(stmt)).scalars().all()
        return [
            {"seq": e.seq, "level": e.level, "event_type": e.event_type, "message": e.message}
            for e in rows
        ]


async def api_cancel_bump(run_id: int) -> None:
    """Bump last_seq + append an event the way the backend's cancel_run does."""
    async with AsyncSessionLocal() as session:
        run = await session.get(AgentRuns, run_id, with_for_update=True)
        run.last_seq += 1
        session.add(
            RunEvents(
                run_id=run_id,
                seq=run.last_seq,
                ts=datetime.now(UTC),
                level="warn",
                event_type="run_finished",
                message="Run cancelled",
                payload=None,
            )
        )
        await session.commit()


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


class TestClaimQueuedRun:
    def test_an_empty_queue_returns_none(self):
        assert db(claim_queued_run()) is None

    def test_claims_oldest_first_and_flips_it_to_running(self):
        async def scenario():
            older_id, _ = await seed(
                queued_run(2, scope_label="older"), queued_run(1, scope_label="newer")
            )
            claimed = await claim_queued_run()
            return older_id, claimed, await read_run(claimed["id"])

        older_id, claimed, row = db(scenario())
        assert claimed["id"] == older_id
        assert set(claimed) == {"id", "scope", "scope_id", "scope_label"}
        assert claimed["scope_label"] == "older"
        assert row["status"] == "running"
        assert row["started_at"] is not None

    def test_concurrent_claims_have_exactly_one_winner(self):
        # SKIP LOCKED: the loser sees no unlocked queued row and gets None
        async def scenario():
            await seed(queued_run())
            return await asyncio.gather(claim_queued_run(), claim_queued_run())

        results = db(scenario())
        assert sorted(r is None for r in results) == [False, True]

    def test_only_queued_runs_are_claimable(self):
        async def scenario():
            await seed(
                queued_run(status="running", started_at=NOW),
                queued_run(status="succeeded"),
                queued_run(status="cancelled"),
            )
            return await claim_queued_run()

        assert db(scenario()) is None


class TestAppendRunEvent:
    def test_appends_with_the_next_seq_and_bumps_last_seq(self):
        async def scenario():
            (run_id,) = await seed(queued_run(status="running", last_seq=3))
            seq = await append_run_event(run_id, "info", "item_started", "searching")
            return seq, await read_run(run_id), await read_events(run_id)

        seq, row, events = db(scenario())
        assert seq == 4
        assert row["last_seq"] == 4
        assert [e["seq"] for e in events] == [4]

    def test_continues_after_an_api_side_bump(self):
        # the API's cancel bumps last_seq under the same row lock — the next
        # append must slot in after it, never violate uq_run_seq
        async def scenario():
            (run_id,) = await seed(queued_run(status="running"))
            first = await append_run_event(run_id, "info", "run_started", "Run started")
            await api_cancel_bump(run_id)
            second = await append_run_event(run_id, "error", "error", "late failure")
            return first, second, await read_events(run_id)

        first, second, events = db(scenario())
        assert (first, second) == (1, 3)
        assert [e["seq"] for e in events] == [1, 2, 3]

    def test_a_missing_run_returns_none(self):
        assert db(append_run_event(99999, "info", "item_started", "searching")) is None


class TestFinishRun:
    def test_success_writes_stats_and_a_success_terminal_event(self):
        stats = {"listings_checked": 2, "prices_found": 1, "new_listings": 1, "errors": 0}

        async def scenario():
            (run_id,) = await seed(queued_run(status="running", started_at=NOW))
            ok = await finish_run(run_id, "succeeded", stats=stats)
            return ok, await read_run(run_id), await read_events(run_id)

        ok, row, events = db(scenario())
        assert ok is True
        assert row["status"] == "succeeded"
        assert row["finished_at"] is not None
        assert row["stats"] == stats
        assert row["last_seq"] == 1
        (event,) = events
        assert event["level"] == "success"
        assert event["event_type"] == "run_finished"
        assert event["message"] == "Run complete — 2 checked, 1 prices, 1 new listings, 0 errors"

    def test_failure_writes_error_and_an_error_terminal_event(self):
        async def scenario():
            (run_id,) = await seed(queued_run(status="running", started_at=NOW))
            ok = await finish_run(run_id, "failed", error="browser crashed")
            return ok, await read_run(run_id), await read_events(run_id)

        ok, row, events = db(scenario())
        assert ok is True
        assert row["status"] == "failed"
        assert row["error"] == "browser crashed"
        assert row["stats"] is None
        (event,) = events
        assert event["level"] == "error"
        assert event["event_type"] == "run_finished"
        assert event["message"] == "Run failed: browser crashed"

    def test_never_clobbers_a_cancelled_run(self):
        # the API cancelled while the agent was finishing — its terminal
        # state and event must survive untouched
        async def scenario():
            (run_id,) = await seed(queued_run(status="cancelled", last_seq=1, finished_at=NOW))
            ok = await finish_run(run_id, "succeeded", stats={})
            return ok, await read_run(run_id), await read_events(run_id)

        ok, row, events = db(scenario())
        assert ok is False
        assert row["status"] == "cancelled"
        assert row["last_seq"] == 1
        assert events == []


class TestCreateGlobalRun:
    def test_inserts_a_running_global_row(self):
        async def scenario():
            created = await create_global_run()
            return created, await read_run(created["id"])

        created, row = db(scenario())
        assert created["scope"] == "global"
        assert created["scope_id"] is None
        assert created["scope_label"] == "Everything"
        assert row["user_id"] is None  # the nightly sweep is a system run
        assert row["status"] == "running"
        assert row["started_at"] is not None


class TestClaimDueSchedule:
    def test_an_empty_table_returns_none(self):
        assert db(claim_due_schedule()) is None

    def test_a_not_yet_due_schedule_is_ignored(self):
        async def scenario():
            (sid,) = await seed(due_schedule(minutes_overdue=-10))
            return await claim_due_schedule(), await read_schedule(sid)

        claimed, row = db(scenario())
        assert claimed is None
        assert row["enabled"] is True
        assert row["last_fired_at"] is None

    def test_a_disabled_schedule_never_fires(self):
        async def scenario():
            (sid,) = await seed(due_schedule(enabled=False))
            return await claim_due_schedule(), await read_schedule(sid)

        claimed, row = db(scenario())
        assert claimed is None
        assert row["last_fired_at"] is None

    def test_fires_the_most_overdue_schedule_first(self):
        async def scenario():
            _, newer_id = await seed(
                due_schedule(minutes_overdue=60, scope_label="older"),
                due_schedule(minutes_overdue=5, scope_label="newer"),
            )
            return await claim_due_schedule(), await read_schedule(newer_id)

        claimed, newer = db(scenario())
        assert claimed["scope_label"] == "older"
        assert newer["last_fired_at"] is None  # still due, untouched

    def test_firing_creates_a_running_run_with_the_schedules_scope(self):
        async def scenario():
            await seed(due_schedule(scope="category", scope_id=4, scope_label="Category: Games"))
            claimed = await claim_due_schedule()
            return claimed, await read_run(claimed["id"])

        claimed, run = db(scenario())
        assert set(claimed) == {"id", "scope", "scope_id", "scope_label", "scheduled"}
        assert claimed["scheduled"] is True
        assert run["scope"] == "category"
        assert run["scope_id"] == 4
        assert run["scope_label"] == "Category: Games"
        assert run["status"] == "running"
        assert run["started_at"] is not None

    def test_firing_copies_the_schedules_owner_onto_the_run(self):
        async def scenario():
            (uid,) = await seed(User(email="owner@test.local"))
            await seed(due_schedule(user_id=uid))
            claimed = await claim_due_schedule()
            return uid, await read_run(claimed["id"])

        uid, run = db(scenario())
        assert run["user_id"] == uid

    def test_a_system_schedule_fires_a_system_run(self):
        async def scenario():
            await seed(due_schedule())  # user_id stays NULL
            claimed = await claim_due_schedule()
            return await read_run(claimed["id"])

        run = db(scenario())
        assert run["user_id"] is None

    def test_a_recurring_fire_rolls_forward_anchored_past_downtime(self):
        async def scenario():
            (sid,) = await seed(due_schedule(minutes_overdue=3 * 1440 + 7, interval_minutes=1440))
            old_due = (await read_schedule(sid))["next_due_at"]
            claimed = await claim_due_schedule()
            second = await claim_due_schedule()
            return claimed, second, old_due, await read_schedule(sid)

        claimed, second, old_due, row = db(scenario())
        assert claimed is not None
        # busy with the fired run, and rolled into the future anyway
        assert second is None
        interval = timedelta(minutes=1440)
        # anchor preserved: the new due time is a whole number of periods on
        assert (row["next_due_at"] - old_due) % interval == timedelta(0)
        # caught up in ONE step: strictly future, at most one period out
        assert row["last_fired_at"] < row["next_due_at"] <= row["last_fired_at"] + interval
        assert row["enabled"] is True

    def test_a_one_shot_fires_once_then_deactivates(self):
        async def scenario():
            (sid,) = await seed(due_schedule(interval_minutes=None))
            old_due = (await read_schedule(sid))["next_due_at"]
            claimed = await claim_due_schedule()
            second = await claim_due_schedule()
            return claimed, second, old_due, await read_schedule(sid)

        claimed, second, old_due, row = db(scenario())
        assert claimed is not None
        assert second is None
        assert row["enabled"] is False
        assert row["last_fired_at"] is not None
        assert row["next_due_at"] == old_due  # one-shots keep their aim time

    @pytest.mark.parametrize("status", ["queued", "running"])
    def test_a_busy_instance_skips_without_rolling(self, status):
        async def scenario():
            overrides = {"status": status, "started_at": NOW if status == "running" else None}
            _, sid = await seed(queued_run(**overrides), due_schedule())
            return await claim_due_schedule(), await read_schedule(sid)

        claimed, row = db(scenario())
        assert claimed is None
        # fully untouched — still due, so it fires on the next free tick
        assert row["enabled"] is True
        assert row["last_fired_at"] is None
        assert row["next_due_at"] == NOW - timedelta(minutes=5)

    def test_concurrent_fires_have_exactly_one_winner(self):
        # SKIP LOCKED: the loser skips the locked row and finds nothing due
        async def scenario():
            await seed(due_schedule())
            results = await asyncio.gather(claim_due_schedule(), claim_due_schedule())
            async with AsyncSessionLocal() as session:
                run_ids = (await session.execute(select(AgentRuns.id))).all()
            return results, len(run_ids)

        results, run_count = db(scenario())
        assert sorted(r is None for r in results) == [False, True]
        assert run_count == 1


class TestHeartbeat:
    def test_a_claim_and_a_sweep_stamp_the_first_beat(self):
        async def scenario():
            await seed(queued_run())
            claimed = await claim_queued_run()
            created = await create_global_run()
            return await read_run(claimed["id"]), await read_run(created["id"])

        for row in db(scenario()):
            assert row["heartbeat_at"] is not None
            assert row["heartbeat_at"] == row["started_at"]

    def test_a_fired_schedule_stamps_the_first_beat(self):
        async def scenario():
            await seed(due_schedule())
            fired = await claim_due_schedule()
            return await read_run(fired["id"])

        row = db(scenario())
        assert row["heartbeat_at"] == row["started_at"]

    def test_beat_run_advances_a_running_runs_heartbeat(self):
        async def scenario():
            (run_id,) = await seed(
                queued_run(
                    status="running",
                    started_at=NOW - timedelta(hours=1),
                    heartbeat_at=NOW - timedelta(minutes=10),
                )
            )
            ok = await beat_run(run_id)
            return ok, await read_run(run_id)

        ok, row = db(scenario())
        assert ok is True
        assert row["heartbeat_at"] > NOW - timedelta(minutes=1)

    def test_beat_run_leaves_a_finished_run_alone(self):
        old_beat = NOW - timedelta(minutes=10)

        async def scenario():
            (run_id,) = await seed(
                queued_run(status="succeeded", started_at=NOW, heartbeat_at=old_beat)
            )
            await beat_run(run_id)
            return await read_run(run_id)

        assert db(scenario())["heartbeat_at"] == old_beat


class TestReapStaleRuns:
    STALE = timedelta(minutes=5)

    def test_fails_a_running_run_whose_heartbeat_went_silent(self):
        async def scenario():
            (dead_id,) = await seed(
                queued_run(
                    status="running",
                    started_at=NOW - timedelta(hours=1),
                    heartbeat_at=NOW - timedelta(minutes=6),
                )
            )
            reaped = await reap_stale_runs(self.STALE)
            return reaped, dead_id, await read_run(dead_id), await read_events(dead_id)

        reaped, dead_id, row, events = db(scenario())
        assert reaped == [dead_id]
        assert row["status"] == "failed"
        assert row["finished_at"] is not None
        assert row["error"] == "Agent stopped responding (no heartbeat for over 5 min)"
        assert [(e["level"], e["event_type"]) for e in events] == [("error", "run_finished")]

    def test_leaves_live_queued_and_finished_runs_alone(self):
        async def scenario():
            ids = await seed(
                # alive: a slow run, but beating
                queued_run(
                    status="running",
                    started_at=NOW - timedelta(hours=1),
                    heartbeat_at=NOW - timedelta(seconds=20),
                ),
                queued_run(),
                queued_run(
                    status="succeeded",
                    started_at=NOW - timedelta(hours=1),
                    heartbeat_at=NOW - timedelta(hours=1),
                ),
                queued_run(status="cancelled", started_at=NOW - timedelta(hours=1)),
            )
            reaped = await reap_stale_runs(self.STALE)
            return reaped, [(await read_run(run_id))["status"] for run_id in ids]

        reaped, statuses = db(scenario())
        assert reaped == []
        assert statuses == ["running", "queued", "succeeded", "cancelled"]

    def test_a_row_from_before_the_column_existed_is_judged_on_started_at(self):
        async def scenario():
            old_id, fresh_id = await seed(
                queued_run(status="running", started_at=NOW - timedelta(minutes=6)),
                queued_run(status="running", started_at=NOW - timedelta(minutes=1)),
            )
            reaped = await reap_stale_runs(self.STALE)
            return reaped, old_id, (await read_run(fresh_id))["status"]

        reaped, old_id, fresh_status = db(scenario())
        assert reaped == [old_id]
        assert fresh_status == "running"


class TestScopedQueries:
    def test_get_listed_items_honors_each_scope(self):
        async def scenario():
            ids = await seed_scope_graph()
            return ids, {
                "global": [r["listing_id"] for r in await get_listed_items()],
                "category": [
                    r["listing_id"] for r in await get_listed_items("category", ids["cat_a"])
                ],
                "site": [r["listing_id"] for r in await get_listed_items("site", ids["site_b"])],
                "item": [r["listing_id"] for r in await get_listed_items("item", ids["item_b"])],
            }

        ids, out = db(scenario())
        assert sorted(out["global"]) == sorted([ids["listing_a"], ids["listing_b"]])
        assert out["category"] == [ids["listing_a"]]
        assert out["site"] == [ids["listing_b"]]
        assert out["item"] == [ids["listing_b"]]

    def test_get_watched_item_list_honors_each_scope(self):
        async def scenario():
            ids = await seed_scope_graph()
            return ids, {
                "global": [r["watch_id"] for r in await get_watched_item_list()],
                "category": [
                    r["watch_id"] for r in await get_watched_item_list("category", ids["cat_a"])
                ],
                "site": [r["watch_id"] for r in await get_watched_item_list("site", ids["site_b"])],
                "item": [r["watch_id"] for r in await get_watched_item_list("item", ids["item_a"])],
            }

        ids, out = db(scenario())
        assert sorted(out["global"]) == sorted([ids["watch_a"], ids["watch_b"]])
        assert out["category"] == [ids["watch_a"]]
        assert out["site"] == [ids["watch_b"]]
        assert out["item"] == [ids["watch_a"]]


def pairs_by_watch(rows) -> dict[int, list[int]]:
    """{watch_id: sorted site_ids} from get_watched_item_list rows."""
    out: dict[int, list[int]] = {}
    for row in rows:
        out.setdefault(row["watch_id"], []).append(row["site_id"])
    return {watch_id: sorted(site_ids) for watch_id, site_ids in out.items()}


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
            return ids, pairs_by_watch(await get_watched_item_list())

        ids, pairs = db(scenario())
        assert pairs[ids["watch_a"]] == sorted([ids["site_a"], ids["site_b"]])
        assert pairs[ids["watch_b"]] == [ids["site_b"]]

    def test_a_watch_with_pins_searches_only_those_sites(self):
        async def scenario():
            ids = await self._games_on_both_sites()
            await seed(WatchSites(watch_id=ids["watch_a"], site_id=ids["site_a"]))
            return ids, pairs_by_watch(await get_watched_item_list())

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
            return ids, pairs_by_watch(await get_watched_item_list())

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
            return ids, pairs_by_watch(await get_watched_item_list())

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


class TestRunStatsTally:
    def test_save_price_check_tallies_checks_and_prices(self):
        tools.reset_run_stats()

        async def scenario():
            ids = await seed_scope_graph()
            return await tools.save_price_check(
                ids["listing_a"], True, "ok", 49.99, runtime=unit_a(ids)
            )

        assert db(scenario()).startswith("Successfully")
        assert tools.run_stats["listings_checked"] == 1
        assert tools.run_stats["prices_found"] == 1

    def test_an_unpriced_check_tallies_no_price(self):
        tools.reset_run_stats()

        async def scenario():
            ids = await seed_scope_graph()
            return await tools.save_price_check(
                ids["listing_a"], False, "sold", runtime=unit_a(ids)
            )

        assert db(scenario()).startswith("Successfully")
        assert tools.run_stats["listings_checked"] == 1
        assert tools.run_stats["prices_found"] == 0

    def test_save_listing_tallies_only_genuinely_new_rows(self):
        tools.reset_run_stats()

        async def scenario():
            ids = await seed_scope_graph()
            args = ("https://gamebay.test/new", "title", 80, "fits")
            first = await tools.save_listing(*args, runtime=unit_a(ids))
            second = await tools.save_listing(*args, runtime=unit_a(ids))
            return first, second

        first, second = db(scenario())
        assert isinstance(first, int)
        assert first == second  # the duplicate returns the existing listing_id
        assert tools.run_stats["new_listings"] == 1


class TestListingOwnership:
    """save_price_check and disable_listing take a listing_id the model typed
    by hand; the bound unit is what makes a typo harmless."""

    def test_a_price_check_on_another_watchs_listing_is_refused(self):
        tools.reset_run_stats()

        async def scenario():
            ids = await seed_scope_graph()
            result = await tools.save_price_check(
                ids["listing_b"], True, "ok", 49.99, runtime=unit_a(ids)
            )
            async with AsyncSessionLocal() as session:
                checks = (await session.execute(select(PriceChecks))).scalars().all()
            return result, len(checks)

        result, checks = db(scenario())
        assert result.startswith("Error:")
        assert checks == 0
        assert tools.run_stats["listings_checked"] == 0

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
        tools.reset_run_stats()
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
            result = await tools.save_listing(url, "title", 80, "fits", runtime=unit_a(ids))
            async with AsyncSessionLocal() as session:
                active = await session.scalar(select(Listings.active).where(Listings.url == url))
                outbox = (await session.execute(select(NotificationOutbox))).scalars().all()
            return result, active, len(outbox)

        result, active, outbox = db(scenario())
        assert result.startswith("SKIPPED:")
        assert active is False
        assert outbox == 0
        assert tools.run_stats["new_listings"] == 0


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
