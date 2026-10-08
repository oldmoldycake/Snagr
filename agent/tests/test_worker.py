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
from datetime import UTC, datetime

import pytest
import worker
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.errors import GraphRecursionError
from observations import UnitContext
from search import SearchSuspended

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
        "deferred": [],
        "ended_by": [],
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

    async def complete(job_id, stats=None, *, worker):
        seen["completed"].append((job_id, stats))
        seen["ended_by"].append(worker)
        return True

    async def fail_or_retry(job_id, error, *, worker):
        seen["failed"].append((job_id, error))
        seen["ended_by"].append(worker)
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

    async def defer(job_id, until, *, worker):
        seen["deferred"].append((job_id, until))
        seen["ended_by"].append(worker)
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
        ("defer", defer),
    ):
        monkeypatch.setattr(worker.job_queue, name, overrides.get(name, fake))
    monkeypatch.setattr(worker.breaker, "record_outcome", record_outcome)
    monkeypatch.setattr(worker, "backoff", worker.Backoff())

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

    async def grounding_candidates():
        # housekeeping reads these on every pass; nothing is due unless a
        # test says so
        return []

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

    async def hunt(agent_, job_id, row, browser):
        seen.setdefault("hunts", []).append(job_id)
        if "hunt_raises" in overrides:
            raise overrides["hunt_raises"]
        return overrides.get(
            "hunt_stats",
            {"listings_checked": 4, "prices_found": 2, "new_listings": 2, "errors": 0},
        )

    async def ground(item_id, item_name, category_id):
        if "ground_raises" in overrides:
            raise overrides["ground_raises"]
        return overrides.get(
            "ground_payload", {"status": "ok", "confidence": "high", "observations": [1, 2, 3]}
        )

    monkeypatch.setattr(worker, "open_browser_session", open_session)
    monkeypatch.setattr(worker, "get_recheck_unit", recheck_unit)
    monkeypatch.setattr(worker, "get_hunt_unit", hunt_unit)
    monkeypatch.setattr(worker, "get_ground_unit", ground_unit)
    monkeypatch.setattr(worker, "get_grounding_candidates", grounding_candidates)
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


class TestGroundPath:
    def test_grounding_needs_no_browser_and_says_what_it_found(self, monkeypatch):
        seen = wire(monkeypatch)
        stats = asyncio.run(worker.run_job(job("ground", listing_id=None)))
        assert stats["prices_found"] == 3
        assert any(event_type == "job_finished" for _, _, event_type, _ in seen["events"])

    def test_a_grounding_that_found_no_price_finishes_with_a_warning(self, monkeypatch):
        # nothing broke, so it is not a failure — but "done" alone would hide
        # that the market stats came to nothing
        seen = wire(
            monkeypatch,
            ground_payload={"status": "insufficient", "confidence": "low", "observations": []},
        )
        stats = asyncio.run(worker.run_job(job("ground", listing_id=None)))
        assert stats["prices_found"] == 0
        assert [(level, m) for _, level, t, m in seen["events"] if t == "job_finished"] == [
            ("warn", "Market price for Item 1: found no prices")
        ]

    def test_grounding_counts_the_tokens_its_model_calls_spend(self, monkeypatch):
        wire(monkeypatch)

        def reply(tokens_in, tokens_out, **metadata):
            usage = {
                "input_tokens": tokens_in,
                "output_tokens": tokens_out,
                "total_tokens": tokens_in + tokens_out,
            }
            message = AIMessage(content="{}", usage_metadata=usage, response_metadata=metadata)
            return GenericFakeChatModel(messages=iter([message]))

        async def ground(item_id, item_name, category_id):
            # extraction calls sit deep inside the grounding, some in tasks of
            # their own, and a provider need not name its model for them to count
            await reply(100, 20, model_name="m").ainvoke("tiers")
            await asyncio.gather(reply(300, 40).ainvoke("snippets"), reply(5, 1).ainvoke("guide"))
            return {"status": "ok", "confidence": "high", "observations": [1]}

        monkeypatch.setattr(worker, "ground_item", ground)
        stats = asyncio.run(worker.run_job(job("ground", listing_id=None)))
        assert (stats["tokens_in"], stats["tokens_out"]) == (405, 61)

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

    def test_every_terminal_write_names_the_worker_that_held_the_job(self, monkeypatch):
        # the queue drops the write of a worker the reaper took the job from,
        # so the pool must say which worker it is
        seen = wire(monkeypatch)
        asyncio.run(worker._work_one("x#check-2", job()))
        seen_failed = wire(monkeypatch, hunt_raises=RuntimeError("the page timed out"))
        asyncio.run(worker._work_one("x#hunt-0", job("hunt")))
        seen_deferred = wire(monkeypatch, ground_raises=SearchSuspended(datetime.now(UTC)))
        asyncio.run(worker._work_one("x#ground-0", job("ground", listing_id=None)))
        assert seen["ended_by"] == ["x#check-2"]
        assert seen_failed["ended_by"] == ["x#hunt-0"]
        assert seen_deferred["ended_by"] == ["x#ground-0"]

    def test_a_site_that_gave_up_no_page_is_retried_and_counted_against_it(self, monkeypatch):
        seen = wire(monkeypatch, hunt_raises=agent.SiteUnreadable("every browser call failed"))
        asyncio.run(worker._work_one("w1", job("hunt")))
        assert seen["failed"] == [(1, "No page on the site would load.")]
        assert seen["completed"] == []
        assert seen["outcomes"] == [(1, False)]
        assert any(event_type == "error" for _, _, event_type, _ in seen["events"])
        assert worker.backoff.until is None

    def test_a_site_paused_for_giving_up_no_page_says_so_in_plain_words(self, monkeypatch):
        # the pause reason is shown on the paused-site card as it is
        wire(monkeypatch, hunt_raises=agent.SiteUnreadable("every browser call failed: net::ERR"))
        details = []

        async def record_outcome(site_id, ok, **kwargs):
            details.append(kwargs["detail"])

        monkeypatch.setattr(worker.breaker, "record_outcome", record_outcome)
        asyncio.run(worker._work_one("w1", job("hunt")))
        assert details == ["no page would load"]

    def test_the_hunters_own_failure_is_retried_but_blames_no_site(self, monkeypatch):
        # an LLM key the provider refuses fails every site's hunt the same way;
        # counting it would pause every marketplace for the length of the outage
        seen = wire(monkeypatch, hunt_raises=agent.ModelFailed("401 invalid x-api-key"))
        asyncio.run(worker._work_one("w1", job("hunt")))
        assert seen["failed"] == [(1, "The AI provider returned an error.")]
        assert seen["outcomes"] == []
        assert worker.backoff.until is not None

    def test_a_failed_grounding_never_reaches_the_breaker(self, monkeypatch):
        seen = wire(monkeypatch, ground_raises=OSError("connection refused"))
        asyncio.run(worker._work_one("w1", job("ground", site_id=None, listing_id=None)))
        assert seen["failed"] == [(1, "Snagr ran into an unexpected error.")]
        assert seen["outcomes"] == []

    @pytest.mark.parametrize(
        "error, reason",
        [
            (
                agent.TimedOut("unit exceeded the 900s budget"),
                "Took too long, so Snagr stopped it.",
            ),
            (agent.SiteUnreadable("every browser call failed"), "No page on the site would load."),
            (agent.ModelFailed("Error code: 429"), "The AI provider returned an error."),
            (
                GraphRecursionError("Recursion limit of 60 reached"),
                "The AI took too many steps without finishing.",
            ),
            (KeyError("site_name"), "Snagr ran into an unexpected error."),
        ],
    )
    def test_a_failure_is_named_in_plain_words_with_its_own_text_kept_as_detail(
        self, monkeypatch, error, reason
    ):
        # the job's error is what every Activity surface shows; the raw text
        # is for whoever runs Snagr, behind the job page's disclosure
        payloads = []

        async def append_event(job_id, level, event_type, message, payload=None):
            payloads.append((level, event_type, message, payload))
            return 1

        seen = wire(monkeypatch, hunt_raises=error, append_event=append_event)
        asyncio.run(worker._work_one("w1", job("hunt")))
        assert seen["failed"] == [(1, reason)]
        assert payloads[-1] == ("error", "error", reason, {"detail": str(error)})

    def test_a_suspended_search_hands_the_job_back_instead_of_holding_its_slot(self, monkeypatch):
        until = datetime(2026, 9, 26, 16, 31, tzinfo=UTC)
        seen = wire(monkeypatch, ground_raises=SearchSuspended(until))
        asyncio.run(worker._work_one("w1", job("ground", listing_id=None)))
        assert seen["deferred"] == [(1, until)]
        # waiting out SearXNG is neither a failure nor a finish, and it is no
        # site's fault
        assert seen["failed"] == []
        assert seen["completed"] == []
        assert seen["outcomes"] == []
        assert [(level, m) for _, level, _, m in seen["events"]] == [
            ("warn", "SearXNG has suspended its engines; trying again at 16:31 UTC")
        ]

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
        assert finished == ["Hunt complete — 2 new · 4 looked at"]

    def test_a_check_finishes_in_silence(self, monkeypatch):
        # a recheck writes no events at all: its whole output is the price
        # check, which the trigger turns into a listing.checked frame
        seen = wire(monkeypatch)
        asyncio.run(worker._work_one("w1", job()))
        assert seen["events"] == []


class TestBackoff:
    def test_each_failure_in_a_row_doubles_the_hold_up_to_the_cap(self, monkeypatch):
        monkeypatch.setattr(worker, "INFRA_BACKOFF_SECONDS", 30)
        monkeypatch.setattr(worker, "INFRA_BACKOFF_CAP_SECONDS", 100)
        hold = worker.Backoff()
        waits = []
        for _ in range(4):
            hold.failed(RuntimeError("down"))
            waits.append(round((hold.until - datetime.now(UTC)).total_seconds()))
        assert waits == [30, 60, 100, 100]

    def test_a_finished_job_lifts_the_hold(self):
        hold = worker.Backoff()
        hold.failed(RuntimeError("down"))
        hold.cleared()
        assert hold.failures == 0
        assert hold.until is None


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
        monkeypatch.setattr(worker, "INFRA_BACKOFF_SECONDS", 0.01)

        async def scenario():
            wake = asyncio.Event()
            task = asyncio.create_task(worker._pool("check-0", ("recheck",), wake))
            await asyncio.sleep(0.05)
            task.cancel()

        asyncio.run(scenario())
        assert seen["failed"] == [(1, "Snagr ran into an unexpected error.")]
        assert [job_id for job_id, _ in seen["completed"]] == [2]

    def test_losing_the_database_mid_claim_never_takes_the_pool_down(self, monkeypatch):
        queue = [job(job_id=1)]
        claims = {"n": 0}

        async def flaky_claim(worker_id, kinds):
            claims["n"] += 1
            if claims["n"] == 1:
                raise ConnectionError("connection was closed in the middle of operation")
            return queue.pop(0) if queue else None

        seen = wire(monkeypatch, claim=flaky_claim)
        monkeypatch.setattr(worker, "POOL_RETRY_SECONDS", 0.01)

        async def scenario():
            wake = asyncio.Event()
            task = asyncio.create_task(worker._pool("check-0", ("recheck",), wake))
            await asyncio.sleep(0.05)
            alive = not task.done()
            task.cancel()
            return alive

        assert asyncio.run(scenario())
        assert [job_id for job_id, _ in seen["completed"]] == [1]

    def test_losing_the_database_while_failing_a_job_never_takes_the_pool_down(self, monkeypatch):
        # the job whose terminal write was lost stays running for the reaper;
        # the pool carries on with the next one
        queue = [job(job_id=1), job(job_id=2)]
        calls = {"n": 0}

        async def explodes_once(browser, row):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("the page timed out")
            return FakeOutcome(True)

        async def db_gone(job_id, error, *, worker):
            raise ConnectionError("connection was closed in the middle of operation")

        seen = wire(monkeypatch, queue=queue, fail_or_retry=db_gone)
        monkeypatch.setattr(worker, "recheck_deterministic", explodes_once)
        monkeypatch.setattr(worker, "INFRA_BACKOFF_SECONDS", 0.01)
        monkeypatch.setattr(worker, "POOL_RETRY_SECONDS", 0.01)

        async def scenario():
            wake = asyncio.Event()
            task = asyncio.create_task(worker._pool("check-0", ("recheck",), wake))
            await asyncio.sleep(0.1)
            alive = not task.done()
            task.cancel()
            return alive

        assert asyncio.run(scenario())
        assert [job_id for job_id, _ in seen["completed"]] == [2]

    def test_a_pool_holds_off_after_a_failure_no_site_is_to_blame_for(self, monkeypatch):
        queue = [job(job_id=1, kind="hunt"), job(job_id=2, kind="hunt")]
        calls = {"n": 0}

        async def provider_down_once(agent_, job_id, row, browser):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("429 quota exceeded")
            return {"listings_checked": 1, "prices_found": 1, "new_listings": 0, "errors": 0}

        seen = wire(monkeypatch, queue=queue)
        monkeypatch.setattr(worker, "run_hunt_job", provider_down_once)
        monkeypatch.setattr(worker, "INFRA_BACKOFF_SECONDS", 0.1)

        async def scenario():
            wake = asyncio.Event()
            task = asyncio.create_task(worker._pool("hunt-0", ("hunt",), wake))
            await asyncio.sleep(0.05)
            held = list(seen["completed"])
            await asyncio.sleep(0.15)
            task.cancel()
            return held

        held = asyncio.run(scenario())
        assert held == []
        assert [job_id for job_id, _ in seen["completed"]] == [2]
        assert worker.backoff.until is None

    def test_each_pool_claims_only_its_own_kinds(self, monkeypatch):
        seen = wire(monkeypatch, queue=[])

        async def scenario():
            wake = asyncio.Event()
            pools = [
                asyncio.create_task(worker._pool(worker_id, worker.kinds_for(worker_id), wake))
                for worker_id in ("x#check-0", "x#hunt-0", "x#ground-0")
            ]
            await asyncio.sleep(0.02)
            for pool in pools:
                pool.cancel()

        asyncio.run(scenario())
        assert ("x#check-0", ("recheck",)) in seen["claimed"]
        assert ("x#hunt-0", ("hunt",)) in seen["claimed"]
        # grounding waits on SearXNG, so it never holds a hunt's slot
        assert ("x#ground-0", ("ground",)) in seen["claimed"]

    def test_every_pool_is_sized_on_its_own(self, monkeypatch):
        monkeypatch.setattr(worker, "RECHECK_CONCURRENCY", 3)
        monkeypatch.setattr(worker, "HUNT_CONCURRENCY", 1)
        monkeypatch.setattr(worker, "GROUND_CONCURRENCY", 2)
        slots = [worker_id.rsplit("#", 1)[1] for worker_id in worker.worker_ids()]
        assert slots == ["check-0", "check-1", "check-2", "hunt-0", "ground-0", "ground-1"]

    def test_with_hunting_off_there_is_no_hunt_pool(self, monkeypatch):
        # the kill switch: a queued hunt is left waiting, never claimed
        seen = wire(monkeypatch, queue=[])
        monkeypatch.setattr(worker, "HUNT_ENABLED", False)

        asyncio.run(worker.once())

        claimed = {kinds for _, kinds in seen["claimed"]}
        # checks and grounding are what the operator still wants
        assert claimed == {("recheck",), ("ground",)}


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


class TestSearchNotice:
    def _once(self, monkeypatch, provider):
        wire(monkeypatch, queue=[])

        async def candidates():
            return []

        monkeypatch.setattr(worker, "get_grounding_candidates", candidates)
        monkeypatch.setattr(worker, "SEARCH_PROVIDER", provider)
        asyncio.run(worker.once())

    def test_no_search_provider_is_announced_at_startup(self, monkeypatch, caplog):
        self._once(monkeypatch, "none")
        assert "Grounding search is off" in caplog.text

    def test_a_configured_provider_says_nothing(self, monkeypatch, caplog):
        self._once(monkeypatch, "brave")
        assert "Grounding search is off" not in caplog.text


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
        with pytest.raises(agent.SiteUnreadable, match="every browser call failed"):
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

        with pytest.raises(agent.TimedOut, match="budget"):
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


class ToolCallingFake(GenericFakeChatModel):
    """A scripted model that accepts tools, so its replies can call them."""

    def bind_tools(self, tools, **kwargs):
        return self


def run_unit(model, tools) -> None:
    """Stream a one-prompt agent wrapped the way the units are, to the end."""
    unit = agent.create_agent(model, tools, middleware=[agent.model_failures])

    async def scenario():
        async for _ in unit.astream({"messages": [{"role": "user", "content": "go"}]}):
            pass

    asyncio.run(scenario())


class TestModelFailures:
    """Every provider raises its own types, so the model call is wrapped to
    say a failure was the model's — and only the model call."""

    def test_a_refused_model_call_is_a_model_failure_with_the_providers_text(self):
        def refused():
            raise RuntimeError("Error code: 401 - invalid x-api-key")
            yield

        with pytest.raises(agent.ModelFailed, match="401 - invalid x-api-key"):
            run_unit(GenericFakeChatModel(messages=refused()), [])

    def test_a_tool_that_raises_is_not_blamed_on_the_model(self):
        @tool
        def explode() -> str:
            """Fail the way a lost database would."""
            raise LookupError("the database went away")

        calls = AIMessage(content="", tool_calls=[{"name": "explode", "args": {}, "id": "1"}])
        with pytest.raises(LookupError):
            run_unit(ToolCallingFake(messages=iter([calls])), [explode])

    def test_both_units_wrap_only_the_model_call(self, monkeypatch):
        built = []
        monkeypatch.setattr(
            agent, "create_agent", lambda llm, tools, **kwargs: built.append(kwargs["middleware"])
        )
        agent.build_recheck_agent("llm", [])
        agent.build_hunt_agent("llm", [])
        # the last middleware is the innermost, so nothing else is inside it
        assert [middleware[-1] for middleware in built] == [agent.model_failures] * 2


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
        assert "swap" in unit_config("hunt", swap=True)["metadata"]["langfuse_tags"]
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


class TestHuntOnAFullWatch:
    """A hunt still queued when another site filled the watch runs as a swap
    hunt, so every site that was queued gets searched; the queue adding no
    hunt for a full watch is what keeps that to one pass (test_jobs_db.py)."""

    def _run(self, monkeypatch, tracked: int) -> dict:
        seen = {}

        async def stream(agent_, prompt, config, job_id):
            seen["prompt"] = prompt
            seen["unit"] = config["configurable"]["unit"]
            return []

        async def nothing(*args, **kwargs):
            return []

        async def count(watch_id):
            return tracked

        async def listings(watch_id, selection_mode):
            return [
                {
                    "listing_id": n,
                    "site_name": "OtherBay",
                    "title": f"Widget #{n}",
                    "price": None,
                    "match_score": 70,
                }
                for n in range(1, tracked + 1)
            ]

        async def no_market(item_id):
            return None

        async def event(*args, **kwargs):
            return None

        monkeypatch.setattr(agent, "_stream", stream)
        monkeypatch.setattr(agent, "get_active_listing_count", count)
        monkeypatch.setattr(agent, "get_tracked_listings", listings)
        monkeypatch.setattr(agent, "get_known_listing_urls", nothing)
        monkeypatch.setattr(agent, "get_checked_urls", nothing)
        monkeypatch.setattr(agent, "get_market_price", no_market)
        monkeypatch.setattr(agent, "append_event", event)
        row = {**hunt_row(max_listings=3), "category_slug": "widgets"}
        asyncio.run(agent.run_hunt_job("hunt-agent", 7, row, browser=None))
        return seen

    def test_a_full_watch_is_searched_to_trade_up_not_skipped(self, monkeypatch):
        seen = self._run(monkeypatch, tracked=3)
        assert seen["unit"].swap
        assert "TRACKED LISTINGS: all 3 slot(s) are filled" in seen["prompt"]

    def test_a_watch_with_room_is_an_ordinary_hunt(self, monkeypatch):
        seen = self._run(monkeypatch, tracked=1)
        assert not seen["unit"].swap
        assert "TRACKING SLOTS: 2 open" in seen["prompt"]


class TestHuntContextTrimming:
    """Every model turn re-sends the whole history, so a hunt that kept every
    page snapshot would pay for its first page again on every later turn."""

    def _middleware(self, monkeypatch):
        built = {}

        def create(llm, tools, **kwargs):
            built.update(kwargs)
            return object()

        monkeypatch.setattr(agent, "create_agent", create)
        agent.build_hunt_agent("llm", [])
        trim_pages, _ = built["middleware"]
        return trim_pages

    def _transcript(self) -> list:
        messages = []
        calls = [("browser_navigate", f"page {n}") for n in range(5)]
        calls.insert(2, ("save_listing", "12"))
        for n, (name, content) in enumerate(calls):
            messages.append(
                AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": f"c{n}"}])
            )
            messages.append(ToolMessage(content=content, name=name, tool_call_id=f"c{n}"))
        return messages

    def test_only_the_latest_pages_reach_the_model(self, monkeypatch):
        middleware = self._middleware(monkeypatch)
        messages = self._transcript()
        (edit,) = middleware.edits
        edit.apply(messages, count_tokens=lambda _: 1)

        results = [m.content for m in messages if isinstance(m, ToolMessage)]
        kept = results[-agent.PAGES_KEPT :]
        assert kept == ["page 2", "page 3", "page 4"]
        # what the model saved is its record, never cleared
        assert "12" in results
        cleared = [r for r in results[: -agent.PAGES_KEPT] if r != "12"]
        assert cleared and all(r.startswith("[page cleared") for r in cleared)
