"""The run-queue consumer orchestration (agent.consume / agent.run /
agent.execute_run) with every seam monkeypatched: DB helpers, the grounding
pre-pass, the MCP/LLM agent builder, and the two per-unit workers. What's
under test is the lifecycle — claim, scope, events, stats, cooperative
cancellation, terminal writes — not SQL (that's test_run_queue_db.py) and
not the LLM."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
import tools
from database import roll_forward
from langchain_core.messages import ToolMessage

import agent


def run_row(run_id=1, scope="global", scope_id=None, label="Everything"):
    return {"id": run_id, "scope": scope, "scope_id": scope_id, "scope_label": label}


def listing_row(n):
    """A pass-1 row with only the keys the orchestrator itself reads."""
    return {"listing_id": n, "listing_url": f"https://example.test/l{n}"}


def pair_row(n, site_id=1, max_listings=3):
    """A pass-2 row with only the keys the orchestrator itself reads."""
    return {
        "watch_id": n,
        "item_id": n,
        "item_name": f"Item {n}",
        "site_id": site_id,
        "site_name": "TestBay",
        "max_listings": max_listings,
    }


def schedule_row(run_id=1, scope="global", scope_id=None, label="Everything"):
    """A claim_due_schedule result — a run_row plus the provenance marker."""
    return run_row(run_id, scope, scope_id, label) | {"scheduled": True}


def wire(
    monkeypatch,
    *,
    claim=None,
    claim_schedule=None,
    listings=(),
    pairs=(),
    statuses=None,
    fail_recheck=(),
    fail_scan=(),
    ground_raises=False,
    build_raises=False,
    tracked=None,
):
    """Point every seam at in-memory fakes; returns what the fakes saw.

    `statuses` scripts get_run_status answers in order, repeating the last one
    (default: forever "running"). `tracked` is the fake active-listing count
    per watch_id (default 0 — every slot open); a successful fake scan fills
    one slot, the way a real save would. Successful fake units bump
    tools.run_stats the way the real DB tools would.
    """
    seen = {
        "created": [],
        "queries": [],
        "events": [],
        "finishes": [],
        "recheck_units": [],
        "scan_units": [],
        "scan_tracked": [],
        "grounded": [],
        "built": [],
        "schedule_claims": [],
    }
    status_script = list(statuses or ["running"])

    async def fake_claim():
        return dict(claim) if claim else None

    async def fake_claim_schedule():
        seen["schedule_claims"].append(True)
        return dict(claim_schedule) if claim_schedule else None

    async def fake_create_global():
        seen["created"].append(True)
        return run_row()

    async def fake_status(run_id):
        return status_script.pop(0) if len(status_script) > 1 else status_script[0]

    async def fake_append(run_id, level, event_type, message, payload=None):
        seen["events"].append((level, event_type, message))
        return len(seen["events"])

    async def fake_finish(run_id, status, stats=None, error=None):
        seen["finishes"].append((run_id, status, stats, error))
        return True

    async def fake_listed(scope, scope_id):
        seen["queries"].append(("listed", scope, scope_id))
        return list(listings)

    async def fake_watched(scope, scope_id):
        seen["queries"].append(("watched", scope, scope_id))
        return list(pairs)

    async def fake_ground():
        if ground_raises:
            raise RuntimeError("provider down")
        seen["grounded"].append(True)

    @asynccontextmanager
    async def fake_build():
        if build_raises:
            raise RuntimeError("mcp down")
        seen["built"].append(True)
        yield ("recheck-agent", "scan-agent")

    async def fake_market(item_id):
        return None

    async def fake_recheck(pass_agent, session_id, row):
        if row["listing_id"] in fail_recheck:
            raise RuntimeError("timeout")
        seen["recheck_units"].append(row["listing_id"])
        tools.run_stats["listings_checked"] += 1
        tools.run_stats["prices_found"] += 1

    slots_used = dict(tracked or {})

    async def fake_count(watch_id):
        return slots_used.get(watch_id, 0)

    async def fake_scan(pass_agent, session_id, row, known_urls, market, tracked_listings):
        if row["watch_id"] in fail_scan:
            raise RuntimeError("timeout")
        seen["scan_units"].append(row["watch_id"])
        seen["scan_tracked"].append(tracked_listings)
        slots_used[row["watch_id"]] = tracked_listings + 1
        tools.run_stats["new_listings"] += 1

    monkeypatch.setattr(agent, "claim_queued_run", fake_claim)
    monkeypatch.setattr(agent, "claim_due_schedule", fake_claim_schedule)
    monkeypatch.setattr(agent, "create_global_run", fake_create_global)
    monkeypatch.setattr(agent, "get_run_status", fake_status)
    monkeypatch.setattr(agent, "append_run_event", fake_append)
    monkeypatch.setattr(agent, "finish_run", fake_finish)
    monkeypatch.setattr(agent, "get_listed_items", fake_listed)
    monkeypatch.setattr(agent, "get_watched_item_list", fake_watched)
    monkeypatch.setattr(agent, "ground_stale", fake_ground)
    monkeypatch.setattr(agent, "build_pass_agents", fake_build)
    monkeypatch.setattr(agent, "get_market_price", fake_market)
    monkeypatch.setattr(agent, "get_active_listing_count", fake_count)
    monkeypatch.setattr(agent, "recheck_listing", fake_recheck)
    monkeypatch.setattr(agent, "scan_pair", fake_scan)
    return seen


class TestConsumeTick:
    def test_an_empty_queue_is_a_noop(self, monkeypatch):
        seen = wire(monkeypatch, claim=None)
        asyncio.run(agent.consume())
        assert seen["built"] == []
        assert seen["events"] == []
        assert seen["finishes"] == []

    def test_a_claimed_run_finishes_succeeded_with_the_tally(self, monkeypatch):
        seen = wire(
            monkeypatch,
            claim=run_row(run_id=7),
            listings=[listing_row(1), listing_row(2)],
            pairs=[pair_row(1)],
        )
        asyncio.run(agent.consume())
        assert seen["recheck_units"] == [1, 2]
        assert seen["scan_units"] == [1]
        assert seen["finishes"] == [
            (
                7,
                "succeeded",
                {"listings_checked": 2, "prices_found": 2, "new_listings": 1, "errors": 0},
                None,
            )
        ]

    def test_an_orchestration_failure_marks_the_run_failed_and_reraises(self, monkeypatch):
        seen = wire(monkeypatch, claim=run_row(run_id=7), build_raises=True)
        with pytest.raises(RuntimeError, match="mcp down"):
            asyncio.run(agent.consume())
        assert seen["finishes"] == [(7, "failed", None, "mcp down")]


class TestScopeHandling:
    def test_scope_and_scope_id_reach_both_query_helpers(self, monkeypatch):
        seen = wire(monkeypatch, claim=run_row(scope="item", scope_id=5, label="Item: Alpha"))
        asyncio.run(agent.consume())
        assert seen["queries"] == [("listed", "item", 5), ("watched", "item", 5)]

    def test_scoped_runs_skip_the_grounding_pre_pass(self, monkeypatch):
        seen = wire(monkeypatch, claim=run_row(scope="item", scope_id=5, label="Item: Alpha"))
        asyncio.run(agent.consume())
        assert seen["grounded"] == []

    def test_global_runs_ground_first_and_a_grounding_failure_never_blocks(self, monkeypatch):
        seen = wire(monkeypatch, claim=run_row(), ground_raises=True, pairs=[pair_row(1)])
        asyncio.run(agent.consume())
        assert seen["scan_units"] == [1]
        assert [f[1] for f in seen["finishes"]] == ["succeeded"]


class TestCancellation:
    def test_cancellation_between_units_stops_without_a_terminal_write(self, monkeypatch):
        # the API's cancel_run already wrote the terminal event — a second
        # write from the agent would clobber it (and collide on uq_run_seq)
        seen = wire(
            monkeypatch,
            claim=run_row(),
            listings=[listing_row(1), listing_row(2)],
            statuses=["running", "cancelled"],
        )
        asyncio.run(agent.consume())
        assert seen["recheck_units"] == [1]
        assert seen["finishes"] == []
        assert "run_finished" not in [e[1] for e in seen["events"]]


class TestUnitFailures:
    def test_a_failing_unit_is_counted_and_logged_then_the_run_continues(self, monkeypatch):
        seen = wire(
            monkeypatch,
            claim=run_row(run_id=7),
            listings=[listing_row(1), listing_row(2)],
            fail_recheck={1},
        )
        asyncio.run(agent.consume())
        assert seen["recheck_units"] == [2]
        assert [e for e in seen["events"] if e[0] == "error"] == [
            ("error", "error", "Recheck failed for listing 1: timeout")
        ]
        ((_, status, stats, _),) = seen["finishes"]
        assert status == "succeeded"
        assert stats["errors"] == 1
        assert stats["listings_checked"] == 1

    def test_a_run_where_every_unit_fails_is_marked_failed(self, monkeypatch):
        seen = wire(
            monkeypatch,
            claim=run_row(run_id=7),
            listings=[listing_row(1)],
            pairs=[pair_row(2)],
            fail_recheck={1},
            fail_scan={2},
        )
        with pytest.raises(RuntimeError, match="every unit failed"):
            asyncio.run(agent.consume())
        ((run_id, status, stats, error),) = seen["finishes"]
        assert (run_id, status, stats) == (7, "failed", None)
        assert "every unit failed (2/2)" in error

    def test_a_run_with_no_units_at_all_still_succeeds(self, monkeypatch):
        # an empty watchlist is not a failure — the all-failed rule needs
        # at least one attempted unit
        seen = wire(monkeypatch, claim=run_row(run_id=7))
        asyncio.run(agent.consume())
        assert [f[1] for f in seen["finishes"]] == ["succeeded"]


class TestSlotBudget:
    """max_listings is one budget per watch across every site and run; the
    orchestrator meters it, because a scan only ever sees its own site."""

    def test_a_full_watch_is_skipped_without_a_scan_or_an_event(self, monkeypatch):
        seen = wire(monkeypatch, claim=run_row(run_id=7), pairs=[pair_row(1)], tracked={1: 3})
        asyncio.run(agent.consume())
        assert seen["scan_units"] == []
        assert "item_started" not in [e[1] for e in seen["events"]]
        ((_, status, stats, _),) = seen["finishes"]
        assert status == "succeeded"
        assert stats["new_listings"] == 0

    def test_an_open_watch_is_scanned_with_its_used_slot_count(self, monkeypatch):
        seen = wire(monkeypatch, claim=run_row(), pairs=[pair_row(1)], tracked={1: 2})
        asyncio.run(agent.consume())
        assert seen["scan_units"] == [1]
        assert seen["scan_tracked"] == [2]

    def test_the_count_is_re_read_before_every_site(self, monkeypatch):
        # one slot left and two sites: the first site fills it, so the second
        # must see a full watch — a count taken once per run would scan both
        seen = wire(
            monkeypatch,
            claim=run_row(),
            pairs=[pair_row(1, site_id=1), pair_row(1, site_id=2)],
            tracked={1: 2},
        )
        asyncio.run(agent.consume())
        assert seen["scan_units"] == [1]
        assert seen["scan_tracked"] == [2]

    def test_a_skipped_pair_is_not_a_unit(self, monkeypatch):
        # the only attempted unit failed; the skip must not count as a success
        # that hides it behind "succeeded with one error"
        seen = wire(
            monkeypatch,
            claim=run_row(run_id=7),
            listings=[listing_row(1)],
            pairs=[pair_row(2)],
            fail_recheck={1},
            tracked={2: 3},
        )
        with pytest.raises(RuntimeError, match="every unit failed"):
            asyncio.run(agent.consume())
        ((_, status, _, error),) = seen["finishes"]
        assert status == "failed"
        assert "every unit failed (1/1)" in error


class TestBrowserFailureDetection:
    """_require_browser_success: a unit whose browsing never worked must raise
    (and so be counted) instead of ending on the model's graceful summary."""

    @staticmethod
    def tool_msg(name, status="success"):
        return ToolMessage(content="### Error\nboom", name=name, tool_call_id="t1", status=status)

    def test_all_browser_calls_failing_raises(self):
        msgs = [
            self.tool_msg("browser_navigate", "error"),
            self.tool_msg("browser_snapshot", "error"),
        ]
        with pytest.raises(RuntimeError, match="every browser call failed"):
            agent._require_browser_success(msgs)

    def test_a_partial_browser_failure_is_normal_browsing(self):
        msgs = [self.tool_msg("browser_navigate", "error"), self.tool_msg("browser_navigate")]
        agent._require_browser_success(msgs)

    def test_db_tool_errors_do_not_trigger_it(self):
        msgs = [self.tool_msg("save_price_check", "error"), self.tool_msg("browser_navigate")]
        agent._require_browser_success(msgs)

    def test_a_unit_with_no_browser_calls_passes(self):
        agent._require_browser_success([])

    def test_a_unit_whose_stream_ends_on_all_errors_raises_from_the_worker(self, monkeypatch):
        # end-to-end through recheck_listing: the guard runs on the final
        # transcript, so the orchestrator counts the unit as failed
        class FakeAgent:
            def __init__(self, messages):
                self._messages = messages

            async def astream(self, _input, config=None, stream_mode=None):
                yield {"messages": self._messages}

        async def fake_prompt(**kwargs):
            return "prompt"

        monkeypatch.setattr(agent, "generate_recheck_prompt", fake_prompt)
        row = {
            "listing_id": 1,
            "listing_url": "https://example.test/l1",
            "watch_id": 1,
            "user_id": 1,
            "site_id": 1,
            "site_name": "TestBay",
            "item_id": 1,
            "item_name": "Item 1",
        }
        msgs = [self.tool_msg("browser_navigate", "error")]
        with pytest.raises(RuntimeError, match="every browser call failed"):
            asyncio.run(agent.recheck_listing(FakeAgent(msgs), "sess", row))


class TestProgressEvents:
    def test_progress_events_bracket_the_run(self, monkeypatch):
        seen = wire(monkeypatch, claim=run_row(), pairs=[pair_row(1), pair_row(2)])
        asyncio.run(agent.consume())
        assert seen["events"][0] == ("info", "run_started", "Run started — Everything")
        assert [e[1] for e in seen["events"][1:]] == ["item_started", "item_started"]
        # the terminal run_finished event belongs to finish_run, not execute_run
        assert "run_finished" not in [e[1] for e in seen["events"]]


class TestStatsTally:
    def test_a_stale_tally_never_leaks_into_a_new_run(self, monkeypatch):
        tools.run_stats.update(
            {"listings_checked": 9, "prices_found": 9, "new_listings": 9, "errors": 9}
        )
        seen = wire(monkeypatch, claim=run_row(run_id=7))
        asyncio.run(agent.consume())
        assert seen["finishes"] == [
            (
                7,
                "succeeded",
                {"listings_checked": 0, "prices_found": 0, "new_listings": 0, "errors": 0},
                None,
            )
        ]


class TestNightlySweep:
    def test_the_nightly_sweep_records_its_own_global_run(self, monkeypatch):
        seen = wire(monkeypatch, listings=[listing_row(1)])
        asyncio.run(agent.run())
        assert seen["created"] == [True]
        assert seen["queries"] == [("listed", "global", None), ("watched", "global", None)]
        assert [f[1] for f in seen["finishes"]] == ["succeeded"]


class TestScheduledRuns:
    def test_a_queued_run_beats_a_due_schedule(self, monkeypatch):
        seen = wire(monkeypatch, claim=run_row(run_id=7), claim_schedule=schedule_row(run_id=9))
        asyncio.run(agent.consume())
        assert [f[0] for f in seen["finishes"]] == [7]
        assert seen["schedule_claims"] == []  # queue hit — the schedule is never consulted

    def test_a_due_schedule_fires_when_the_queue_is_empty(self, monkeypatch):
        seen = wire(
            monkeypatch,
            claim=None,
            claim_schedule=schedule_row(run_id=9, scope="site", scope_id=3, label="Site: GameBay"),
        )
        asyncio.run(agent.consume())
        assert seen["queries"] == [("listed", "site", 3), ("watched", "site", 3)]
        assert [f[:2] for f in seen["finishes"]] == [(9, "succeeded")]

    def test_an_idle_tick_with_nothing_due_is_a_noop(self, monkeypatch):
        seen = wire(monkeypatch, claim=None, claim_schedule=None)
        asyncio.run(agent.consume())
        assert seen["schedule_claims"] == [True]  # consulted, empty
        assert seen["built"] == []
        assert seen["events"] == []
        assert seen["finishes"] == []

    def test_a_scheduled_runs_start_event_carries_the_marker(self, monkeypatch):
        seen = wire(
            monkeypatch,
            claim_schedule=schedule_row(run_id=9, scope="site", scope_id=3, label="Site: GameBay"),
        )
        asyncio.run(agent.consume())
        assert seen["events"][0] == (
            "info",
            "run_started",
            "Run started — Site: GameBay (scheduled)",
        )


class TestRollForward:
    NOW = datetime(2026, 8, 14, 10, 5, tzinfo=UTC)

    def test_barely_overdue_steps_exactly_once(self):
        due = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
        assert roll_forward(due, 60, self.NOW) == datetime(2026, 8, 14, 11, 0, tzinfo=UTC)

    def test_downtime_collapses_to_the_first_future_boundary(self):
        # Monday 02:00 due, daily, woken Thursday 13:37 → Friday 02:00: the
        # 02:00 anchor survives and the missed days never re-fire
        due = datetime(2026, 8, 10, 2, 0, tzinfo=UTC)
        now = datetime(2026, 8, 13, 13, 37, tzinfo=UTC)
        assert roll_forward(due, 1440, now) == datetime(2026, 8, 14, 2, 0, tzinfo=UTC)

    def test_a_boundary_now_rolls_strictly_past_it(self):
        due = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
        now = datetime(2026, 8, 14, 11, 0, tzinfo=UTC)  # exactly due + interval
        assert roll_forward(due, 60, now) == datetime(2026, 8, 14, 12, 0, tzinfo=UTC)

    def test_now_equal_to_due_steps_once(self):
        due = datetime(2026, 8, 14, 10, 0, tzinfo=UTC)
        assert roll_forward(due, 60, due) == datetime(2026, 8, 14, 11, 0, tzinfo=UTC)

    def test_a_future_due_time_still_steps_once(self):
        # defensive: a mis-seeded future due_at must not roll backwards
        due = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
        assert roll_forward(due, 60, self.NOW) == datetime(2026, 8, 15, 11, 0, tzinfo=UTC)

    def test_an_every_minute_interval_steps_correctly(self):
        due = datetime(2026, 8, 14, 10, 4, tzinfo=UTC)
        assert roll_forward(due, 1, self.NOW) == datetime(2026, 8, 14, 10, 6, tzinfo=UTC)
