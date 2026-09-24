"""SSE broadcaster — fan the hunter's activity out to every connected
/api/events client.

The DB is the bus: migration 015's triggers pg_notify whenever ANY writer
(the agent daemon, our cancel_job, a psql session) commits a jobs insert or
status change ('snagr_jobs'), a job_events insert or a price_checks insert
('snagr_job_events'). listen_pg() holds one dedicated LISTEN connection,
re-reads the announced rows, and fans them out to client queues as the
{event, data, id} dicts that sse-starlette's EventSourceResponse encodes on
the wire (format pinned by mocks/sse.ts).

Two shapes of frame, because the hunter does two shapes of work. A hunt (or a
grounding pass) has a voice: lifecycle envelopes plus every line of its log.
A recheck has a pulse: no lifecycle, no events, just the price check it
wrote, which is what `listing.checked` carries — that is the whole reason
rechecks are cheap enough to run every half hour.

Every frame is per-viewer (job privacy): clients register with their
identity, and each frame is gated by the same predicate the REST surface uses
(services/jobs.py), so push and backfill can never disagree. Visibility is
looked up fresh per notification: a few tiny indexed queries per event at
household scale, and no cache invalidation coupled to watch mutations.

Notifications carry ids only; rows are re-read here. NOTIFY delivers on
commit, so an announcement can never outrun what's readable.

Errors in this module log-and-continue instead of raising — the loud-failure
rule serves request handlers, but killing the app's only listener task would
silently end live updates for everyone. The reconnect loop is the recovery:
on every (re)connect each client gets a fresh per-viewer job.snapshot, from
which it refetches its visible backfills (JobsProvider polls
/jobs/:id/events unconditionally; the filtered response is authoritative).
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field

import asyncpg
from sqlalchemy import select

from app.config import settings
from app.database import _sessionmaker
from app.models import Items, JobEvents, Jobs, Listings, PriceChecks, Sites, User, Watches
from app.schemas.jobs import JobEnvelope, JobSnapshotData, ListingChecked
from app.services.jobs import build_job_event, live_jobs, named_job, sees_job

log = logging.getLogger(__name__)

JOBS_CHANNEL = "snagr_jobs"
EVENTS_CHANNEL = "snagr_job_events"

# job status -> the SSE event name the client listens for. 'pending' has no
# entry: the POST /api/jobs response announces it instead.
_STATUS_EVENTS = {
    "running": "job.started",
    "done": "job.finished",
    "cancelled": "job.finished",
    "failed": "job.failed",
}

# Only work with a story to tell gets lifecycle frames. A recheck's whole
# output is its price check, and announcing three of those a minute as
# started/finished pairs would drown the page it is meant to inform.
_NARRATED_KINDS = ("hunt", "ground")


@dataclass(frozen=True, eq=False)
class _Client:
    """One connected /api/events viewer: their queue plus the identity every
    per-viewer filter keys on. eq=False keeps identity hashing — two tabs of
    the same user are two clients."""

    user_id: int
    is_admin: bool
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1000))


_clients: set[_Client] = set()


def register_client(user: User) -> _Client:
    """Add a connected /api/events viewer; returns their client handle."""
    client = _Client(user_id=user.id, is_admin=user.role == "admin")
    _clients.add(client)
    return client


def unregister_client(client: _Client) -> None:
    """Forget a viewer whose stream closed; a no-op if it is already gone."""
    _clients.discard(client)


def _put(client: _Client, message: dict) -> None:
    try:
        client.queue.put_nowait(message)
    except asyncio.QueueFull:
        # a stalled consumer; it recovers via the snapshot on its reconnect
        log.warning("SSE client queue full; dropping message")


async def _broadcast_job(session, job_id: int, message: dict) -> None:
    """Push one message to every client who may see that job."""
    for client in list(_clients):
        if await sees_job(session, job_id, client.user_id, client.is_admin):
            _put(client, message)


async def snapshot_message(user_id: int, is_admin: bool) -> dict:
    """The per-viewer job.snapshot sent on every (re)connect — the live hunts
    THIS viewer may see, from which their client rebuilds its live set and
    refetches each backfill. last_seq is the job's global write cursor
    (metadata; never gap-compared)."""
    async with _sessionmaker()() as session:
        jobs = await live_jobs(session, user_id, is_admin)
    return {"event": "job.snapshot", "data": JobSnapshotData(jobs=jobs).model_dump_json()}


async def _handle_job(session, job_id: int) -> None:
    """A jobs insert or status change — a lifecycle frame, or nothing."""
    job = await session.get(Jobs, job_id)
    if job is None:
        log.warning(f"Notified of job {job_id} but found no row")
        return
    if job.kind not in _NARRATED_KINDS:
        return
    event = _STATUS_EVENTS.get(job.status)
    if event is None:
        return
    frame = await named_job(session, job_id)
    if frame is None:
        return
    await _broadcast_job(
        session, job_id, {"event": event, "data": JobEnvelope(job=frame).model_dump_json()}
    )


async def _handle_job_event(session, job_id: int, seq: int) -> None:
    """One line of a job's log."""
    row = (
        await session.execute(
            select(JobEvents).where(JobEvents.job_id == job_id).where(JobEvents.seq == seq)
        )
    ).scalar_one_or_none()
    if row is None:
        log.warning(f"Notified of job_events {job_id}:{seq} but found no row")
        return
    await _broadcast_job(
        session,
        job_id,
        {
            "event": "job.event",
            "data": build_job_event(row).model_dump_json(),
            "id": f"{job_id}:{seq}",
        },
    )


async def _handle_price_check(session, check_id: int) -> None:
    """A price check, whichever path read it — the recheck's whole output.

    Gated by listing ownership rather than by a job, because a check written
    by a hunt belongs to the same person and reads the same on the page.
    """
    row = (
        await session.execute(
            select(
                PriceChecks.listing_id,
                PriceChecks.price,
                PriceChecks.currency,
                PriceChecks.status,
                PriceChecks.method,
                PriceChecks.confirmed,
                PriceChecks.checked_at,
                Listings.item_id,
                Items.name.label("item_name"),
                Sites.name.label("site_name"),
                Watches.user_id.label("owner_id"),
            )
            .join(Listings, Listings.id == PriceChecks.listing_id)
            .join(Items, Items.id == Listings.item_id)
            .join(Sites, Sites.id == Listings.site_id)
            .join(Watches, Watches.id == Listings.watch_id)
            .where(PriceChecks.id == check_id)
        )
    ).one_or_none()
    if row is None:
        log.warning(f"Notified of price_check {check_id} but found no row")
        return

    frame = ListingChecked(
        listing_id=row.listing_id,
        item_id=row.item_id,
        item_name=row.item_name,
        site_name=row.site_name,
        price=str(row.price) if row.price is not None else None,
        currency=row.currency,
        status=row.status,
        method=row.method,
        confirmed=row.confirmed,
        # a listing that sold or ended is not re-read again, and the slot it
        # held is what the next hunt fills
        slot_freed=row.status in ("sold", "ended"),
        checked_at=row.checked_at.isoformat(),
    )
    message = {"event": "listing.checked", "data": frame.model_dump_json()}
    owner = row.owner_id
    for client in list(_clients):
        if client.is_admin or client.user_id == owner:
            _put(client, message)


async def _handle_notification(channel: str, payload: str) -> None:
    """Translate one trigger notification into per-viewer client deliveries."""
    note = json.loads(payload)
    async with _sessionmaker()() as session:
        if channel == JOBS_CHANNEL:
            await _handle_job(session, note["id"])
        elif "check" in note:
            await _handle_price_check(session, note["check"])
        else:
            await _handle_job_event(session, note["job_id"], note["seq"])


async def listen_pg() -> None:
    """The app-lifetime listener task: LISTEN on both channels and process
    notifications in arrival order. Reconnects forever on DB loss (the LAN DB
    rides a flaky VPN); each (re)connect sends every client a fresh per-viewer
    snapshot so they backfill whatever the outage swallowed."""
    # asyncpg wants a plain postgres:// DSN, without SQLAlchemy's driver tag
    dsn = settings.DATABASE_URL.replace("+asyncpg", "")
    pending: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

    def _on_notify(_conn, _pid, channel: str, payload: str) -> None:
        pending.put_nowait((channel, payload))

    while True:
        try:
            conn = await asyncpg.connect(dsn)
            try:
                for channel in (JOBS_CHANNEL, EVENTS_CHANNEL):
                    await conn.add_listener(channel, _on_notify)
                # per-client snapshots: each viewer gets only the jobs they
                # may see, and refetches their own visible backfill from it
                for client in list(_clients):
                    _put(client, await snapshot_message(client.user_id, client.is_admin))
                log.info("SSE listener connected")
                while True:
                    try:
                        channel, payload = await asyncio.wait_for(pending.get(), timeout=10)
                    except TimeoutError:
                        # idle: surface a silently-dead TCP link (VPN drop)
                        await conn.execute("SELECT 1")
                        continue
                    await _handle_notification(channel, payload)
            finally:
                await conn.close()
        except (OSError, asyncpg.PostgresError) as e:
            log.error(f"SSE listener lost Postgres ({e}); retrying in 5s")
            await asyncio.sleep(5)
