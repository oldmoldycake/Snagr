"""SSE broadcaster — fan run activity out to every connected /api/events client (Phase 3, D3).

The DB is the bus: migration 007's triggers pg_notify on 'snagr_run_events'
whenever ANY writer (the agent's consumer, our cancel_run, a psql session)
commits a run_events insert or an agent_runs status change. listen_pg() holds
one dedicated LISTEN connection, re-reads the announced rows, and fans them
out to client queues as the {event, data, id} dicts that sse-starlette's
EventSourceResponse encodes on the wire (format pinned by mocks/sse.ts).

Every frame is per-viewer (run privacy): clients register with their identity,
run envelopes and snapshots are gated by run_visible, and run.event frames
additionally pass event_visible — the same predicate the REST surface uses
(services/runs.py), so push and backfill can never disagree. Visibility refs
are looked up fresh per notification: a few tiny indexed queries per event at
household scale, and no cache invalidation coupled to watch mutations.

Notifications carry ids only; rows are re-read here. NOTIFY delivers on
commit, so an announcement can never outrun what's readable.

Errors in this module log-and-continue instead of raising — the loud-failure
rule serves request handlers, but killing the app's only listener task would
silently end live updates for everyone. The reconnect loop is the recovery:
on every (re)connect each client gets a fresh per-viewer run.snapshot, from
which it refetches its visible backfill (RunEventsProvider polls
/runs/:id/events unconditionally; the filtered response is authoritative).
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field

import asyncpg
from sqlalchemy import select

from app.config import settings
from app.database import _sessionmaker
from app.models import AgentRuns, RunEvents, User
from app.schemas.runs import RunEnvelope, RunSnapshotData, RunSnapshotEntry
from app.services.runs import (
    build_agent_run,
    build_run_event,
    event_visible,
    load_viewer_refs,
    run_visible,
)

log = logging.getLogger(__name__)

CHANNEL = "snagr_run_events"

# terminal statuses -> the SSE event name the client listens for; 'running' is
# run.started, 'queued' is announced by the POST /api/runs response instead
_STATUS_EVENTS = {
    "running": "run.started",
    "succeeded": "run.finished",
    "cancelled": "run.finished",
    "failed": "run.failed",
}


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
    """Drop a disconnected client."""
    _clients.discard(client)


def _put(client: _Client, message: dict) -> None:
    try:
        client.queue.put_nowait(message)
    except asyncio.QueueFull:
        # a stalled consumer; it recovers via the snapshot on its reconnect
        log.warning("SSE client queue full; dropping message")


def broadcast(message: dict, run: AgentRuns | None = None) -> None:
    """Push one {event, data, id?} message to every connected client — or,
    when `run` is given, only to clients who may see that run."""
    for client in _clients:
        if run is None or run_visible(run, client.user_id, client.is_admin):
            _put(client, message)


async def snapshot_message(user_id: int, is_admin: bool) -> dict:
    """The per-viewer run.snapshot sent on every (re)connect — the active runs
    THIS viewer may see, from which their client refetches its backfill.
    last_seq is the run's global write cursor (metadata; never gap-compared)."""
    async with _sessionmaker()() as session:
        stmt = (
            select(AgentRuns)
            .where(AgentRuns.status.in_(("queued", "running")))
            .order_by(AgentRuns.id)
        )
        rows = (await session.execute(stmt)).scalars().all()
    data = RunSnapshotData(
        active_runs=[
            RunSnapshotEntry(
                id=run.id,
                user_id=run.user_id,
                status=run.status,
                scope=run.scope,
                scope_label=run.scope_label,
                last_seq=run.last_seq,
            )
            for run in rows
            if run_visible(run, user_id, is_admin)
        ]
    )
    return {"event": "run.snapshot", "data": data.model_dump_json()}


async def _handle_notification(payload: str) -> None:
    """Translate one trigger notification into per-viewer client deliveries."""
    note = json.loads(payload)
    if note["kind"] == "event":
        async with _sessionmaker()() as session:
            stmt = (
                select(RunEvents)
                .where(RunEvents.run_id == note["run_id"])
                .where(RunEvents.seq == note["seq"])
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                log.warning(
                    f"Notified of run_events {note['run_id']}:{note['seq']} but found no row"
                )
                return
            run = await session.get(AgentRuns, row.run_id)
            if run is None:
                log.warning(f"Notified of run {note['run_id']} but found no row")
                return
            message = {
                "event": "run.event",
                "data": build_run_event(row).model_dump_json(),
                "id": f"{row.run_id}:{row.seq}",
            }
            # the empty-set predicate call IS the neutrality test (an event
            # with no item/listing reference passes for anyone) — reusing it
            # keeps this fast path from ever drifting from the real rule
            if event_visible(row, frozenset(), frozenset()):
                broadcast(message, run)
                return
            for client in list(_clients):
                if not run_visible(run, client.user_id, client.is_admin):
                    continue
                if not client.is_admin:
                    refs = await load_viewer_refs(session, client.user_id)
                    if not event_visible(row, *refs):
                        continue
                _put(client, message)
    elif note["kind"] == "status":
        event = _STATUS_EVENTS.get(note["status"])
        if event is None:
            return
        async with _sessionmaker()() as session:
            run = await session.get(AgentRuns, note["run_id"])
        if run is None:
            log.warning(f"Notified of run {note['run_id']} but found no row")
            return
        # lifecycle envelopes carry scope_label — gated by run-row visibility
        broadcast(
            {"event": event, "data": RunEnvelope(run=build_agent_run(run)).model_dump_json()},
            run,
        )


async def listen_pg() -> None:
    """The app-lifetime listener task: LISTEN on the channel and process
    notifications in arrival order. Reconnects forever on DB loss (the LAN DB
    rides a flaky VPN); each (re)connect sends every client a fresh per-viewer
    snapshot so they backfill whatever the outage swallowed."""
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
                # per-client snapshots: each viewer gets only the runs they
                # may see, and refetches their own visible backfill from it
                for client in list(_clients):
                    _put(client, await snapshot_message(client.user_id, client.is_admin))
                log.info("SSE listener connected")
                while True:
                    try:
                        payload = await asyncio.wait_for(pending.get(), timeout=10)
                    except TimeoutError:
                        # idle: surface a silently-dead TCP link (VPN drop)
                        await conn.execute("SELECT 1")
                        continue
                    await _handle_notification(payload)
            finally:
                await conn.close()
        except (OSError, asyncpg.PostgresError) as e:
            log.error(f"SSE listener lost Postgres ({e}); retrying in 5s")
            await asyncio.sleep(5)
