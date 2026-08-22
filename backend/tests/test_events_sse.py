"""The SSE pipeline: migration 007's pg_notify triggers, the hub in
services/events.py, and GET /api/events — including one end-to-end pass
(SQL insert -> trigger -> LISTEN -> broadcast) and the per-viewer filtering
matrix (run envelopes gated by run_visible, run.event by event_visible,
per-client snapshots).

The wire format is pinned by mocks/sse.ts; handlers.ts has no SSE cases, so
auth mirrors the closest normal endpoint (401 unauthenticated envelope).
"""

import asyncio
import json
import os
from datetime import UTC, datetime

import asyncpg
import pytest
from app.config import settings
from app.database import _sessionmaker
from app.models import AgentRuns, RunEvents, User
from app.services import events as events_service

from tests.conftest import CSRF
from tests.factories import Scenario

OWNER = {"email": "sse@example.com", "password": "hunter2hunter2"}

# conftest already rewrote this to the snagr_test URL; asyncpg wants no driver tag
DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")

NOW = datetime.now(UTC)


def _run(**overrides) -> AgentRuns:
    fields = {
        "scope": "global",
        "scope_id": None,
        "scope_label": "Everything",
        "status": "running",
        "started_at": NOW,
        **overrides,
    }
    return AgentRuns(**fields)


def _event(run_id: int, seq: int = 1, **overrides) -> RunEvents:
    fields = {
        "run_id": run_id,
        "seq": seq,
        "ts": NOW,
        "level": "info",
        "event_type": "listing_check",
        "message": "Checking TestBay…",
        "payload": None,
        **overrides,
    }
    return RunEvents(**fields)


async def _seed(*rows) -> list[int]:
    async with _sessionmaker()() as session:
        session.add_all(rows)
        await session.commit()
        return [r.id for r in rows]


@pytest.fixture
async def listen():
    """A raw LISTEN connection on the notify channel; yields a queue of payloads."""
    conn = await asyncpg.connect(DSN)
    notifications: asyncio.Queue[str] = asyncio.Queue()
    await conn.add_listener(events_service.CHANNEL, lambda *args: notifications.put_nowait(args[3]))
    yield notifications
    await conn.close()


def _viewer(user_id: int, role: str = "user") -> User:
    """A detached User stub carrying just what register_client reads."""
    return User(id=user_id, email=f"viewer{user_id}@hub.local", role=role)


@pytest.fixture
def mailbox():
    """A registered hub client queue (admin viewer — sees everything, like the
    pre-privacy hub), unregistered afterwards."""
    client = events_service.register_client(_viewer(999, role="admin"))
    yield client.queue
    events_service.unregister_client(client)


async def _next(queue: asyncio.Queue, timeout: float = 5.0):
    return await asyncio.wait_for(queue.get(), timeout)


class TestNotifyTriggers:
    """Migration 007's DDL (mirrored in conftest): every write announces itself."""

    async def test_inserting_a_run_announces_its_status(self, listen):
        (run_id,) = await _seed(_run())
        note = json.loads(await _next(listen))
        assert note == {"kind": "status", "run_id": run_id, "status": "running"}

    async def test_inserting_a_run_event_announces_run_and_seq(self, listen):
        (run_id,) = await _seed(_run())
        await _next(listen)  # the insert's own status announcement
        await _seed(_event(run_id, seq=7))
        note = json.loads(await _next(listen))
        assert note == {"kind": "event", "run_id": run_id, "seq": 7}

    async def test_a_status_change_announces_once(self, listen):
        (run_id,) = await _seed(_run())
        await _next(listen)
        async with _sessionmaker()() as session:
            run = await session.get(AgentRuns, run_id)
            run.status = "succeeded"
            run.finished_at = NOW
            await session.commit()
        note = json.loads(await _next(listen))
        assert note == {"kind": "status", "run_id": run_id, "status": "succeeded"}

    async def test_a_write_without_status_change_stays_silent(self, listen):
        (run_id,) = await _seed(_run())
        await _next(listen)
        async with _sessionmaker()() as session:
            run = await session.get(AgentRuns, run_id)
            run.last_seq = 42  # the agent bumps this constantly mid-run
            await session.commit()
        with pytest.raises(TimeoutError):
            await _next(listen, timeout=0.5)


class TestHub:
    async def test_broadcast_reaches_every_registered_client(self):
        a = events_service.register_client(_viewer(1))
        b = events_service.register_client(_viewer(2))
        try:
            events_service.broadcast({"event": "run.event", "data": "{}"})
            assert (await _next(a.queue))["event"] == "run.event"
            assert (await _next(b.queue))["event"] == "run.event"
        finally:
            events_service.unregister_client(a)
            events_service.unregister_client(b)

    async def test_an_unregistered_client_stops_receiving(self):
        client = events_service.register_client(_viewer(1))
        events_service.unregister_client(client)
        events_service.broadcast({"event": "run.event", "data": "{}"})
        assert client.queue.empty()

    async def test_snapshot_lists_only_active_runs(self):
        await _seed(
            _run(status="succeeded", finished_at=NOW),
            _run(status="running", scope_label="Site: TestBay"),
            _run(status="queued", started_at=None),
        )
        message = await events_service.snapshot_message(1, False)
        assert message["event"] == "run.snapshot"
        active = json.loads(message["data"])["active_runs"]
        assert [r["status"] for r in active] == ["running", "queued"]
        # the exact subset mocks/sse.ts sends — the client casts it to AgentRun
        assert set(active[0]) == {"id", "user_id", "status", "scope", "scope_label", "last_seq"}
        assert active[0]["scope_label"] == "Site: TestBay"

    async def test_an_event_notification_broadcasts_the_row(self, mailbox):
        (run_id,) = await _seed(_run())
        await _seed(_event(run_id, seq=3, message="Found it"))
        payload = json.dumps({"kind": "event", "run_id": run_id, "seq": 3})
        await events_service._handle_notification(payload)
        message = await _next(mailbox)
        assert message["event"] == "run.event"
        assert message["id"] == f"{run_id}:3"
        event = json.loads(message["data"])
        assert event["message"] == "Found it"
        assert event["seq"] == 3

    @pytest.mark.parametrize(
        ("status", "expected"),
        [("running", "run.started"), ("succeeded", "run.finished"), ("failed", "run.failed")],
    )
    async def test_status_notifications_map_to_lifecycle_events(self, mailbox, status, expected):
        (run_id,) = await _seed(_run(status=status))
        payload = json.dumps({"kind": "status", "run_id": run_id, "status": status})
        await events_service._handle_notification(payload)
        message = await _next(mailbox)
        assert message["event"] == expected
        assert json.loads(message["data"])["run"]["id"] == run_id

    async def test_a_queued_birth_is_not_broadcast(self, mailbox):
        # the POST /api/runs response carries the queued run; mocks/sse.ts sends nothing
        (run_id,) = await _seed(_run(status="queued", started_at=None))
        payload = json.dumps({"kind": "status", "run_id": run_id, "status": "queued"})
        await events_service._handle_notification(payload)
        assert mailbox.empty()

    async def test_a_notification_for_a_missing_row_is_survivable(self, mailbox):
        # log-and-continue: a dead hub is worse than a dropped message
        await events_service._handle_notification(
            json.dumps({"kind": "event", "run_id": 999, "seq": 1})
        )
        assert mailbox.empty()


class _SseConnection:
    """A hand-driven ASGI connection to GET /api/events.

    httpx's ASGITransport runs the app to completion and buffers the whole
    body before returning — which never happens for an endless SSE stream —
    so these tests speak ASGI to the app directly, in the test's own loop.
    """

    def __init__(self, cookies: dict[str, str]):
        from app.main import app

        self._app = app
        cookie = "; ".join(f"{name}={value}" for name, value in cookies.items())
        self._scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/events",
            "raw_path": b"/api/events",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"test"), (b"cookie", cookie.encode())],
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
        }
        self._incoming: asyncio.Queue[dict] = asyncio.Queue()
        self._disconnected: asyncio.Future[dict] = asyncio.get_event_loop().create_future()
        self._buffer = ""

    async def _receive(self) -> dict:
        return await asyncio.shield(self._disconnected)

    async def _send(self, message: dict) -> None:
        self._incoming.put_nowait(message)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._app(self._scope, self._receive, self._send))
        head = await asyncio.wait_for(self._incoming.get(), 5)
        assert head["type"] == "http.response.start"
        self.status = head["status"]
        self.headers = {k.decode(): v.decode() for k, v in head["headers"]}

    async def next_event(self, timeout: float = 5.0) -> dict:
        """The next SSE event on the wire, skipping keep-alive comments."""
        while True:
            if "\n\n" in self._buffer:
                block, self._buffer = self._buffer.split("\n\n", 1)
                fields = {}
                for line in block.splitlines():
                    if line and not line.startswith(":"):
                        key, _, value = line.partition(": ")
                        fields[key] = value
                if fields:
                    return fields
                continue  # a ping comment block
            message = await asyncio.wait_for(self._incoming.get(), timeout)
            if message["type"] == "http.response.body":
                self._buffer += message["body"].decode().replace("\r\n", "\n")

    async def disconnect(self) -> None:
        self._disconnected.set_result({"type": "http.disconnect"})
        await asyncio.wait_for(self._task, 5)


class TestStreamEndpoint:
    async def test_requires_auth(self, client):
        res = await client.get("/api/events")
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "unauthenticated"

    async def test_snapshot_then_live_events(self, client):
        res = await client.post("/api/auth/register", json=OWNER, headers=CSRF)
        assert res.status_code == 201, res.text
        await _seed(_run(scope_label="Site: TestBay"))

        conn = _SseConnection(dict(client.cookies))
        await conn.start()
        try:
            assert conn.status == 200
            assert conn.headers["content-type"].startswith("text/event-stream")

            first = await conn.next_event()
            assert first["event"] == "run.snapshot"
            assert json.loads(first["data"])["active_runs"][0]["scope_label"] == "Site: TestBay"

            events_service.broadcast({"event": "run.event", "data": "{}", "id": "1:1"})
            second = await conn.next_event()
            assert second["event"] == "run.event"
            assert second["id"] == "1:1"
        finally:
            await conn.disconnect()

    async def test_disconnect_unregisters_the_client(self, client):
        await client.post("/api/auth/register", json=OWNER, headers=CSRF)
        before = len(events_service._clients)

        conn = _SseConnection(dict(client.cookies))
        await conn.start()
        await conn.next_event()  # snapshot — the stream is fully up
        assert len(events_service._clients) == before + 1

        await conn.disconnect()
        assert len(events_service._clients) == before


# --- per-viewer filtering -------------------------------------------------------


async def _privacy_fixture() -> dict:
    """Users A and B, a watch each, one item BOTH watch, and A's listing —
    the ownership graph the event predicate keys on. Returns the ids."""
    async with _sessionmaker()() as session:
        sc = Scenario(session)
        a = User(email="a@hub.local")
        b = User(email="b@hub.local")
        session.add_all([a, b])
        await session.flush()
        item_a = await sc.item("Alpha")
        item_b = await sc.item("Beta")
        shared = await sc.item("Shared")
        watch_a = await sc.watch(item_a, user=a)
        await sc.watch(item_b, user=b)
        await sc.watch(shared, user=a)
        await sc.watch(shared, user=b)
        listing_a = await sc.listing(watch_a, item_a)
        ids = {
            "a": a.id,
            "b": b.id,
            "item_a": item_a.id,
            "item_b": item_b.id,
            "shared": shared.id,
            "listing_a": listing_a.id,
        }
        await session.commit()
    return ids


class TestPerViewerFiltering:
    """run.event frames pass run_visible AND event_visible per client; the
    lifecycle envelopes and snapshots pass run_visible — same predicate as
    the REST surface (services/runs.py), asserted here on the push channel."""

    @pytest.fixture
    async def graph(self):
        ids = await _privacy_fixture()
        clients = {
            "a": events_service.register_client(_viewer(ids["a"])),
            "b": events_service.register_client(_viewer(ids["b"])),
            "admin": events_service.register_client(_viewer(999, role="admin")),
        }
        yield ids, clients
        for client in clients.values():
            events_service.unregister_client(client)

    async def _notify_event(self, run_id: int, seq: int) -> None:
        payload = json.dumps({"kind": "event", "run_id": run_id, "seq": seq})
        await events_service._handle_notification(payload)

    async def test_item_events_reach_watchers_and_admin_only(self, graph):
        ids, clients = graph
        (run_id,) = await _seed(_run())  # system run: everyone sees the run itself
        await _seed(_event(run_id, seq=1, payload={"item_id": ids["item_a"]}))
        await self._notify_event(run_id, 1)
        assert (await _next(clients["a"].queue))["event"] == "run.event"
        assert clients["b"].queue.empty()
        assert (await _next(clients["admin"].queue))["event"] == "run.event"

    async def test_a_shared_item_event_reaches_both_watchers(self, graph):
        ids, clients = graph
        (run_id,) = await _seed(_run())
        await _seed(_event(run_id, seq=1, payload={"item_id": ids["shared"]}))
        await self._notify_event(run_id, 1)
        assert (await _next(clients["a"].queue))["event"] == "run.event"
        assert (await _next(clients["b"].queue))["event"] == "run.event"

    async def test_a_listing_event_reaches_only_its_owner(self, graph):
        ids, clients = graph
        (run_id,) = await _seed(_run())
        await _seed(_event(run_id, seq=1, payload={"listing_id": ids["listing_a"]}))
        await self._notify_event(run_id, 1)
        assert (await _next(clients["a"].queue))["event"] == "run.event"
        assert clients["b"].queue.empty()
        assert (await _next(clients["admin"].queue))["event"] == "run.event"

    async def test_a_neutral_event_reaches_every_viewer_of_the_run(self, graph):
        ids, clients = graph
        (run_id,) = await _seed(_run())
        await _seed(_event(run_id, seq=1, payload=None))
        await self._notify_event(run_id, 1)
        for client in clients.values():
            assert (await _next(client.queue))["event"] == "run.event"

    async def test_a_hidden_runs_events_never_stream(self, graph):
        # A's own run names the item B ALSO watches — the run gate wins:
        # B gets nothing, on the push channel exactly as on REST
        ids, clients = graph
        (run_id,) = await _seed(_run(user_id=ids["a"]))
        await _seed(_event(run_id, seq=1, payload={"item_id": ids["shared"]}))
        await self._notify_event(run_id, 1)
        assert (await _next(clients["a"].queue))["event"] == "run.event"
        assert clients["b"].queue.empty()
        assert (await _next(clients["admin"].queue))["event"] == "run.event"

    async def test_lifecycle_envelopes_are_gated_by_run_visibility(self, graph):
        ids, clients = graph
        (run_id,) = await _seed(_run(user_id=ids["a"]))
        payload = json.dumps({"kind": "status", "run_id": run_id, "status": "running"})
        await events_service._handle_notification(payload)
        assert (await _next(clients["a"].queue))["event"] == "run.started"
        assert clients["b"].queue.empty()
        assert (await _next(clients["admin"].queue))["event"] == "run.started"

    async def test_snapshots_are_per_viewer(self, graph):
        ids, _ = graph
        await _seed(_run(scope_label="system sweep"), _run(user_id=ids["a"], scope_label="A's run"))

        a_runs = json.loads((await events_service.snapshot_message(ids["a"], False))["data"])
        assert [r["scope_label"] for r in a_runs["active_runs"]] == ["system sweep", "A's run"]

        b_runs = json.loads((await events_service.snapshot_message(ids["b"], False))["data"])
        assert [r["scope_label"] for r in b_runs["active_runs"]] == ["system sweep"]

        admin_runs = json.loads((await events_service.snapshot_message(999, True))["data"])
        assert len(admin_runs["active_runs"]) == 2


class TestFilteredReconvergence:
    async def test_filtered_viewer_converges_via_authoritative_backfill(
        self, client, make_client, monkeypatch
    ):
        """D-P5 end to end: a filtered viewer reconnects mid-system-run, sees
        the global last_seq in their snapshot, refetches the backfill, gets
        exactly their visible subset, keeps streaming filtered live events —
        and a repeat backfill from their max visible seq returns nothing new
        (convergence, no spinning)."""
        monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
        await client.post("/api/auth/register", json=OWNER, headers=CSRF)
        b_client = await make_client()
        res = await b_client.post(
            "/api/auth/register",
            json={"email": "b@example.com", "password": "hunter2hunter2"},
            headers=CSRF,
        )
        b_id = res.json()["user"]["id"]

        async with _sessionmaker()() as session:
            sc = Scenario(session)
            b = await session.get(User, b_id)
            item_b = await sc.item("Beta")
            other = await sc.item("Alpha")
            await sc.watch(item_b, user=b)
            run = await sc.run(status="running", started_at=sc.now, days_ago=0)
            await sc.run_event(run, 1, message="Run started", event_type="run_started")
            await sc.run_event(run, 2, payload={"item_id": other.id})
            await sc.run_event(run, 3, payload={"item_id": item_b.id})
            run_id, item_b_id = run.id, item_b.id
            await sc.commit()

        conn = _SseConnection(dict(b_client.cookies))
        await conn.start()
        try:
            first = await conn.next_event()
            assert first["event"] == "run.snapshot"
            (entry,) = json.loads(first["data"])["active_runs"]
            assert entry["id"] == run_id
            assert entry["last_seq"] == 3  # the GLOBAL cursor — metadata, never compared

            # the authoritative backfill: exactly B's visible subset
            res = await b_client.get(f"/api/runs/{run_id}/events?after_seq=0")
            assert [e["seq"] for e in res.json()["data"]] == [1, 3]

            # live continuation stays filtered by the same predicate
            await _seed(_event(run_id, seq=4, payload={"item_id": item_b_id}))
            await events_service._handle_notification(
                json.dumps({"kind": "event", "run_id": run_id, "seq": 4})
            )
            frame = await conn.next_event()
            assert frame["event"] == "run.event"
            assert json.loads(frame["data"])["seq"] == 4

            # convergence: from B's max visible seq there is nothing left
            res = await b_client.get(f"/api/runs/{run_id}/events?after_seq=4")
            assert res.json()["data"] == []
        finally:
            await conn.disconnect()


class TestEndToEnd:
    async def test_a_committed_insert_reaches_a_hub_client(self, mailbox):
        """SQL insert -> trigger NOTIFY -> listen_pg -> broadcast, nothing mocked."""
        listener = asyncio.create_task(events_service.listen_pg())
        try:
            # connected once the on-connect snapshot lands
            message = await _next(mailbox)
            assert message["event"] == "run.snapshot"

            (run_id,) = await _seed(_run())
            message = await _next(mailbox)
            assert message["event"] == "run.started"

            await _seed(_event(run_id, seq=1, message="Checking TestBay…"))
            message = await _next(mailbox)
            assert message["event"] == "run.event"
            assert message["id"] == f"{run_id}:1"
            assert json.loads(message["data"])["message"] == "Checking TestBay…"
        finally:
            listener.cancel()
            with pytest.raises(asyncio.CancelledError):
                await listener
