"""Server-Sent Events stream — GET /api/events  (Phase 3).

NOT in endpoints.ts: the frontend opens this directly via
`new EventSource('/api/events')` in features/runs/RunEventsProvider.tsx.

Wire format (match mocks/sse.ts exactly):
    on connect  -> event: run.snapshot   {active_runs: [...]}
    per event   -> event: run.event      RunEvent    (id: "<run_id>:<seq>")
    lifecycle   -> event: run.started / run.finished / run.failed  {run: AgentRun}

Backed by services/events.py (Postgres LISTEN/NOTIFY hub, D3). nginx.conf
already disables buffering + extends timeouts for this path. Auth rides the
access cookie — EventSource can't send headers, which is why auth is cookies
in the first place; an expired cookie 401s the reconnect and the client shows
"reconnecting" until any refreshed request restores it.
"""

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from sse_starlette import EventSourceResponse

from app.core.deps import current_user
from app.services import events as events_service

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events")
async def stream_events(user=Depends(current_user)) -> EventSourceResponse:
    queue = events_service.register_client()

    async def stream() -> AsyncIterator[dict]:
        # snapshot queried inside the generator: the request-scoped session
        # would be long gone by the time an SSE body starts streaming
        try:
            yield await events_service.snapshot_message()
            while True:
                yield await queue.get()
        finally:
            events_service.unregister_client(queue)

    return EventSourceResponse(stream())
