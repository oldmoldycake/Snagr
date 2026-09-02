"""Notification dispatch — the seventh service, for the delivery loop no router owns.

The DB is the bus: migration 010's trigger pg_notifys 'snagr_notifications'
whenever any writer (the agent's save tools, a psql session) commits a
notification_outbox insert. listen_pg() holds one dedicated LISTEN
connection, but unlike the SSE hub the payload is only a wakeup hint: every
wake — connect, NOTIFY, or the 10s idle heartbeat — runs the same full
_drain(), so rows written while the backend was down are swept on the next
connect and due retries ride the heartbeat. Nothing depends on a NOTIFY
actually arriving.

_drain() expands each pending outbox row into one notification_deliveries
row per matching enabled channel (zero matches -> 'skipped'), then sends
every due pending delivery: ntfy text, Discord embed, or the signed
versioned webhook envelope. A failed send spends an attempt and backs off
(RETRY_BACKOFF); after MAX_ATTEMPTS the delivery goes 'failed' and stays
as the delivery log.

Errors here log-and-continue instead of raising — the loud-failure rule
serves request handlers, but a dead dispatcher silently loses everyone's
notifications. A send that raises anything (a poisoned payload included) is
recorded on its delivery row as a spent attempt, so it burns out instead of
wedging the loop. Single-worker assumption: the Dockerfile and compose run
one uvicorn worker, so exactly one dispatcher exists; the SKIP LOCKED
claims make an accidental second instance safe, not supported.

Test sends (POST /api/me/channels/{id}/test) reuse the same adapters via
send_test(), which is what keeps the test button honest — it exercises the
exact path a real event takes.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

import asyncpg
import httpx
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.core.security import sign_webhook
from app.database import _sessionmaker
from app.models import NotificationChannels, NotificationDeliveries, NotificationOutbox

log = logging.getLogger(__name__)

CHANNEL = "snagr_notifications"

SEND_TIMEOUT_SECONDS = 10
MAX_ATTEMPTS = 5
# seconds until retry n+1 after failure n: quick blip, short outage, longer
# outage, "try again in a while"
RETRY_BACKOFF = (30, 300, 1800, 7200)

_EMBED_COLORS = {"target.hit": 0x22C55E, "listing.new": 0x3B82F6, "test": 0x64748B}


class _RetryAfter(Exception):
    """A send the destination rate-limited while telling us when to come back
    (Discord 429) — the backoff honors the larger of its hint and our slot."""

    def __init__(self, seconds: float, cause: str):
        super().__init__(cause)
        self.seconds = seconds


# --- per-kind rendering (pure — shared by real sends, test sends, and tests) --


def _ntfy_message(event: str, payload: dict) -> tuple[str, dict[str, str]]:
    """(body, headers) for a ntfy push. Title stays ASCII: item names ride in
    the UTF-8 body because HTTP header values have no encoding to trust."""
    if event == "target.hit":
        body = (
            f"{payload['item_name']} — {payload['price']} {payload['currency']} "
            f"on {payload['site_name']} (target {payload['target_price']})"
        )
        return body, {
            "Title": "Snagr target hit",
            "Tags": "moneybag",
            "Click": payload["listing_url"],
        }
    if event == "listing.new":
        body = (
            f"{payload['title'] or payload['item_name']} — "
            f"{payload['match_score']}/100 match on {payload['site_name']}"
        )
        return body, {
            "Title": "Snagr new listing",
            "Tags": "mag",
            "Click": payload["listing_url"],
        }
    return "Snagr test notification — you're all set!", {"Title": "Snagr", "Tags": "tada"}


def _discord_payload(event: str, payload: dict, occurred_at: str) -> dict:
    """The Discord incoming-webhook body: one embed per event."""
    if event == "target.hit":
        embed = {
            "title": payload["item_name"][:256],
            "url": payload["listing_url"],
            "description": "Target price hit",
            "color": _EMBED_COLORS[event],
            "fields": [
                {
                    "name": "Price",
                    "value": f"{payload['price']} {payload['currency']}",
                    "inline": True,
                },
                {
                    "name": "Target",
                    "value": f"{payload['target_price']} {payload['currency']}",
                    "inline": True,
                },
                {"name": "Site", "value": payload["site_name"], "inline": True},
            ],
            "timestamp": occurred_at,
            "footer": {"text": "Snagr"},
        }
    elif event == "listing.new":
        embed = {
            "title": (payload["title"] or payload["item_name"])[:256],
            "url": payload["listing_url"],
            "description": payload["match_summary"],
            "color": _EMBED_COLORS[event],
            "fields": [
                {"name": "Item", "value": payload["item_name"], "inline": True},
                {"name": "Site", "value": payload["site_name"], "inline": True},
                {"name": "Match", "value": f"{payload['match_score']}/100", "inline": True},
            ],
            "timestamp": occurred_at,
            "footer": {"text": "Snagr"},
        }
    else:
        embed = {
            "title": "Snagr test notification",
            "description": "you're all set!",
            "color": _EMBED_COLORS["test"],
            "footer": {"text": "Snagr"},
        }
    return {"username": "Snagr", "embeds": [embed]}


def _webhook_body(outbox_id: int, event: str, payload: dict, occurred_at: str) -> bytes:
    """The versioned envelope, serialized once — the signature covers these
    exact bytes. `id` is the outbox id: consumers dedupe on it across retries."""
    envelope = {
        "version": 1,
        "id": outbox_id,
        "event": event,
        "occurred_at": occurred_at,
        "data": payload,
    }
    return json.dumps(envelope, separators=(",", ":")).encode()


# --- per-kind sending ---------------------------------------------------------


async def _send_ntfy(channel: NotificationChannels, event: str, payload: dict) -> None:
    if not settings.NTFY_SERVER_URL:
        raise RuntimeError("this instance has no ntfy server configured")
    body, headers = _ntfy_message(event, payload)
    async with httpx.AsyncClient(timeout=SEND_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            f"{settings.NTFY_SERVER_URL.rstrip('/')}/{channel.topic}",
            content=body,
            headers=headers,
        )
        resp.raise_for_status()


async def _send_discord(
    channel: NotificationChannels, event: str, payload: dict, occurred_at: str
) -> None:
    async with httpx.AsyncClient(timeout=SEND_TIMEOUT_SECONDS) as client:
        resp = await client.post(channel.url, json=_discord_payload(event, payload, occurred_at))
        if resp.status_code == 429:
            raise _RetryAfter(float(resp.headers.get("Retry-After") or 0), "Discord rate limit")
        resp.raise_for_status()


async def _send_webhook(
    channel: NotificationChannels,
    outbox_id: int,
    event: str,
    payload: dict,
    occurred_at: str,
    delivery_id: str,
) -> None:
    body = _webhook_body(outbox_id, event, payload, occurred_at)
    timestamp = str(int(datetime.now(UTC).timestamp()))
    headers = {
        "Content-Type": "application/json",
        "X-Snagr-Event": event,
        "X-Snagr-Delivery": delivery_id,
        "X-Snagr-Timestamp": timestamp,
        "X-Snagr-Signature": sign_webhook(channel.secret, timestamp, body),
    }
    async with httpx.AsyncClient(timeout=SEND_TIMEOUT_SECONDS) as client:
        resp = await client.post(channel.url, content=body, headers=headers)
        resp.raise_for_status()


async def _send(
    channel: NotificationChannels,
    outbox_id: int,
    event: str,
    payload: dict,
    occurred_at: str,
    delivery_id: str,
) -> None:
    """Deliver one message to one channel; raises on any failure."""
    if channel.kind == "ntfy":
        await _send_ntfy(channel, event, payload)
    elif channel.kind == "discord":
        await _send_discord(channel, event, payload, occurred_at)
    else:
        await _send_webhook(channel, outbox_id, event, payload, occurred_at, delivery_id)


async def send_test(channel: NotificationChannels) -> None:
    """One synthetic message through the real adapter for this channel's kind.
    Raises exactly like a real send — the router maps RuntimeError (no ntfy
    server) to 422 no_server and httpx errors to 502 channel_failed."""
    await _send(channel, 0, "test", {}, datetime.now(UTC).isoformat(), "test")


# --- the dispatch loop --------------------------------------------------------


async def _expand_one() -> bool:
    """Claim one pending outbox row and fan it out into per-channel
    deliveries; zero matching channels marks it 'skipped' — the event stays
    recorded either way. True when a row was processed."""
    async with _sessionmaker()() as session:
        stmt = (
            select(NotificationOutbox)
            .where(NotificationOutbox.status == "pending")
            .order_by(NotificationOutbox.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return False
        result = await session.execute(
            select(NotificationChannels)
            .where(NotificationChannels.user_id == row.user_id)
            .where(NotificationChannels.enabled)
        )
        matching = [c for c in result.scalars() if c.events is None or row.event in c.events]
        for channel in matching:
            session.add(NotificationDeliveries(outbox_id=row.id, channel_id=channel.id))
        row.status = "processed" if matching else "skipped"
        row.processed_at = datetime.now(UTC)
        await session.commit()
        return True


async def _deliver_one() -> bool:
    """Claim one due pending delivery and attempt it; True when one was tried.

    The send happens while the row lock is held — deliberate: a crash mid-send
    releases the lock and the row is simply still pending, so there is no
    'sending' limbo state and no reaper to write. Duplicate delivery after a
    crash-between-send-and-commit is the accepted cost (consumers dedupe on
    the envelope id)."""
    now = datetime.now(UTC)
    async with _sessionmaker()() as session:
        stmt = (
            select(NotificationDeliveries, NotificationOutbox, NotificationChannels)
            .join(NotificationOutbox, NotificationOutbox.id == NotificationDeliveries.outbox_id)
            .join(
                NotificationChannels,
                NotificationChannels.id == NotificationDeliveries.channel_id,
            )
            .where(NotificationDeliveries.status == "pending")
            .where(NotificationDeliveries.next_attempt_at <= now)
            .order_by(NotificationDeliveries.next_attempt_at)
            .limit(1)
            .with_for_update(skip_locked=True, of=NotificationDeliveries)
        )
        claimed = (await session.execute(stmt)).one_or_none()
        if claimed is None:
            return False
        delivery, outbox, channel = claimed
        delivery.attempts += 1
        try:
            await _send(
                channel,
                outbox.id,
                outbox.event,
                outbox.payload,
                outbox.created_at.isoformat(),
                str(delivery.id),
            )
        except Exception as e:
            delivery.last_error = f"{e!r}"[:500]
            if delivery.attempts >= MAX_ATTEMPTS:
                delivery.status = "failed"
                log.error(f"Delivery {delivery.id} ({channel.kind}) failed for good: {e!r}")
            else:
                backoff = RETRY_BACKOFF[delivery.attempts - 1]
                if isinstance(e, _RetryAfter):
                    backoff = min(max(backoff, e.seconds), 3600)
                delivery.next_attempt_at = datetime.now(UTC) + timedelta(seconds=backoff)
                log.warning(
                    f"Delivery {delivery.id} ({channel.kind}) attempt "
                    f"{delivery.attempts} failed, retrying in {backoff:.0f}s: {e!r}"
                )
        else:
            delivery.status = "delivered"
            delivery.delivered_at = datetime.now(UTC)
        await session.commit()
        return True


async def _drain() -> None:
    """Expand every pending event, then attempt every due delivery. Called on
    connect, on every NOTIFY, and on the idle heartbeat — one code path, so a
    missed NOTIFY is never special."""
    while await _expand_one():
        pass
    while await _deliver_one():
        pass


async def listen_pg() -> None:
    """The app-lifetime dispatcher task: LISTEN on the channel and drain on
    every wake. Reconnects forever on DB loss (the LAN DB rides a flaky VPN);
    the on-connect drain is the catch-up for anything written in the gap."""
    # asyncpg wants a plain postgres:// DSN, without SQLAlchemy's driver tag
    dsn = settings.DATABASE_URL.replace("+asyncpg", "")
    pending: asyncio.Queue[str] = asyncio.Queue()

    def _on_notify(_conn, _pid, _channel, payload: str) -> None:
        pending.put_nowait(payload)

    while True:
        try:
            conn = await asyncpg.connect(dsn)
            try:
                await conn.add_listener(CHANNEL, _on_notify)
                log.info("notification dispatcher connected")
                await _drain()
                while True:
                    try:
                        await asyncio.wait_for(pending.get(), timeout=10)
                        while not pending.empty():  # coalesce a burst into one drain
                            pending.get_nowait()
                    except TimeoutError:
                        # idle: surface a silently-dead TCP link (VPN drop) —
                        # and this tick is what makes due retries fire
                        await conn.execute("SELECT 1")
                    await _drain()
            finally:
                await conn.close()
        # SQLAlchemyError too, unlike the SSE hub: _drain() IS this task's job,
        # so a DB loss inside it must reconnect rather than kill the loop
        except (OSError, asyncpg.PostgresError, SQLAlchemyError) as e:
            log.error(f"notification dispatcher lost Postgres ({e}); retrying in 5s")
            await asyncio.sleep(5)
