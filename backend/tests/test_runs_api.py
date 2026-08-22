"""HTTP layer for /api/runs.

Run visibility is per-user (services/runs.py predicate): a viewer sees their
own runs plus system runs (user_id NULL), admins see everything, and a hidden
run 404s exactly like a nonexistent one. The single-actor tests below sign in
ONE user — the first registrant, who is an admin — so they exercise shape,
filters, ordering, and pagination unfiltered; the ownership matrix at the
bottom drives two non-admin users + the admin against the same fixture graph.

Seeding COMMITS through `db_session` because each request runs on its own
session. Ownerless runs hang off nothing, so rows are inserted directly; the
scope-resolution and privacy tests build real graphs via Scenario.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from app.config import settings
from app.models import AgentRuns, RunEvents, User

from tests.conftest import CSRF
from tests.factories import Scenario

OWNER = {"email": "runs@example.com", "password": "hunter2hunter2"}

NOW = datetime.now(UTC)


async def _sign_in(client, creds=OWNER):
    """Register (which also signs in) and return the new user's id."""
    res = await client.post("/api/auth/register", json=creds, headers=CSRF)
    assert res.status_code == 201, res.text
    return res.json()["user"]["id"]


@asynccontextmanager
async def _seed_for(db_session, user_id):
    """Scenario bound to an already-registered user, committed on exit."""
    async with db_session() as session:
        scenario = Scenario(session)
        scenario._user = await session.get(User, user_id)
        yield scenario
        await session.commit()


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
        "user_id": None,
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


# --- trigger_run ----------------------------------------------------------------


async def test_trigger_requires_the_csrf_header(client):
    res = await client.post("/api/runs", json={"scope": "global"})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "csrf"


async def test_trigger_requires_a_session(client):
    res = await client.post("/api/runs", json={"scope": "global"}, headers=CSRF)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


async def test_trigger_global_returns_202_with_a_queued_run(client):
    user_id = await _sign_in(client)

    res = await client.post("/api/runs", json={"scope": "global"}, headers=CSRF)
    assert res.status_code == 202, res.text
    body = res.json()
    assert list(body) == ["run"]
    run = body["run"]
    assert run["user_id"] == user_id  # the caller owns the run they trigger
    assert run["scope"] == "global"
    assert run["scope_id"] is None
    assert run["scope_label"] == "Everything"
    assert run["status"] == "queued"
    assert run["started_at"] is None
    assert run["finished_at"] is None
    assert run["stats"] is None
    assert run["error"] is None
    assert run["last_seq"] == 0

    # the row is durable, not just echoed — the detail endpoint must see it
    persisted = (await client.get(f"/api/runs/{run['id']}")).json()
    assert persisted["status"] == "queued"
    assert persisted["scope_label"] == "Everything"


async def test_trigger_while_a_run_is_running_is_409_with_its_id(client, db_session):
    (active_id,) = await _seed(db_session, _run(0, status="running", started_at=NOW))
    await _sign_in(client)

    res = await client.post("/api/runs", json={"scope": "global"}, headers=CSRF)
    assert res.status_code == 409
    error = res.json()["error"]
    assert error["code"] == "run_in_progress"
    assert error["run_id"] == active_id


async def test_a_queued_run_also_blocks_new_triggers(client, db_session):
    await _seed(db_session, _run(0, status="queued"))
    await _sign_in(client)

    res = await client.post("/api/runs", json={"scope": "global"}, headers=CSRF)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "run_in_progress"


async def test_active_check_wins_over_scope_validation(client, db_session):
    # handlers.ts checks hasActiveRun() before even reading the body — a busy
    # instance answers 409, never 404, no matter how broken the scope is
    await _seed(db_session, _run(0, status="running", started_at=NOW))
    await _sign_in(client)

    res = await client.post(
        "/api/runs", json={"scope": "category", "scope_id": 999999}, headers=CSRF
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "run_in_progress"


async def test_trigger_unknown_category_is_404(client):
    await _sign_in(client)
    res = await client.post(
        "/api/runs", json={"scope": "category", "scope_id": 999999}, headers=CSRF
    )
    assert res.status_code == 404
    error = res.json()["error"]
    assert error["code"] == "not_found"
    assert error["message"] == "Category 999999 does not exist"


async def test_trigger_unknown_site_is_404(client):
    await _sign_in(client)
    res = await client.post("/api/runs", json={"scope": "site", "scope_id": 999999}, headers=CSRF)
    assert res.status_code == 404
    error = res.json()["error"]
    assert error["code"] == "not_found"
    assert error["message"] == "Site 999999 does not exist"


async def test_trigger_unknown_item_is_404(client):
    await _sign_in(client)
    res = await client.post("/api/runs", json={"scope": "item", "scope_id": 999999}, headers=CSRF)
    assert res.status_code == 404
    error = res.json()["error"]
    assert error["code"] == "not_found"
    assert error["message"] == "Item 999999 does not exist"


async def test_scoped_trigger_without_a_scope_id_is_404(client):
    # code only: the mock says "Category undefined does not exist", we say
    # "Category None…" — status + error.code match, the message text can't
    await _sign_in(client)
    res = await client.post("/api/runs", json={"scope": "category"}, headers=CSRF)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


async def test_trigger_category_scope_builds_the_label(client, db_session):
    user_id = await _sign_in(client)
    async with _seed_for(db_session, user_id) as sc:
        category_id = (await sc.category()).id

    res = await client.post(
        "/api/runs", json={"scope": "category", "scope_id": category_id}, headers=CSRF
    )
    assert res.status_code == 202, res.text
    run = res.json()["run"]
    assert run["scope_label"] == "Category: Cameras"
    assert run["scope_id"] == category_id


async def test_trigger_site_scope_builds_the_label(client, db_session):
    user_id = await _sign_in(client)
    async with _seed_for(db_session, user_id) as sc:
        site_id = (await sc.site()).id

    res = await client.post("/api/runs", json={"scope": "site", "scope_id": site_id}, headers=CSRF)
    assert res.status_code == 202, res.text
    assert res.json()["run"]["scope_label"] == "Site: TestBay"


async def test_trigger_item_scope_resolves_the_shared_catalog(client, db_session):
    # scope targets come from the shared catalog, not the caller's watches —
    # an item nobody watches is still a valid target (the run itself is
    # stamped with its creator)
    user_id = await _sign_in(client)
    async with _seed_for(db_session, user_id) as sc:
        item_id = (await sc.item()).id

    res = await client.post("/api/runs", json={"scope": "item", "scope_id": item_id}, headers=CSRF)
    assert res.status_code == 202, res.text
    assert res.json()["run"]["scope_label"] == "Item: Alpha"


async def test_trigger_after_a_finished_run_succeeds(client, db_session):
    # only queued/running block — a full history of terminal runs doesn't
    await _seed(
        db_session,
        _run(3, status="succeeded"),
        _run(2, status="failed"),
        _run(1, status="cancelled"),
    )
    await _sign_in(client)

    res = await client.post("/api/runs", json={"scope": "global"}, headers=CSRF)
    assert res.status_code == 202, res.text


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


async def test_unknown_run_backfill_is_404(client):
    # hidden ≡ nonexistent: a hidden run's backfill must be indistinguishable
    # from an unknown id, so both 404 (handlers.ts changed with this feature)
    await _sign_in(client)
    res = await client.get("/api/runs/99999/events")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


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


# --- ownership / privacy --------------------------------------------------------

A = {"email": "a@example.com", "password": "hunter2hunter2"}
B = {"email": "b@example.com", "password": "hunter2hunter2"}


async def _actors(client, make_client, monkeypatch):
    """`client` signs in as the admin (first registrant); returns two more
    signed-in non-admin clients with their user ids."""
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
    await _sign_in(client)
    a_client = await make_client()
    a_id = await _sign_in(a_client, A)
    b_client = await make_client()
    b_id = await _sign_in(b_client, B)
    return (a_client, a_id), (b_client, b_id)


async def _privacy_graph(db_session, a_id, b_id) -> dict:
    """The predicate's fixture matrix: a run owned by each user plus a system
    run whose log references A's item, A's listing, B's item, B's listing, an
    item BOTH watch, and neutral lifecycle rows. Returns the ids assertions
    key on; the system run's visible seqs are A=[1,2,3,5,7], B=[1,4,5,6,7]."""
    async with db_session() as session:
        sc = Scenario(session)
        a = await session.get(User, a_id)
        b = await session.get(User, b_id)

        item_a = await sc.item("Alpha")
        item_b = await sc.item("Beta")
        shared = await sc.item("Shared")
        watch_a = await sc.watch(item_a, user=a)
        watch_b = await sc.watch(item_b, user=b)
        await sc.watch(shared, user=a)
        await sc.watch(shared, user=b)
        listing_a = await sc.listing(watch_a, item_a)
        listing_b = await sc.listing(watch_b, item_b)

        run_a = await sc.run(
            user=a, days_ago=2, scope="item", scope_id=item_a.id, scope_label="Item: Alpha"
        )
        run_b = await sc.run(user=b, days_ago=3)
        system = await sc.run(days_ago=1)
        await sc.run_event(system, 1, message="Run started", event_type="run_started")
        await sc.run_event(system, 2, payload={"item_id": item_a.id})
        await sc.run_event(
            system, 3, payload={"listing_id": listing_a.id}, level="error", event_type="error"
        )
        await sc.run_event(system, 4, payload={"item_id": item_b.id})
        await sc.run_event(system, 5, payload={"item_id": shared.id})
        await sc.run_event(system, 6, payload={"listing_id": listing_b.id})
        await sc.run_event(system, 7, message="Run complete", event_type="run_finished")
        # run_a's log names the SHARED item — used to prove run-row visibility
        # gates before the event rule (B watches it, but may not see A's run)
        await sc.run_event(run_a, 1, payload={"item_id": shared.id})

        ids = {"run_a": run_a.id, "run_b": run_b.id, "system": system.id}
        await sc.commit()
    return ids


async def test_list_scopes_to_own_plus_system(client, make_client, monkeypatch, db_session):
    (a_client, a_id), (b_client, b_id) = await _actors(client, make_client, monkeypatch)
    ids = await _privacy_graph(db_session, a_id, b_id)

    a_body = (await a_client.get("/api/runs")).json()
    assert a_body["meta"]["total"] == 2  # post-filter, not the table count
    assert {r["id"] for r in a_body["data"]} == {ids["run_a"], ids["system"]}

    b_body = (await b_client.get("/api/runs")).json()
    assert {r["id"] for r in b_body["data"]} == {ids["run_b"], ids["system"]}

    admin_body = (await client.get("/api/runs")).json()
    assert admin_body["meta"]["total"] == 3


async def test_another_users_run_404s_on_every_route(client, make_client, monkeypatch, db_session):
    (_, a_id), (b_client, b_id) = await _actors(client, make_client, monkeypatch)
    ids = await _privacy_graph(db_session, a_id, b_id)

    # detail, backfill, cancel — all not_found, exactly like an unknown id.
    # The backfill case matters doubly: run_a's log references the shared item
    # B watches, and the run gate must win over the event rule.
    for res in (
        await b_client.get(f"/api/runs/{ids['run_a']}"),
        await b_client.get(f"/api/runs/{ids['run_a']}/events"),
        await b_client.post(f"/api/runs/{ids['run_a']}/cancel", headers=CSRF),
    ):
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"


async def test_system_run_backfill_is_filtered_per_viewer(
    client, make_client, monkeypatch, db_session
):
    (a_client, a_id), (b_client, b_id) = await _actors(client, make_client, monkeypatch)
    ids = await _privacy_graph(db_session, a_id, b_id)
    url = f"/api/runs/{ids['system']}/events"

    a_seqs = [e["seq"] for e in (await a_client.get(url)).json()["data"]]
    assert a_seqs == [1, 2, 3, 5, 7]  # lifecycle + own item + own listing + shared item

    b_seqs = [e["seq"] for e in (await b_client.get(url)).json()["data"]]
    assert b_seqs == [1, 4, 5, 6, 7]  # both watchers legitimately see the shared item (5)

    admin_seqs = [e["seq"] for e in (await client.get(url)).json()["data"]]
    assert admin_seqs == [1, 2, 3, 4, 5, 6, 7]


async def test_backfill_filters_before_the_limit(client, make_client, monkeypatch, db_session):
    (a_client, a_id), (_, b_id) = await _actors(client, make_client, monkeypatch)
    ids = await _privacy_graph(db_session, a_id, b_id)

    # A's visible seqs after 2 are [3, 5, 7]; limit counts VISIBLE events, so
    # limit=2 returns [3, 5] — limit-then-filter would have fetched seqs 3-4
    # and returned only [3], stranding the viewer
    res = await a_client.get(f"/api/runs/{ids['system']}/events?after_seq=2&limit=2")
    assert [e["seq"] for e in res.json()["data"]] == [3, 5]


async def test_cancel_ownership_matrix(client, make_client, monkeypatch, db_session):
    (a_client, a_id), (b_client, _) = await _actors(client, make_client, monkeypatch)
    async with db_session() as session:
        sc = Scenario(session)
        a = await session.get(User, a_id)
        own = await sc.run(user=a, status="running", started_at=sc.now)
        active_system = await sc.run(status="running", started_at=sc.now)
        finished_system = await sc.run(status="succeeded")
        own_id, active_id, finished_id = own.id, active_system.id, finished_system.id
        await sc.commit()

    # system runs are admin-cancel-only for non-admins…
    res = await b_client.post(f"/api/runs/{active_id}/cancel", headers=CSRF)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "forbidden"

    # …and permission outranks state: a FINISHED system run is still 403, not 409
    res = await b_client.post(f"/api/runs/{finished_id}/cancel", headers=CSRF)
    assert res.status_code == 403

    # owners cancel their own; admins cancel anything, system runs included
    assert (await a_client.post(f"/api/runs/{own_id}/cancel", headers=CSRF)).status_code == 200
    assert (await client.post(f"/api/runs/{active_id}/cancel", headers=CSRF)).status_code == 200
