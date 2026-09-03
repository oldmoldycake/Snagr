"""The notification dispatcher, layer by layer — the shape of test_events_sse.py.

1. TestNotifyTrigger    — migration 010's DDL: an outbox insert NOTIFYs, and
                          nothing else does (raw asyncpg LISTEN, no app code).
2. TestExpand           — _expand_one: fanout, the events filter, disabled
                          channels, and the zero-channels 'skipped' outcome.
3. TestDeliver          — _deliver_one with outbound HTTP behind a
                          MockTransport: the exact ntfy bytes (the format the
                          agent used to send itself), the signed webhook
                          envelope (signature recomputed and verified here),
                          the Discord embed, and the retry/backoff ladder.
4. TestEndToEnd         — the real listen_pg() task, nothing mocked but HTTP:
                          the on-connect drain delivers what was queued while
                          it was down, then a fresh insert rides the NOTIFY.

The renderers are pure functions, so layer 3 asserts payload bytes without a
network anywhere. Suite-order caveat: the end-to-end task must be cancelled
before _clean_tables truncates, or TRUNCATE blocks on its claim locks.
"""

import asyncio
import hashlib
import hmac
import json
import os
from datetime import UTC, datetime, timedelta

import asyncpg
import httpx
import pytest
from app.config import settings
from app.models import NotificationDeliveries, NotificationOutbox
from app.services import notifications as notifications_service
from sqlalchemy import select

DSN = os.environ["DATABASE_URL"].replace("+asyncpg", "")


@pytest.fixture
async def listen():
    """A raw LISTEN connection on the notify channel; yields a queue of payloads."""
    conn = await asyncpg.connect(DSN)
    notifications: asyncio.Queue[str] = asyncio.Queue()
    await conn.add_listener(
        notifications_service.CHANNEL, lambda *args: notifications.put_nowait(args[3])
    )
    yield notifications
    await conn.close()


@pytest.fixture
def outbound(monkeypatch):
    """Route the dispatcher's outbound HTTP into a MockTransport. Returns the
    captured requests; set .status via the list-wrapper to fail sends."""
    requests: list[httpx.Request] = []
    status = {"code": 200, "headers": {}}
    real_client = httpx.AsyncClient  # the patch below replaces the module attr

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status["code"], headers=status["headers"])

    def factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(notifications_service.httpx, "AsyncClient", factory)
    requests_status = requests, status
    return requests_status


@pytest.fixture
def ntfy_server(monkeypatch):
    monkeypatch.setattr(settings, "NTFY_SERVER_URL", "https://ntfy.test")


async def _next(queue: asyncio.Queue, timeout: float = 5.0):
    return await asyncio.wait_for(queue.get(), timeout)


async def _read_delivery(db_session, delivery_id: int) -> NotificationDeliveries:
    async with db_session() as session:
        return await session.get(NotificationDeliveries, delivery_id)


async def _seed_delivery(sc, *, kind="ntfy", event="target.hit", **delivery_overrides):
    """One committed (outbox, channel, pending delivery) triple; returns ids."""
    outbox = await sc.outbox(event=event)
    channel = await sc.channel(kind=kind)
    delivery = NotificationDeliveries(
        outbox_id=outbox.id, channel_id=channel.id, **delivery_overrides
    )
    sc.db.add(delivery)
    await sc.db.flush()
    ids = (outbox.id, channel.id, delivery.id)
    await sc.db.commit()
    return ids


class TestNotifyTrigger:
    async def test_an_outbox_insert_notifies_its_id(self, sc, listen):
        row = await sc.outbox()
        await sc.db.commit()
        note = json.loads(await _next(listen))
        assert note == {"outbox_id": row.id}

    async def test_channel_and_delivery_writes_stay_silent(self, sc, listen):
        outbox = await sc.outbox()
        await sc.db.commit()
        await _next(listen)  # drain the outbox insert's own announcement

        channel = await sc.channel()
        sc.db.add(NotificationDeliveries(outbox_id=outbox.id, channel_id=channel.id))
        await sc.db.commit()
        with pytest.raises(TimeoutError):
            await _next(listen, timeout=0.5)


class TestExpand:
    async def test_fans_out_to_every_matching_channel(self, sc, db_session):
        outbox = await sc.outbox()
        a = await sc.channel(kind="ntfy")
        b = await sc.channel(kind="discord", events=["target.hit"])
        await sc.db.commit()

        assert await notifications_service._expand_one() is True
        async with db_session() as session:
            deliveries = (await session.execute(select(NotificationDeliveries))).scalars().all()
            assert {d.channel_id for d in deliveries} == {a.id, b.id}
            refreshed = await session.get(NotificationOutbox, outbox.id)
            assert refreshed.status == "processed"
            assert refreshed.processed_at is not None

    async def test_the_events_filter_and_disabled_channels_exclude(self, sc, db_session):
        await sc.outbox(event="target.hit")
        await sc.channel(kind="discord", events=["listing.new"])  # wrong event
        await sc.channel(kind="ntfy", enabled=False)  # off
        matching = await sc.channel(kind="webhook", events=["target.hit", "listing.new"])
        await sc.db.commit()

        assert await notifications_service._expand_one() is True
        async with db_session() as session:
            (delivery,) = (await session.execute(select(NotificationDeliveries))).scalars().all()
            assert delivery.channel_id == matching.id

    async def test_no_channels_marks_the_event_skipped(self, sc, db_session):
        outbox = await sc.outbox()
        await sc.db.commit()

        assert await notifications_service._expand_one() is True
        async with db_session() as session:
            refreshed = await session.get(NotificationOutbox, outbox.id)
            assert refreshed.status == "skipped"
            deliveries = (await session.execute(select(NotificationDeliveries))).scalars().all()
            assert deliveries == []

    async def test_nothing_pending_returns_false(self, sc):
        assert await notifications_service._expand_one() is False


class TestDeliver:
    async def test_ntfy_reproduces_the_agents_old_message(
        self, sc, db_session, outbound, ntfy_server
    ):
        _, _, delivery_id = await _seed_delivery(sc, kind="ntfy")
        requests, _ = outbound

        assert await notifications_service._deliver_one() is True
        (request,) = requests
        assert str(request.url) == "https://ntfy.test/test-topic"
        assert request.content.decode() == "Widget — 90.00 USD on TestBay (target 100.00)"
        assert request.headers["Title"] == "Snagr target hit"
        assert request.headers["Tags"] == "moneybag"
        assert request.headers["Click"] == "https://testbay.example/listing/1"

        delivery = await _read_delivery(db_session, delivery_id)
        assert (delivery.status, delivery.attempts) == ("delivered", 1)
        assert delivery.delivered_at is not None

    async def test_webhook_envelope_is_signed_and_versioned(self, sc, db_session, outbound):
        outbox_id, _, delivery_id = await _seed_delivery(sc, kind="webhook")
        requests, _ = outbound

        assert await notifications_service._deliver_one() is True
        (request,) = requests
        body = json.loads(request.content)
        assert body == {
            "version": 1,
            "id": outbox_id,
            "event": "target.hit",
            "occurred_at": body["occurred_at"],
            "data": {
                "watch_id": 1,
                "item_id": 1,
                "listing_id": 1,
                "site_id": 1,
                "item_name": "Widget",
                "site_name": "TestBay",
                "listing_url": "https://testbay.example/listing/1",
                "price": "90.00",
                "currency": "USD",
                "target_price": "100.00",
            },
        }
        assert request.headers["X-Snagr-Event"] == "target.hit"
        assert request.headers["X-Snagr-Delivery"] == str(delivery_id)
        # recompute the signature the way a consumer would: over the literal
        # timestamp header value, a dot, and the exact received bytes
        timestamp = request.headers["X-Snagr-Timestamp"]
        expected = hmac.new(
            b"test-secret", f"{timestamp}.".encode() + request.content, hashlib.sha256
        ).hexdigest()
        assert request.headers["X-Snagr-Signature"] == f"sha256={expected}"

    async def test_discord_gets_a_target_hit_embed(self, sc, outbound):
        await _seed_delivery(sc, kind="discord")
        requests, _ = outbound

        assert await notifications_service._deliver_one() is True
        (request,) = requests
        body = json.loads(request.content)
        assert body["username"] == "Snagr"
        (embed,) = body["embeds"]
        assert embed["title"] == "Widget"
        assert embed["url"] == "https://testbay.example/listing/1"
        assert embed["color"] == 0x22C55E
        assert embed["footer"] == {"text": "Snagr"}
        assert embed["fields"] == [
            {"name": "Price", "value": "90.00 USD", "inline": True},
            {"name": "Target", "value": "100.00 USD", "inline": True},
            {"name": "Site", "value": "TestBay", "inline": True},
        ]

    async def test_a_failed_send_spends_an_attempt_and_backs_off(self, sc, db_session, outbound):
        _, _, delivery_id = await _seed_delivery(sc, kind="webhook")
        requests, status = outbound
        status["code"] = 500

        before = datetime.now(UTC)
        assert await notifications_service._deliver_one() is True
        delivery = await _read_delivery(db_session, delivery_id)
        assert (delivery.status, delivery.attempts) == ("pending", 1)
        assert "500" in delivery.last_error
        assert delivery.next_attempt_at >= before + timedelta(
            seconds=notifications_service.RETRY_BACKOFF[0]
        )

        # not due yet — nothing to deliver until the backoff elapses
        assert await notifications_service._deliver_one() is False

    async def test_the_last_attempt_goes_terminal(self, sc, db_session, outbound):
        _, _, delivery_id = await _seed_delivery(
            sc, kind="webhook", attempts=notifications_service.MAX_ATTEMPTS - 1
        )
        _, status = outbound
        status["code"] = 500

        assert await notifications_service._deliver_one() is True
        delivery = await _read_delivery(db_session, delivery_id)
        expected = ("failed", notifications_service.MAX_ATTEMPTS)
        assert (delivery.status, delivery.attempts) == expected

    async def test_a_discord_rate_limit_hint_stretches_the_backoff(self, sc, db_session, outbound):
        _, _, delivery_id = await _seed_delivery(sc, kind="discord")
        _, status = outbound
        status["code"] = 429
        status["headers"] = {"Retry-After": "120"}

        before = datetime.now(UTC)
        assert await notifications_service._deliver_one() is True
        delivery = await _read_delivery(db_session, delivery_id)
        assert delivery.status == "pending"
        assert delivery.next_attempt_at >= before + timedelta(seconds=120)

    async def test_ntfy_without_a_server_is_a_spent_attempt(
        self, sc, db_session, outbound, monkeypatch
    ):
        monkeypatch.setattr(settings, "NTFY_SERVER_URL", None)
        _, _, delivery_id = await _seed_delivery(sc, kind="ntfy")

        assert await notifications_service._deliver_one() is True
        delivery = await _read_delivery(db_session, delivery_id)
        assert (delivery.status, delivery.attempts) == ("pending", 1)
        assert "no ntfy server" in delivery.last_error


class TestEndToEnd:
    async def test_queued_and_fresh_events_both_deliver(
        self, sc, db_session, outbound, ntfy_server
    ):
        """Outbox insert -> trigger NOTIFY -> listen_pg -> HTTP out, nothing
        else mocked. The row committed BEFORE the task starts proves the
        on-connect drain (catch-up); the one inserted after proves the NOTIFY
        path."""
        await sc.channel(kind="ntfy")
        queued = await sc.outbox()
        await sc.db.commit()
        requests, _ = outbound

        task = asyncio.create_task(notifications_service.listen_pg())
        try:

            async def until(condition, timeout=5.0):
                deadline = asyncio.get_running_loop().time() + timeout
                while not condition():
                    assert asyncio.get_running_loop().time() < deadline, "timed out"
                    await asyncio.sleep(0.05)

            await until(lambda: len(requests) == 1)

            async with db_session() as session:
                refreshed = await session.get(NotificationOutbox, queued.id)
                assert refreshed.status == "processed"
                session.add(
                    NotificationOutbox(
                        user_id=queued.user_id, event="target.hit", payload=queued.payload
                    )
                )
                await session.commit()

            await until(lambda: len(requests) == 2)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
