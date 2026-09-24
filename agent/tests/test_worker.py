"""The daemon's orchestration with every seam monkeypatched: the queue, the
DB lookups, the MCP session, the model, and the two per-unit workers. What's
under test is the lifecycle — claim, drain, terminal writes, the heartbeat,
cancellation, shutdown, housekeeping — not SQL (that's test_jobs_db.py) and
not the LLM.

No pytest-asyncio here (it isn't a dependency): each test drives its
coroutine with asyncio.run, like the rest of this suite.
"""

import asyncio
from contextlib import asynccontextmanager, contextmanager

import pytest
import worker
from langchain_core.messages import AIMessage, ToolMessage
from observations import Swap, UnitContext

import agent


def recheck_row(listing_id=1, site_id=1):
    """A get_recheck_unit row with only the keys the worker itself reads."""
    return {
        "listing_id": listing_id,
        "listing_url": f"https://example.test/l{listing_id}",
        "site_id": site_id,
        "site_base_url": "https://example.test",
        "watch_id": 1,
        "user_id": 1,
        "item_id": 1,
        "item_name": "Item 1",
        "site_name": "TestBay",
        "condition_hint": None,
    }


def hunt_row(site_id=1, max_listings=3):
    """A get_hunt_unit row with only the keys the worker itself reads."""
    return {
        "watch_id": 1,
        "user_id": 1,
        "item_id": 1,
        "item_name": "Item 1",
        "site_id": site_id,
        "site_name": "TestBay",
        "base_url": "https://example.test",
        "criteria": None,
        "expected_price": None,
        "condition_hint": None,
        "selection_mode": "cheapest",
        "max_listings": max_listings,
        "allow_reproductions": False,
    }


def job(kind="recheck", job_id=1, **overrides):
    return {
        "id": job_id,
        "kind": kind,
        "user_id": None,
        "watch_id": 1,
        "site_id": 1,
        "listing_id": 1 if kind == "recheck" else None,
        "item_id": 1,
        "priority": 0,
        "attempts": 1,
        "reason": None,
        "payload": None,
        **overrides,
    }


class FakeOutcome:
    """What recheck_deterministic answers with."""

    def __init__(self, handled, method="jsonld", transport="static"):
        self.handled = handled
        self.method = method if handled else None
        self.transport = transport
        self.note = None


def wire(monkeypatch, **overrides):
    """Replace every seam the worker reaches through and record what it did.

    Returns the recorder: `seen` lists what the queue was told, keyed by the
    call, so a test asserts on the job's lifecycle rather than on the mocks.
    """
    seen = {
        "claimed": [],
        "completed": [],
        "failed": [],
        "events": [],
        "beats": [],
        "released": [],
        "outcomes": [],
        "grounded": [],
        "reaped": 0,
        "pruned": 0,
        "swept": 0,
        "recheck_units": [],
        "hunt_units": [],
    }

    async def claim(worker_id, kinds):
        seen["claimed"].append((worker_id, tuple(kinds)))
        queue = overrides.get("queue", [])
        return queue.pop(0) if queue else None

    async def complete(job_id, stats=None):
        seen["completed"].append((job_id, stats))
        return True

    async def fail_or_retry(job_id, error):
        seen["failed"].append((job_id, error))
        return "pending"

    async def append_event(job_id, level, event_type, message, payload=None):
        seen["events"].append((job_id, level, event_type, message))
        return 1

    async def heartbeat(job_id):
        seen["beats"].append(job_id)
        return True

    async def release_all(workers):
        seen["released"].append(list(workers))
        return 0

    async def reap():
        seen["reaped"] += 1
        return []

    async def prune():
        seen["pruned"] += 1
        return 0

    async def sweep():
        seen["swept"] += 1
        return 0

    async def enqueue_ground(item_id):
        seen["grounded"].append(item_id)
        return True

    async def record_outcome(site_id, ok, **kwargs):
        seen["outcomes"].append((site_id, ok))
        return None

    for name, fake in (
        ("claim", claim),
        ("complete", complete),
        ("fail_or_retry", fail_or_retry),
        ("append_event", append_event),
        ("heartbeat", heartbeat),
        ("release_all", release_all),
        ("reap", reap),
        ("prune", prune),
        ("sweep", sweep),
        ("enqueue_ground", enqueue_ground),
    ):
        monkeypatch.setattr(worker.job_queue, name, overrides.get(name, fake))
    monkeypatch.setattr(worker.breaker, "record_outcome", record_outcome)

    @asynccontextmanager
    async def open_session():
        yield ["browser_navigate"], "browser"

    async def recheck_unit(listing_id):
        seen["recheck_units"].append(listing_id)
        return overrides.get("recheck_row", recheck_row())

    async def hunt_unit(watch_id, site_id):
        seen["hunt_units"].append((watch_id, site_id))
        return overrides.get("hunt_row", hunt_row())

    async def ground_unit(item_id):
        return {
            "item_id": item_id,
            "item_name": "Item 1",
            "category_id": 1,
            "category_slug": "video-games",
        }

    async def deterministic(browser, row):
        return overrides.get("ladder", FakeOutcome(True))

    async def llm_recheck(agent_, row, browser, job_id=None):
        seen.setdefault("llm_rechecks", []).append(row["listing_id"])
        if "recheck_raises" in overrides:
            raise overrides["recheck_raises"]
        return overrides.get(
            "recheck_stats",
            {
                "listings_checked": 1,
                "prices_found": 1,
                "new_listings": 0,
                "errors": 0,
                "tokens_in": 1200,
                "tokens_out": 300,
            },
        )

    async def hunt(agent_, job_id, row, browser, *, swap):
        seen.setdefault("hunts", []).append(job_id)
        seen.setdefault("swaps", []).append(swap)
        if "hunt_raises" in overrides:
            raise overrides["hunt_raises"]
        return overrides.get(
            "hunt_stats",
            {"listings_checked": 4, "prices_found": 2, "new_listings": 2, "errors": 0},
        )

    async def ground(item_id, item_name, category_id):
        return overrides.get(
            "ground_payload", {"status": "ok", "confidence": "high", "observations": [1, 2, 3]}
        )

    monkeypatch.setattr(worker, "open_browser_session", open_session)
    monkeypatch.setattr(worker, "get_recheck_unit", recheck_unit)
    monkeypatch.setattr(worker, "get_hunt_unit", hunt_unit)
    monkeypatch.setattr(worker, "get_ground_unit", ground_unit)
    monkeypatch.setattr(worker, "recheck_deterministic", deterministic)
    monkeypatch.setattr(worker, "recheck_listing", llm_recheck)
    monkeypatch.setattr(worker, "run_hunt_job", hunt)
    monkeypatch.setattr(worker, "ground_item", ground)
    monkeypatch.setattr(worker, "build_llm", lambda: "llm")
    monkeypatch.setattr(worker, "build_recheck_agent", lambda llm, tools: "recheck-agent")
    monkeypatch.setattr(worker, "build_hunt_agent", lambda llm, tools: "hunt-agent")
    monkeypatch.setattr(worker, "flush_traces", lambda: None)
    return seen


class TestRecheckPath:
    """The cheap path gets first refusal; the model is the fallback, and its
    read is what relearns the locator for next time."""

    def test_a_listing_the_ladder_can_read_never_reaches_the_model(self, monkeypatch):
        seen = wire(monkeypatch, ladder=FakeOutcome(True, "jsonld", "static"))
        stats = asyncio.run(worker.run_job(job()))
        assert seen.get("llm_rechecks") is None
        assert stats["listings_checked"] == 1
        assert (stats["method"], stats["transport"]) == ("jsonld", "static")
        assert stats["tokens_in"] == 0

    def test_a_listing_the_ladder_cannot_read_falls_back_to_the_model(self, monkeypatch):
        seen = wire(monkeypatch, ladder=FakeOutcome(False))
        stats = asyncio.run(worker.run_job(job()))
        assert seen["llm_rechecks"] == [1]
        assert (stats["method"], stats["transport"]) == ("llm", "browser")
        assert (stats["tokens_in"], stats["tokens_out"]) == (1200, 300)

    def test_the_kill_switch_puts_every_recheck_back_through_the_model(self, monkeypatch):
        seen = wire(monkeypatch, ladder=FakeOutcome(True))
        monkeypatch.setattr(worker, "CHEAP_RECHECK", False)
        asyncio.run(worker.run_job(job()))
        assert seen["llm_rechecks"] == [1]

    def test_an_untracked_listing_is_nothing_to_do_not_a_failure(self, monkeypatch):
        async def gone(listing_id):
            return None

        seen = wire(monkeypatch)
        monkeypatch.setattr(worker, "get_recheck_unit", gone)
        stats = asyncio.run(worker.run_job(job()))
        assert stats["listings_checked"] == 0
        assert seen.get("llm_rechecks") is None

    def test_a_readable_page_clears_the_sites_error_count(self, monkeypatch):
        seen = wire(monkeypatch)
        asyncio.run(worker.run_job(job()))
        assert seen["outcomes"] == [(1, True)]


class TestTheBreakerHearsAFailedRead:
    """A model that cannot read a page says so by recording status="error",
    not by raising — so a marketplace that has stopped answering looks, from
    the outside, exactly like a run of perfectly successful jobs."""

    def test_a_unit_that_read_nothing_counts_against_its_site(self, monkeypatch):
        seen = wire(
            monkeypatch,
            ladder=FakeOutcome(False),
            recheck_stats={
                "listings_checked": 1,
                "prices_found": 0,
                "new_listings": 0,
                "errors": 1,
                "tokens_in": 900,
                "tokens_out": 100,
            },
        )
        asyncio.run(worker.run_job(job()))
        assert seen["outcomes"] == [(1, False)]

    def test_one_bad_listing_among_good_ones_is_still_an_answer(self, monkeypatch):
        # otherwise five mixed hunts in a row would pause a working site
        seen = wire(
            monkeypatch,
            hunt_stats={
                "listings_checked": 5,
                "prices_found": 2,
                "new_listings": 1,
                "errors": 1,
            },
        )
        asyncio.run(worker.run_job(job("hunt")))
        assert seen["outcomes"] == [(1, True)]

    def test_a_hunt_that_found_nothing_worth_saving_is_not_a_failure(self, monkeypatch):
        seen = wire(
            monkeypatch,
            hunt_stats={"listings_checked": 6, "prices_found": 0, "new_listings": 0, "errors": 0},
        )
        asyncio.run(worker.run_job(job("hunt")))
        assert seen["outcomes"] == [(1, True)]


class TestHuntPath:
    def test_a_pair_the_watch_no_longer_searches_is_nothing_to_do(self, monkeypatch):
        async def gone(watch_id, site_id):
            return None

        seen = wire(monkeypatch)
        monkeypatch.setattr(worker, "get_hunt_unit", gone)
        stats = asyncio.run(worker.run_job(job("hunt")))
        assert stats["listings_checked"] == 0
        assert seen.get("hunts") is None

    def test_a_hunts_tally_becomes_the_jobs_stats(self, monkeypatch):
        wire(monkeypatch)
        stats = asyncio.run(worker.run_job(job("hunt")))
        assert stats["new_listings"] == 2
        assert stats["duration_ms"] >= 0

    def test_only_a_job_flagged_swap_runs_as_a_swap_hunt(self, monkeypatch):
        seen = wire(monkeypatch)
        asyncio.run(worker.run_job(job("hunt", payload={"swap": True})))
        asyncio.run(worker.run_job(job("hunt", payload={"backoff_minutes": 30})))
        asyncio.run(worker.run_job(job("hunt")))
        assert seen["swaps"] == [True, False, False]


class TestGroundPath:
    def test_grounding_needs_no_browser_and_says_what_it_found(self, monkeypatch):
        seen = wire(monkeypatch)
        stats = asyncio.run(worker.run_job(job("ground", listing_id=None)))
        assert stats["prices_found"] == 3
        assert any(event_type == "job_finished" for _, _, event_type, _ in seen["events"])

    def test_grounding_runs_inside_one_trace_per_item_for_no_one_user(self, monkeypatch):
        wire(monkeypatch)
        opened = []

        @contextmanager
        def job_trace(name, session_id, tags, **ids):
            opened.append((name, session_id, tags, ids))
            yield

        monkeypatch.setattr(worker, "job_trace", job_trace)
        asyncio.run(worker.run_job(job("ground", listing_id=None)))
        # job_trace takes no user: grounding is shared by every watcher
        assert opened == [
            (
                "ground",
                "item-1",
                ["kind:ground", "category:video-games"],
                {"job_id": 1, "item_id": 1, "category_id": 1},
            )
        ]


class TestTerminalWrites:
    def test_a_finished_job_is_completed_with_its_stats(self, monkeypatch):
        seen = wire(monkeypatch)
        asyncio.run(worker._work_one("w1", job()))
        (job_id, stats) = seen["completed"][0]
        assert job_id == 1
        assert stats["listings_checked"] == 1
        assert seen["failed"] == []

    def test_a_failing_job_is_retried_and_counted_against_its_site(self, monkeypatch):
        seen = wire(monkeypatch, hunt_raises=RuntimeError("challenge page"))
        asyncio.run(worker._work_one("w1", job("hunt")))
        assert seen["failed"] == [(1, "challenge page")]
        assert seen["completed"] == []
        assert (1, False) in seen["outcomes"]
        assert any(event_type == "error" for _, _, event_type, _ in seen["events"])

    def test_a_cancelled_job_keeps_the_apis_terminal_state(self, monkeypatch):
        seen = wire(monkeypatch, hunt_raises=agent.Cancelled("job 1 was cancelled"))
        asyncio.run(worker._work_one("w1", job("hunt")))
        assert seen["completed"] == [(1, None)]
        assert seen["failed"] == []
        assert ("Cancelled by you") in [message for _, _, _, message in seen["events"]]

    def test_a_hunt_says_what_it_found_when_it_finishes(self, monkeypatch):
        seen = wire(monkeypatch)
        asyncio.run(worker._work_one("w1", job("hunt")))
        finished = [m for _, _, event_type, m in seen["events"] if event_type == "job_finished"]
        assert finished == ["Hunt complete — 2 new · 4 seen"]

    def test_a_check_finishes_in_silence(self, monkeypatch):
        # a recheck writes no events at all: its whole output is the price
        # check, which the trigger turns into a listing.checked frame
        seen = wire(monkeypatch)
        asyncio.run(worker._work_one("w1", job()))
        assert seen["events"] == []


class TestHeartbeat:
    def test_a_long_job_keeps_beating(self, monkeypatch):
        seen = wire(monkeypatch)
        monkeypatch.setattr(worker, "JOB_HEARTBEAT_INTERVAL_SECONDS", 0.01)

        async def slow():
            await asyncio.sleep(0.05)
            return "done"

        assert asyncio.run(worker._with_heartbeat(7, slow())) == "done"
        assert seen["beats"].count(7) >= 2

    def test_the_heartbeat_stops_with_the_job(self, monkeypatch):
        seen = wire(monkeypatch)
        monkeypatch.setattr(worker, "JOB_HEARTBEAT_INTERVAL_SECONDS", 0.01)

        async def scenario():
            async def quick():
                return None

            await worker._with_heartbeat(7, quick())
            await asyncio.sleep(0.05)

        asyncio.run(scenario())
        assert seen["beats"] == []


class TestPool:
    """A pool drains its kind until the queue is empty, then waits to be
    nudged — by a NOTIFY or by the tick, which are the same code path."""

    def test_a_pool_drains_until_the_queue_is_empty(self, monkeypatch):
        queue = [job(job_id=1), job(job_id=2), job(job_id=3)]
        seen = wire(monkeypatch, queue=queue)

        async def scenario():
            wake = asyncio.Event()
            task = asyncio.create_task(worker._pool("check-0", ("recheck",), wake))
            for _ in range(20):
                await asyncio.sleep(0)
                if not queue:
                    break
            await asyncio.sleep(0.05)
            task.cancel()
            return task

        asyncio.run(scenario())
        assert [job_id for job_id, _ in seen["completed"]] == [1, 2, 3]

    def test_a_nudge_wakes_a_pool_that_had_nothing_to_do(self, monkeypatch):
        queue = []
        seen = wire(monkeypatch, queue=queue)

        async def scenario():
            wake = asyncio.Event()
            task = asyncio.create_task(worker._pool("check-0", ("recheck",), wake))
            await asyncio.sleep(0.02)
            assert seen["completed"] == []
            queue.append(job(job_id=9))
            worker._nudge([wake])
            await asyncio.sleep(0.02)
            task.cancel()

        asyncio.run(scenario())
        assert [job_id for job_id, _ in seen["completed"]] == [9]

    def test_a_job_that_blows_up_never_takes_the_pool_down(self, monkeypatch):
        queue = [job(job_id=1), job(job_id=2)]
        calls = {"n": 0}

        async def sometimes_explodes(browser, row):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("the page timed out")
            return FakeOutcome(True)

        seen = wire(monkeypatch, queue=queue)
        monkeypatch.setattr(worker, "recheck_deterministic", sometimes_explodes)

        async def scenario():
            wake = asyncio.Event()
            task = asyncio.create_task(worker._pool("check-0", ("recheck",), wake))
            await asyncio.sleep(0.05)
            task.cancel()

        asyncio.run(scenario())
        assert seen["failed"] == [(1, "the page timed out")]
        assert [job_id for job_id, _ in seen["completed"]] == [2]

    def test_each_pool_claims_only_its_own_kinds(self, monkeypatch):
        seen = wire(monkeypatch, queue=[])

        async def scenario():
            wake = asyncio.Event()
            checks = asyncio.create_task(worker._pool("x#check-0", worker.CHECK_KINDS, wake))
            hunts = asyncio.create_task(worker._pool("x#hunt-0", worker.HUNT_KINDS, wake))
            await asyncio.sleep(0.02)
            checks.cancel()
            hunts.cancel()

        asyncio.run(scenario())
        assert ("x#check-0", ("recheck",)) in seen["claimed"]
        assert ("x#hunt-0", ("hunt", "ground")) in seen["claimed"]

    def test_with_hunting_off_the_hunt_pool_only_grounds(self, monkeypatch):
        # the kill switch: a queued hunt is left waiting, never claimed
        seen = wire(monkeypatch, queue=[])
        monkeypatch.setattr(worker, "HUNT_ENABLED", False)

        asyncio.run(worker.once())

        hunt_pool = [kinds for worker_id, kinds in seen["claimed"] if "#hunt-" in worker_id]
        check_pool = [kinds for worker_id, kinds in seen["claimed"] if "#check-" in worker_id]
        assert hunt_pool and all(kinds == ("ground",) for kinds in hunt_pool)
        # checks are what the operator still wants
        assert check_pool and all(kinds == ("recheck",) for kinds in check_pool)


class TestShutdown:
    def test_stopping_hands_every_in_flight_job_back(self, monkeypatch):
        seen = wire(monkeypatch, queue=[])

        async def never(*args):
            await asyncio.Event().wait()

        monkeypatch.setattr(worker, "_listen", never)
        monkeypatch.setattr(worker, "_scheduler", never)

        async def scenario():
            task = asyncio.create_task(worker.serve())
            await asyncio.sleep(0.02)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(scenario())
        # exactly this process's workers, so a second instance is untouched
        assert len(seen["released"]) == 1
        assert seen["released"][0] == worker.worker_ids()

    def test_one_drain_releases_what_it_held_too(self, monkeypatch):
        seen = wire(monkeypatch, queue=[job(job_id=1)])
        asyncio.run(worker.once())
        assert [job_id for job_id, _ in seen["completed"]] == [1]
        assert seen["released"][0] == worker.worker_ids()


class TestHousekeeping:
    def test_a_pass_reaps_and_queues_what_is_due(self, monkeypatch):
        seen = wire(monkeypatch)

        async def candidates():
            return [
                {
                    "item_id": 1,
                    "item_name": "a",
                    "category_id": 1,
                    "as_of": None,
                    "last_attempt_at": None,
                },
                {
                    "item_id": 2,
                    "item_name": "b",
                    "category_id": 1,
                    "as_of": None,
                    "last_attempt_at": None,
                },
            ]

        monkeypatch.setattr(worker, "get_grounding_candidates", candidates)
        asyncio.run(worker.housekeeping())
        assert seen["reaped"] == 1
        assert seen["grounded"] == [1, 2]

    def test_a_fresh_item_is_not_grounded_again(self, monkeypatch):
        from datetime import UTC, datetime, timedelta

        seen = wire(monkeypatch)
        an_hour_ago = datetime.now(UTC) - timedelta(hours=1)

        async def candidates():
            return [
                {
                    "item_id": 1,
                    "item_name": "a",
                    "category_id": 1,
                    "as_of": an_hour_ago,
                    "last_attempt_at": an_hour_ago,
                }
            ]

        monkeypatch.setattr(worker, "get_grounding_candidates", candidates)
        asyncio.run(worker.housekeeping())
        assert seen["grounded"] == []

    def test_retention_runs_on_its_own_slower_clock(self, monkeypatch):
        seen = wire(monkeypatch)

        async def candidates():
            return []

        monkeypatch.setattr(worker, "get_grounding_candidates", candidates)
        asyncio.run(worker.housekeeping(ticks=0))
        asyncio.run(worker.housekeeping(ticks=1))
        assert (seen["reaped"], seen["pruned"]) == (2, 1)

    def test_the_sweep_runs_on_wake_and_then_hourly(self, monkeypatch):
        # tick 0 is the scheduler's first pass — the hunter starting — and a
        # pass every minute makes tick 60 an hour later
        seen = wire(monkeypatch)

        async def candidates():
            return []

        monkeypatch.setattr(worker, "get_grounding_candidates", candidates)
        for ticks in range(worker.SWEEP_EVERY_TICKS + 1):
            asyncio.run(worker.housekeeping(ticks=ticks))
        assert seen["swept"] == 2
        assert worker.SWEEP_EVERY_TICKS * worker.SCHEDULER_INTERVAL_SECONDS == 3600

    def test_a_one_shot_drain_sweeps_first(self, monkeypatch):
        # --once under cron is a wake too: what the chain dropped is queued
        # before the drain, so this very run works it
        seen = wire(monkeypatch, queue=[])

        async def candidates():
            return []

        monkeypatch.setattr(worker, "get_grounding_candidates", candidates)
        asyncio.run(worker.once())
        assert seen["swept"] == 1


class TestBrowserFailureDetection:
    """A unit whose every browser call errored ends with the model politely
    summarising that it couldn't browse — which would otherwise look clean."""

    def browser_error(self):
        return ToolMessage(
            content="net::ERR", name="browser_navigate", status="error", tool_call_id="1"
        )

    def browser_ok(self):
        return ToolMessage(content="page", name="browser_navigate", tool_call_id="2")

    def test_all_browser_calls_failing_raises(self):
        with pytest.raises(RuntimeError, match="every browser call failed"):
            agent._require_browser_success([self.browser_error(), AIMessage(content="sorry")])

    def test_a_partial_browser_failure_is_normal_browsing(self):
        agent._require_browser_success([self.browser_error(), self.browser_ok()])

    def test_db_tool_errors_do_not_trigger_it(self):
        agent._require_browser_success(
            [
                ToolMessage(
                    content="Error: bad id",
                    name="save_price_check",
                    status="error",
                    tool_call_id="3",
                )
            ]
        )

    def test_a_unit_with_no_browser_calls_passes(self):
        agent._require_browser_success([AIMessage(content="done")])


class TestUnitBudgets:
    def test_a_unit_past_the_wall_clock_budget_fails_with_a_message(self, monkeypatch):
        monkeypatch.setattr(agent, "AGENT_UNIT_TIMEOUT_SECONDS", 0.01)

        async def wedged():
            await asyncio.Event().wait()

        with pytest.raises(RuntimeError, match="budget"):
            asyncio.run(agent.bounded(wedged()))

    def test_a_unit_inside_the_budget_hands_its_value_back(self, monkeypatch):
        monkeypatch.setattr(agent, "AGENT_UNIT_TIMEOUT_SECONDS", 5)

        async def quick():
            return "value"

        assert asyncio.run(agent.bounded(quick())) == "value"

    def test_the_step_cap_rides_on_every_units_config(self):
        config = agent.agent_config(
            "hunt",
            UnitContext(watch_id=1, item_id=1, site_id=1),
            user_id=1,
            site_name="eBay",
            category="video-games",
        )
        assert config["recursion_limit"] == agent.AGENT_MAX_STEPS


def unit_config(kind, **unit):
    """agent_config for a unit on watch 12 (user 3, item 5, site 2 = eBay)."""
    context = UnitContext(watch_id=12, item_id=5, site_id=2, job_id=40, **unit)
    return agent.agent_config(kind, context, user_id=3, site_name="eBay", category="video-games")


class TestTraceGrouping:
    def test_a_watchs_hunts_and_rechecks_share_one_session(self):
        hunt = unit_config("hunt")["metadata"]
        recheck = unit_config("recheck", listing_id=9)["metadata"]
        assert hunt["langfuse_session_id"] == recheck["langfuse_session_id"] == "watch-12"
        assert hunt["session_id"] == "watch-12"

    def test_every_trace_carries_the_watch_owner(self):
        metadata = unit_config("hunt")["metadata"]
        assert metadata["langfuse_user_id"] == metadata["user_id"] == "3"

    def test_a_trace_is_named_and_tagged_by_kind_site_and_category(self):
        config = unit_config("recheck", listing_id=9)
        assert config["run_name"] == "recheck"
        assert config["metadata"]["langfuse_tags"] == [
            "kind:recheck",
            "site:eBay",
            "category:video-games",
        ]

    def test_a_swap_hunt_is_tagged_as_one(self):
        assert "swap" in unit_config("hunt", swap=Swap())["metadata"]["langfuse_tags"]
        assert "swap" not in unit_config("hunt")["metadata"]["langfuse_tags"]

    def test_the_ids_a_unit_is_bound_to_lead_back_to_its_job(self):
        hunt = unit_config("hunt")["metadata"]
        recheck = unit_config("recheck", listing_id=9)["metadata"]
        assert (hunt["job_id"], hunt["watch_id"], hunt["item_id"], hunt["site_id"]) == (
            40,
            12,
            5,
            2,
        )
        assert "listing_id" not in hunt
        assert recheck["listing_id"] == 9

    def test_the_unit_stays_out_of_the_trace_metadata(self):
        config = unit_config("hunt")
        assert "unit" not in config["metadata"]
        assert config["configurable"]["unit"].watch_id == 12
