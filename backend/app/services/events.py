"""SSE broadcaster — fan run activity out to every connected /api/events client (Phase 3, D3).

The DB is the bus: migration 007's triggers pg_notify on 'snagr_run_events'
whenever ANY writer (the agent's consumer, our cancel_run, a psql session)
commits a run_events insert or an agent_runs status change. listen_pg() holds
one dedicated LISTEN connection, re-reads the announced rows, and broadcasts
them to every client queue as the {event, data, id} dicts that sse-starlette's
EventSourceResponse encodes on the wire (format pinned by mocks/sse.ts).

Notifications carry ids only; rows are re-read here. NOTIFY delivers on
commit, so an announcement can never outrun what's readable.

Errors in this module log-and-continue instead of raising — the loud-failure
rule serves request handlers, but killing the app's only listener task would
silently end live updates for everyone. The reconnect loop is the recovery:
on every (re)connect it broadcasts a fresh run.snapshot, and clients backfill
gaps from it (RunEventsProvider compares last_seq and polls /runs/:id/events).
"""

import asyncio
import json
import logging

import asyncpg
from sqlalchemy import select

from app.config import settings
from app.database import _sessionmaker
from app.models import AgentRuns, RunEvents
from app.schemas.runs import RunEnvelope, RunSnapshotData, RunSnapshotEntry
from app.services.runs import build_agent_run, build_run_event

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

_clients: set[asyncio.Queue] = set()


def register_client() -> asyncio.Queue:
    """Add a connected /api/events client; returns its private message queue."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
    _clients.add(queue)
    return queue


def unregister_client(queue: asyncio.Queue) -> None:
    """Drop a disconnected client's queue."""
    _clients.discard(queue)


def broadcast(message: dict) -> None:
    """Push one {event, data, id?} message to every connected client."""
    for queue in _clients:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            # a stalled consumer; it recovers via the snapshot on its reconnect
            log.warning("SSE client queue full; dropping message")


async def snapshot_message() -> dict:
    """The run.snapshot sent on every (re)connect — active runs + last_seq,
    from which clients backfill any events they missed."""
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
                status=run.status,
                scope=run.scope,
                scope_label=run.scope_label,
                last_seq=run.last_seq,
            )
            for run in rows
        ]
    )
    return {"event": "run.snapshot", "data": data.model_dump_json()}


async def _handle_notification(payload: str) -> None:
    """Translate one trigger notification into a client broadcast."""
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
            log.warning(f"Notified of run_events {note['run_id']}:{note['seq']} but found no row")
            return
        broadcast(
            {
                "event": "run.event",
                "data": build_run_event(row).model_dump_json(),
                "id": f"{row.run_id}:{row.seq}",
            }
        )
    elif note["kind"] == "status":
        event = _STATUS_EVENTS.get(note["status"])
        if event is None:
            return
        async with _sessionmaker()() as session:
            run = await session.get(AgentRuns, note["run_id"])
        if run is None:
            log.warning(f"Notified of run {note['run_id']} but found no row")
            return
        broadcast({"event": event, "data": RunEnvelope(run=build_agent_run(run)).model_dump_json()})


async def listen_pg() -> None:
    """The app-lifetime listener task: LISTEN on the channel and process
    notifications in arrival order. Reconnects forever on DB loss (the LAN DB
    rides a flaky VPN); each (re)connect broadcasts a fresh snapshot so
    clients backfill whatever the outage swallowed."""
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
                broadcast(await snapshot_message())
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
