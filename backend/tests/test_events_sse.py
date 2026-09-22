"""The SSE pipeline: migration 015's pg_notify triggers, the hub in
services/events.py, and GET /api/events — including one end-to-end pass
(SQL insert -> trigger -> LISTEN -> broadcast) and the per-viewer filtering
matrix (every frame gated by the same predicate the REST surface uses).

Two shapes of frame, because the hunter does two shapes of work: a hunt has a
voice (lifecycle envelopes plus every line of its log) and a recheck has a
pulse (no lifecycle, no events, just the price check it wrote). Both are
asserted here.

The wire format is pinned by mocks/sse.ts; handlers.ts has no SSE cases, so
auth mirrors the closest normal endpoint (401 unauthenticated envelope).
"""

import asyncio
import json
import os
from datetime import UTC, datetime
from decimal import Decimal

import asyncpg
import pytest
from app.database import _sessionmaker
from app.models import JobEvents, Jobs, PriceChecks, User
from app.services import events as events_service

from tests.conftest import CSRF
from tests.factories import Scenario

OWNER = {"email": "sse@example.com", "password": "hunter2hunter2"}

# conftest already rewrote this to the snagr_test URL; asyncpg wants no driver tag
DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")

NOW = datetime.now(UTC)


def _job(**overrides) -> Jobs:
    fields = {
        "kind": "hunt",
        "status": "running",
        "started_at": NOW,
        **overrides,
    }
    return Jobs(**fields)


def _event(job_id: int, seq: int = 1, **overrides) -> JobEvents:
    fields = {
        "job_id": job_id,
        "seq": seq,
        "ts": NOW,
        "level": "info",
        "event_type": "listing_check",
        "message": "Reading https://testbay.example/itm/1",
        "payload": None,
        **overrides,
    }
    return JobEvents(**fields)


async def _seed(*rows) -> list[int]:
    async with _sessionmaker()() as session:
        session.add_all(rows)
        await session.commit()
        return [r.id for r in rows]


@pytest.fixture
async def listen():
    """A raw LISTEN connection on both notify channels; yields a queue of
    (channel, payload) pairs."""
    conn = await asyncpg.connect(DSN)
    notifications: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
    for channel in (events_service.JOBS_CHANNEL, events_service.EVENTS_CHANNEL):
        await conn.add_listener(channel, lambda *a: notifications.put_nowait((a[2], a[3])))
    yield notifications
    await conn.close()


def _viewer(user_id: int, role: str = "user") -> User:
    """A detached User stub carrying just what register_client reads."""
    return User(id=user_id, email=f"viewer{user_id}@hub.local", role=role)


@pytest.fixture
def mailbox():
    """A registered hub client queue (admin viewer — sees everything),
    unregistered afterwards."""
    client = events_service.register_client(_viewer(999, role="admin"))
    yield client.queue
    events_service.unregister_client(client)


async def _next(queue: asyncio.Queue, timeout: float = 5.0):
    return await asyncio.wait_for(queue.get(), timeout)


async def _notify(channel: str, **note) -> None:
    await events_service._handle_notification(channel, json.dumps(note))


class TestNotifyTriggers:
    """Migration 015's DDL (mirrored in conftest): every write announces
    itself, so no writer has to remember to."""

    async def test_inserting_a_job_announces_it(self, listen):
        (job_id,) = await _seed(_job(status="pending", started_at=None))
        channel, payload = await _next(listen)
        assert channel == events_service.JOBS_CHANNEL
        assert json.loads(payload) == {"id": job_id, "kind": "hunt", "status": "pending"}

    async def test_a_status_change_announces_once(self, listen):
        (job_id,) = await _seed(_job())
        await _next(listen)  # the insert's own announcement
        async with _sessionmaker()() as session:
            job = await session.get(Jobs, job_id)
            job.status = "done"
            job.finished_at = NOW
            await session.commit()
        _, payload = await _next(listen)
        assert json.loads(payload) == {"id": job_id, "kind": "hunt", "status": "done"}

    async def test_a_write_without_a_status_change_stays_silent(self, listen):
        (job_id,) = await _seed(_job())
        await _next(listen)
        async with _sessionmaker()() as session:
            job = await session.get(Jobs, job_id)
            job.heartbeat_at = NOW  # the worker stamps this every 30 seconds
            await session.commit()
        with pytest.raises(TimeoutError):
            await _next(listen, timeout=0.5)

    async def test_a_job_event_announces_its_job_and_seq(self, listen):
        (job_id,) = await _seed(_job())
        await _next(listen)
        await _seed(_event(job_id, seq=7))
        channel, payload = await _next(listen)
        assert channel == events_service.EVENTS_CHANNEL
        assert json.loads(payload) == {"job_id": job_id, "seq": 7}

    async def test_a_price_check_announces_itself(self, listen, sc):
        """Whoever wrote it — the deterministic ladder, a static GET or the
        model — one trigger puts it on the page."""
        item = await sc.item()
        listing = await sc.listing(await sc.watch(item), item)
        await sc.commit()
        check = PriceChecks(
            listing_id=listing.id,
            price=Decimal("49.99"),
            currency="USD",
            in_stock=True,
            status="ok",
            method="jsonld",
            checked_at=NOW,
        )
        (check_id,) = await _seed(check)
        channel, payload = await _next(listen)
        assert channel == events_service.EVENTS_CHANNEL
        assert json.loads(payload) == {"check": check_id}


class TestHub:
    async def test_an_unregistered_client_stops_receiving(self, sc):
        watch = await sc.watch(await sc.item())
        job = await sc.job(watch=watch, status="running")
        await sc.commit()
        client = events_service.register_client(_viewer(sc.user_id))
        events_service.unregister_client(client)
        await _notify(events_service.JOBS_CHANNEL, id=job.id)
        assert client.queue.empty()

    async def test_the_snapshot_lists_live_hunts_only(self, sc, mailbox):
        watch = await sc.watch(await sc.item())
        await sc.job(watch=watch, status="done")
        await sc.job(watch=watch, status="running", site_id=(await sc.site("Other")).id)
        await sc.job(kind="ground", watch=None, item_id=watch.item_id, status="pending")
        # a check is live work too, but it has no events and is over in
        # seconds — a client would only ever see it as history
        await sc.job(kind="recheck", watch=watch, status="running")
        await sc.commit()

        message = await events_service.snapshot_message(999, True)
        assert message["event"] == "job.snapshot"
        jobs = json.loads(message["data"])["jobs"]
        assert sorted(j["kind"] for j in jobs) == ["ground", "hunt"]

    async def test_an_event_notification_broadcasts_the_row(self, sc, mailbox):
        watch = await sc.watch(await sc.item())
        job = await sc.job(watch=watch, status="running")
        await sc.job_event(job, 3, message="Saved as listing #12")
        await sc.commit()

        await _notify(events_service.EVENTS_CHANNEL, job_id=job.id, seq=3)
        message = await _next(mailbox)
        assert message["event"] == "job.event"
        assert message["id"] == f"{job.id}:3"
        event = json.loads(message["data"])
        assert event["message"] == "Saved as listing #12"
        assert event["seq"] == 3

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("running", "job.started"),
            ("done", "job.finished"),
            ("cancelled", "job.finished"),
            ("failed", "job.failed"),
        ],
    )
    async def test_status_notifications_map_to_lifecycle_events(
        self, sc, mailbox, status, expected
    ):
        watch = await sc.watch(await sc.item())
        job = await sc.job(watch=watch, status=status)
        await sc.commit()

        await _notify(events_service.JOBS_CHANNEL, id=job.id)
        message = await _next(mailbox)
        assert message["event"] == expected
        body = json.loads(message["data"])["job"]
        assert body["id"] == job.id
        # the label is what every row on the page reads
        assert body["label"].endswith("× TestBay")

    async def test_a_pending_birth_is_not_broadcast(self, sc, mailbox):
        # the POST /api/jobs response carries the queued jobs
        watch = await sc.watch(await sc.item())
        job = await sc.job(watch=watch, status="pending")
        await sc.commit()
        await _notify(events_service.JOBS_CHANNEL, id=job.id)
        assert mailbox.empty()

    async def test_a_recheck_emits_no_lifecycle_frames(self, sc, mailbox):
        # its whole output is the price check the other trigger announces;
        # started/finished pairs three times a minute would drown the page
        watch = await sc.watch(await sc.item())
        job = await sc.job(kind="recheck", watch=watch, status="running")
        await sc.commit()
        await _notify(events_service.JOBS_CHANNEL, id=job.id)
        assert mailbox.empty()

    async def test_a_price_check_becomes_a_listing_checked_frame(self, sc, mailbox):
        item = await sc.item("Game Boy Color")
        listing = await sc.listing(await sc.watch(item), item)
        await sc.checks(listing, (0, "189.00"))
        await sc.commit()
        check_id = await sc.db.scalar(
            PriceChecks.__table__.select().with_only_columns(PriceChecks.id)
        )

        await _notify(events_service.EVENTS_CHANNEL, check=check_id)
        message = await _next(mailbox)
        assert message["event"] == "listing.checked"
        frame = json.loads(message["data"])
        assert frame["item_name"] == "Game Boy Color"
        assert frame["site_name"] == "TestBay"
        assert frame["price"] == "189.00"
        assert frame["confirmed"] is True
        assert frame["slot_freed"] is False

    async def test_a_sold_check_says_the_slot_is_free(self, sc, mailbox):
        item = await sc.item()
        listing = await sc.listing(await sc.watch(item), item)
        await sc.checks(listing, (0, None))  # an unpriced check is a sold one
        await sc.commit()
        check_id = await sc.db.scalar(
            PriceChecks.__table__.select().with_only_columns(PriceChecks.id)
        )

        await _notify(events_service.EVENTS_CHANNEL, check=check_id)
        frame = json.loads((await _next(mailbox))["data"])
        assert frame["status"] == "sold"
        assert frame["slot_freed"] is True

    async def test_a_notification_for_a_missing_row_is_survivable(self, mailbox):
        # log-and-continue: a dead hub is worse than a dropped message
        await _notify(events_service.EVENTS_CHANNEL, job_id=999, seq=1)
        await _notify(events_service.JOBS_CHANNEL, id=999)
        await _notify(events_service.EVENTS_CHANNEL, check=999)
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

    async def test_snapshot_then_live_events(self, client, db_session):
        res = await client.post("/api/auth/register", json=OWNER, headers=CSRF)
        assert res.status_code == 201, res.text
        user_id = res.json()["user"]["id"]

        async with db_session() as session:
            sc = Scenario(session)
            user = await session.get(User, user_id)
            item = await sc.item("Game Boy Color")
            watch = await sc.watch(item, user=user)
            job = await sc.job(watch=watch, status="running", days_ago=0)
            await sc.job_event(job, 1, message="Hunting TestBay…")
            job_id = job.id
            await sc.commit()

        conn = _SseConnection(dict(client.cookies))
        await conn.start()
        try:
            assert conn.status == 200
            assert conn.headers["content-type"].startswith("text/event-stream")

            first = await conn.next_event()
            assert first["event"] == "job.snapshot"
            (live,) = json.loads(first["data"])["jobs"]
            assert live["label"] == "Game Boy Color × TestBay"

            await _notify(events_service.EVENTS_CHANNEL, job_id=job_id, seq=1)
            second = await conn.next_event()
            assert second["event"] == "job.event"
            assert second["id"] == f"{job_id}:1"
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
    the ownership graph every frame is gated by. Returns the ids."""
    async with _sessionmaker()() as session:
        sc = Scenario(session)
        a = User(email="a@hub.local")
        b = User(email="b@hub.local")
        session.add_all([a, b])
        await session.flush()
        item_a = await sc.item("Alpha")
        shared = await sc.item("Shared")
        watch_a = await sc.watch(item_a, user=a)
        shared_a = await sc.watch(shared, user=a)
        await sc.watch(shared, user=b)
        listing_a = await sc.listing(watch_a, item_a)
        hunt_a = await sc.job(watch=watch_a, status="running")
        ground_shared = await sc.job(kind="ground", watch=None, item_id=shared.id, status="running")
        await sc.job_event(hunt_a, 1, message="Hunting TestBay…")
        await sc.job_event(ground_shared, 1, message="Reading price guides…")
        ids = {
            "a": a.id,
            "b": b.id,
            "item_a": item_a.id,
            "shared": shared.id,
            "shared_a": shared_a.id,
            "listing_a": listing_a.id,
            "hunt_a": hunt_a.id,
            "ground_shared": ground_shared.id,
        }
        await session.commit()
    return ids


class TestPerViewerFiltering:
    """Every frame passes the same predicate the REST surface uses
    (services/jobs.py), asserted here on the push channel: a viewer sees jobs
    for their own watches, `ground` jobs for items they watch, and — as
    admin — everything."""

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

    async def test_a_hunts_events_reach_its_owner_and_admin_only(self, graph):
        ids, clients = graph
        await _notify(events_service.EVENTS_CHANNEL, job_id=ids["hunt_a"], seq=1)
        assert (await _next(clients["a"].queue))["event"] == "job.event"
        assert clients["b"].queue.empty()
        assert (await _next(clients["admin"].queue))["event"] == "job.event"

    async def test_a_ground_jobs_events_reach_every_watcher_of_its_item(self, graph):
        ids, clients = graph
        await _notify(events_service.EVENTS_CHANNEL, job_id=ids["ground_shared"], seq=1)
        assert (await _next(clients["a"].queue))["event"] == "job.event"
        assert (await _next(clients["b"].queue))["event"] == "job.event"

    async def test_lifecycle_envelopes_are_gated_the_same_way(self, graph):
        ids, clients = graph
        await _notify(events_service.JOBS_CHANNEL, id=ids["hunt_a"])
        assert (await _next(clients["a"].queue))["event"] == "job.started"
        assert clients["b"].queue.empty()
        assert (await _next(clients["admin"].queue))["event"] == "job.started"

    async def test_a_check_reaches_only_the_listings_owner(self, graph):
        ids, clients = graph
        async with _sessionmaker()() as session:
            check = PriceChecks(
                listing_id=ids["listing_a"],
                price=Decimal("10.00"),
                currency="USD",
                in_stock=True,
                status="ok",
                method="locator",
                checked_at=NOW,
            )
            session.add(check)
            await session.commit()
            check_id = check.id

        await _notify(events_service.EVENTS_CHANNEL, check=check_id)
        assert (await _next(clients["a"].queue))["event"] == "listing.checked"
        assert clients["b"].queue.empty()
        assert (await _next(clients["admin"].queue))["event"] == "listing.checked"

    async def test_snapshots_are_per_viewer(self, graph):
        ids, _ = graph
        a_jobs = json.loads((await events_service.snapshot_message(ids["a"], False))["data"])
        assert sorted(j["kind"] for j in a_jobs["jobs"]) == ["ground", "hunt"]

        b_jobs = json.loads((await events_service.snapshot_message(ids["b"], False))["data"])
        assert [j["kind"] for j in b_jobs["jobs"]] == ["ground"]

        admin_jobs = json.loads((await events_service.snapshot_message(999, True))["data"])
        assert len(admin_jobs["jobs"]) == 2


class TestReconnect:
    async def test_a_reconnecting_viewer_rebuilds_from_snapshot_and_backfill(
        self, client, db_session
    ):
        """The contract: the snapshot names the live jobs, the client refetches
        each backfill, and live frames continue from there — with no gap
        inference anywhere (last_seq is metadata)."""
        res = await client.post("/api/auth/register", json=OWNER, headers=CSRF)
        user_id = res.json()["user"]["id"]

        async with db_session() as session:
            sc = Scenario(session)
            user = await session.get(User, user_id)
            item = await sc.item("Alpha")
            job = await sc.job(watch=await sc.watch(item, user=user), status="running", days_ago=0)
            await sc.job_event(job, 1, message="Hunting TestBay…")
            await sc.job_event(job, 2, message="Reading a candidate…")
            job_id = job.id
            await sc.commit()

        conn = _SseConnection(dict(client.cookies))
        await conn.start()
        try:
            first = await conn.next_event()
            (live,) = json.loads(first["data"])["jobs"]
            assert live["id"] == job_id
            assert live["last_seq"] == 2

            res = await client.get(f"/api/jobs/{job_id}/events?after_seq=0")
            assert [e["seq"] for e in res.json()["data"]] == [1, 2]

            await _seed(_event(job_id, seq=3, message="Saved a listing"))
            await _notify(events_service.EVENTS_CHANNEL, job_id=job_id, seq=3)
            frame = await conn.next_event()
            assert json.loads(frame["data"])["seq"] == 3

            # convergence: from the last seq held there is nothing left
            res = await client.get(f"/api/jobs/{job_id}/events?after_seq=3")
            assert res.json()["data"] == []
        finally:
            await conn.disconnect()


class TestEndToEnd:
    async def test_a_committed_insert_reaches_a_hub_client(self, sc, mailbox):
        """SQL insert -> trigger NOTIFY -> listen_pg -> broadcast, nothing mocked."""
        watch = await sc.watch(await sc.item())
        ids = (watch.id, watch.item_id, (await sc.site()).id)
        await sc.commit()
        listener = asyncio.create_task(events_service.listen_pg())
        try:
            # connected once the on-connect snapshot lands
            message = await _next(mailbox)
            assert message["event"] == "job.snapshot"

            watch_id, item_id, site_id = ids
            (job_id,) = await _seed(_job(watch_id=watch_id, item_id=item_id, site_id=site_id))
            message = await _next(mailbox)
            assert message["event"] == "job.started"

            await _seed(_event(job_id, seq=1, message="Hunting TestBay…"))
            message = await _next(mailbox)
            assert message["event"] == "job.event"
            assert message["id"] == f"{job_id}:1"
            assert json.loads(message["data"])["message"] == "Hunting TestBay…"
        finally:
            listener.cancel()
            with pytest.raises(asyncio.CancelledError):
                await listener
