"""HTTP layer for /api/runs — everything except triggerRun (still a loud stub).

Run history is instance-wide (agent_runs has no user_id): any signed-in user
sees the same rows, so there are no ownership tests here — just auth, filters,
ordering, pagination, and the serialized shape.

Seeding COMMITS through `db_session` because each request runs on its own
session. Runs hang off nothing (no user/item graph), so rows are inserted
directly instead of via Scenario.
"""

from datetime import UTC, datetime, timedelta

from app.models import AgentRuns, RunEvents

from tests.conftest import CSRF

OWNER = {"email": "runs@example.com", "password": "hunter2hunter2"}

NOW = datetime.now(UTC)


async def _sign_in(client, creds=OWNER):
    res = await client.post("/api/auth/register", json=creds, headers=CSRF)
    assert res.status_code == 201, res.text


def _run(days_ago: float, **overrides) -> AgentRuns:
    """A finished-looking run `days_ago` days back; override any column."""
    fields = {
        "scope": "global",
        "scope_id": None,
        "scope_label": "Everything",
        "status": "succeeded",
        "created_at": NOW - timedelta(days=days_ago),
        **overrides,
    }
    return AgentRuns(**fields)


def _event(run_id: int, seq: int, **overrides) -> RunEvents:
    """An event `seq` steps into a run's log; ts climbs with seq so time agrees."""
    fields = {
        "run_id": run_id,
        "seq": seq,
        "ts": NOW - timedelta(seconds=100 - seq),
        "level": "info",
        "event_type": "listing_check",
        "message": f"event {seq}",
        "payload": None,
        **overrides,
    }
    return RunEvents(**fields)


async def _seed(db_session, *rows) -> list[int]:
    """Insert any model rows; returns their ids (captured before commit expires them)."""
    async with db_session() as session:
        session.add_all(rows)
        await session.flush()
        ids = [row.id for row in rows]
        await session.commit()
    return ids


# --- authentication -----------------------------------------------------------


async def test_list_runs_requires_a_session(client):
    res = await client.get("/api/runs")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


# --- envelope + shape -----------------------------------------------------------


async def test_no_history_is_an_empty_page(client):
    await _sign_in(client)
    res = await client.get("/api/runs")
    assert res.status_code == 200
    assert res.json() == {"data": [], "meta": {"page": 1, "per_page": 25, "total": 0}}


async def test_runs_serialize_every_field(client, db_session):
    started = NOW - timedelta(minutes=10)
    finished = NOW - timedelta(minutes=5)
    stats = {"listings_checked": 4, "prices_found": 3, "new_listings": 1, "errors": 0}
    await _seed(
        db_session,
        _run(
            1,
            scope="site",
            scope_id=7,
            scope_label="Site: TestBay",
            status="failed",
            started_at=started,
            finished_at=finished,
            stats=stats,
            error="browser crashed",
            last_seq=42,
        ),
    )
    await _sign_in(client)

    (run,) = (await client.get("/api/runs")).json()["data"]
    assert run == {
        "id": run["id"],
        "scope": "site",
        "scope_id": 7,
        "scope_label": "Site: TestBay",
        "status": "failed",
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "stats": stats,
        "error": "browser crashed",
        "created_at": (NOW - timedelta(days=1)).isoformat(),
        "last_seq": 42,
    }


async def test_queued_run_has_null_progress_fields(client, db_session):
    # a just-enqueued run: nothing started, no stats, seq 0 — nulls, never fakes
    await _seed(db_session, _run(0, status="queued"))
    await _sign_in(client)

    (run,) = (await client.get("/api/runs")).json()["data"]
    assert run["status"] == "queued"
    assert run["started_at"] is None
    assert run["finished_at"] is None
    assert run["stats"] is None
    assert run["error"] is None
    assert run["last_seq"] == 0


# --- ordering + filters ---------------------------------------------------------


async def test_runs_come_back_newest_first(client, db_session):
    await _seed(
        db_session,
        _run(3, scope_label="oldest"),
        _run(1, scope_label="newest"),
        _run(2, scope_label="middle"),
    )
    await _sign_in(client)

    labels = [r["scope_label"] for r in (await client.get("/api/runs")).json()["data"]]
    assert labels == ["newest", "middle", "oldest"]


async def test_status_filter(client, db_session):
    await _seed(db_session, _run(1), _run(2, status="failed"), _run(3))
    await _sign_in(client)

    body = (await client.get("/api/runs?status=failed")).json()
    assert body["meta"]["total"] == 1
    assert [r["status"] for r in body["data"]] == ["failed"]


async def test_scope_filter(client, db_session):
    # handlers.ts never filters on scope, but RunListParams sends it — the
    # backend honors the contract param (gap called out in the router)
    await _seed(db_session, _run(1), _run(2, scope="item", scope_id=5, scope_label="Item: Alpha"))
    await _sign_in(client)

    body = (await client.get("/api/runs?scope=item")).json()
    assert body["meta"]["total"] == 1
    assert [r["scope"] for r in body["data"]] == ["item"]


# --- get_run --------------------------------------------------------------------


async def test_get_run_requires_a_session(client):
    res = await client.get("/api/runs/1")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


async def test_unknown_run_is_404(client):
    await _sign_in(client)
    res = await client.get("/api/runs/99999")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


async def test_get_run_returns_the_serialized_run(client, db_session):
    await _seed(db_session, _run(2, scope_label="wanted"), _run(1, scope_label="decoy"))
    await _sign_in(client)

    runs = (await client.get("/api/runs")).json()["data"]
    wanted_id = next(r["id"] for r in runs if r["scope_label"] == "wanted")

    res = await client.get(f"/api/runs/{wanted_id}")
    assert res.status_code == 200
    run = res.json()
    assert run["id"] == wanted_id
    assert run["scope_label"] == "wanted"
    # same serializer as the list — one deep field proves the shape came through
    assert run["created_at"] == (NOW - timedelta(days=2)).isoformat()


# --- get_run_events -------------------------------------------------------------


async def test_get_run_events_requires_a_session(client):
    res = await client.get("/api/runs/1/events")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


async def test_unknown_run_backfill_is_empty_not_404(client):
    # handlers.ts never 404s here — an unknown run is just an empty backfill
    await _sign_in(client)
    res = await client.get("/api/runs/99999/events")
    assert res.status_code == 200
    assert res.json() == {"data": []}


async def test_events_come_back_in_seq_order_with_full_shape(client, db_session):
    run_id, decoy_id = await _seed(db_session, _run(1), _run(2))
    payload = {"url": "https://example.test/l1", "price": "49.99"}
    await _seed(
        db_session,
        _event(run_id, 2),
        _event(run_id, 1, event_type="run_started", message="run started"),
        _event(run_id, 3, level="success", event_type="price_found", payload=payload),
        _event(decoy_id, 1, message="someone else's run"),
    )
    await _sign_in(client)

    events = (await client.get(f"/api/runs/{run_id}/events")).json()["data"]
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert all(e["run_id"] == run_id for e in events)
    assert events[2] == {
        "run_id": run_id,
        "seq": 3,
        "ts": (NOW - timedelta(seconds=97)).isoformat(),
        "level": "success",
        "event_type": "price_found",
        "message": "event 3",
        "payload": payload,
    }


async def test_after_seq_backfills_only_newer_events(client, db_session):
    (run_id,) = await _seed(db_session, _run(1))
    await _seed(db_session, *[_event(run_id, s) for s in range(1, 6)])
    await _sign_in(client)

    events = (await client.get(f"/api/runs/{run_id}/events?after_seq=3")).json()["data"]
    assert [e["seq"] for e in events] == [4, 5]


async def test_limit_caps_the_backfill(client, db_session):
    (run_id,) = await _seed(db_session, _run(1))
    await _seed(db_session, *[_event(run_id, s) for s in range(1, 6)])
    await _sign_in(client)

    events = (await client.get(f"/api/runs/{run_id}/events?limit=2")).json()["data"]
    # the limit keeps the OLDEST pending events — backfill resumes from after_seq
    assert [e["seq"] for e in events] == [1, 2]


# --- cancel_run -----------------------------------------------------------------


async def test_cancel_requires_the_csrf_header(client):
    res = await client.post("/api/runs/1/cancel")
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "csrf"


async def test_cancel_requires_a_session(client):
    res = await client.post("/api/runs/1/cancel", headers=CSRF)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


async def test_cancel_unknown_run_is_404(client):
    await _sign_in(client)
    res = await client.post("/api/runs/99999/cancel", headers=CSRF)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


async def test_cancel_a_finished_run_is_409(client, db_session):
    (run_id,) = await _seed(db_session, _run(1, status="succeeded"))
    await _sign_in(client)

    res = await client.post(f"/api/runs/{run_id}/cancel", headers=CSRF)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "not_active"


async def test_cancel_a_queued_run(client, db_session):
    (run_id,) = await _seed(db_session, _run(0, status="queued"))
    await _sign_in(client)

    res = await client.post(f"/api/runs/{run_id}/cancel", headers=CSRF)
    assert res.status_code == 200
    run = res.json()
    assert run["status"] == "cancelled"
    assert run["finished_at"] is not None
    assert run["started_at"] is None  # it never ran
    assert run["last_seq"] == 1

    # the terminal event is durable — the backfill endpoint must see it
    (event,) = (await client.get(f"/api/runs/{run_id}/events")).json()["data"]
    assert event["seq"] == 1
    assert event["level"] == "warn"
    assert event["event_type"] == "run_finished"
    assert event["message"] == "Run cancelled"


async def test_cancel_a_running_run_continues_its_event_log(client, db_session):
    started = NOW - timedelta(minutes=5)
    (run_id,) = await _seed(db_session, _run(0, status="running", started_at=started, last_seq=3))
    await _seed(db_session, *[_event(run_id, s) for s in range(1, 4)])
    await _sign_in(client)

    res = await client.post(f"/api/runs/{run_id}/cancel", headers=CSRF)
    assert res.status_code == 200
    run = res.json()
    assert run["status"] == "cancelled"
    assert run["started_at"] == started.isoformat()
    assert run["last_seq"] == 4  # cancel appends, never clobbers, the agent's events

    events = (await client.get(f"/api/runs/{run_id}/events?after_seq=3")).json()["data"]
    assert [e["seq"] for e in events] == [4]
    assert events[0]["event_type"] == "run_finished"


async def test_cancelling_twice_is_409(client, db_session):
    (run_id,) = await _seed(db_session, _run(0, status="queued"))
    await _sign_in(client)

    assert (await client.post(f"/api/runs/{run_id}/cancel", headers=CSRF)).status_code == 200
    res = await client.post(f"/api/runs/{run_id}/cancel", headers=CSRF)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "not_active"


# --- pagination -----------------------------------------------------------------


async def test_pagination_slices_and_reports_total(client, db_session):
    await _seed(db_session, *[_run(d) for d in range(1, 6)])
    await _sign_in(client)

    page2 = (await client.get("/api/runs?page=2&per_page=2")).json()
    assert page2["meta"] == {"page": 2, "per_page": 2, "total": 5}
    assert len(page2["data"]) == 2

    page3 = (await client.get("/api/runs?page=3&per_page=2")).json()
    assert page3["meta"]["total"] == 5
    assert len(page3["data"]) == 1

    # pages don't overlap
    ids = [r["id"] for r in page2["data"]] + [r["id"] for r in page3["data"]]
    assert len(ids) == len(set(ids))
