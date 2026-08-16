"""The run-queue consumer orchestration (agent.consume / agent.run /
agent.execute_run) with every seam monkeypatched: DB helpers, the grounding
pre-pass, the MCP/LLM agent builder, and the two per-unit workers. What's
under test is the lifecycle — claim, scope, events, stats, cooperative
cancellation, terminal writes — not SQL (that's test_run_queue_db.py) and
not the LLM."""

import asyncio

import pytest
import tools

import agent


def run_row(run_id=1, scope="global", scope_id=None, label="Everything"):
    return {"id": run_id, "scope": scope, "scope_id": scope_id, "scope_label": label}


def listing_row(n):
    """A pass-1 row with only the keys the orchestrator itself reads."""
    return {"listing_id": n, "listing_url": f"https://example.test/l{n}"}


def pair_row(n):
    """A pass-2 row with only the keys the orchestrator itself reads."""
    return {
        "watch_id": n,
        "item_id": n,
        "item_name": f"Item {n}",
        "site_id": 1,
        "site_name": "TestBay",
    }


def wire(
    monkeypatch,
    *,
    claim=None,
    listings=(),
    pairs=(),
    statuses=None,
    fail_recheck=(),
    fail_scan=(),
    ground_raises=False,
    build_raises=False,
):
    """Point every seam at in-memory fakes; returns what the fakes saw.

    `statuses` scripts get_run_status answers in order, repeating the last one
    (default: forever "running"). Successful fake units bump tools.run_stats
    the way the real DB tools would.
    """
    seen = {
        "created": [],
        "queries": [],
        "events": [],
        "finishes": [],
        "recheck_units": [],
        "scan_units": [],
        "grounded": [],
        "built": [],
    }
    status_script = list(statuses or ["running"])

    async def fake_claim():
        return dict(claim) if claim else None

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

    async def fake_build():
        if build_raises:
            raise RuntimeError("mcp down")
        seen["built"].append(True)
        return ("recheck-agent", "scan-agent")

    async def fake_market(item_id):
        return None

    async def fake_recheck(pass_agent, session_id, row):
        if row["listing_id"] in fail_recheck:
            raise RuntimeError("timeout")
        seen["recheck_units"].append(row["listing_id"])
        tools.run_stats["listings_checked"] += 1
        tools.run_stats["prices_found"] += 1

    async def fake_scan(pass_agent, session_id, row, known_urls, market):
        if row["watch_id"] in fail_scan:
            raise RuntimeError("timeout")
        seen["scan_units"].append(row["watch_id"])
        tools.run_stats["new_listings"] += 1

    monkeypatch.setattr(agent, "claim_queued_run", fake_claim)
    monkeypatch.setattr(agent, "create_global_run", fake_create_global)
    monkeypatch.setattr(agent, "get_run_status", fake_status)
    monkeypatch.setattr(agent, "append_run_event", fake_append)
    monkeypatch.setattr(agent, "finish_run", fake_finish)
    monkeypatch.setattr(agent, "get_listed_items", fake_listed)
    monkeypatch.setattr(agent, "get_watched_item_list", fake_watched)
    monkeypatch.setattr(agent, "ground_stale", fake_ground)
    monkeypatch.setattr(agent, "build_pass_agents", fake_build)
    monkeypatch.setattr(agent, "get_market_price", fake_market)
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
