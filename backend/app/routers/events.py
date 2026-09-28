"""Server-Sent Events stream — GET /api/events.

NOT in endpoints.ts: the frontend opens this directly via
`new EventSource('/api/events')` in features/activity/JobsProvider.tsx.

Wire format (match mocks/sse.ts exactly; every frame is per-viewer — gated by
the visibility predicate in services/jobs.py):
    on connect  -> event: job.snapshot    {jobs: [...]}  (the viewer's live hunts)
    per event   -> event: job.event       JobEvent       (id: "<job_id>:<seq>")
    lifecycle   -> event: job.started / job.finished / job.failed  {job: Job}
    per check   -> event: listing.checked ListingChecked

Rechecks emit no lifecycle frames and write no events: their whole output is
the listing.checked frame. Backed by services/events.py (Postgres
LISTEN/NOTIFY hub); the frame list above is the whole wire contract.
nginx.conf already disables buffering + extends timeouts for this path. Auth
rides the access cookie — EventSource can't send headers, which is why auth is
cookies in the first place; an expired cookie 401s the reconnect and the
client shows "reconnecting" until any refreshed request restores it.
"""

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from sse_starlette import EventSourceResponse

from app.core.deps import current_user
from app.services import events as events_service

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events")
async def stream_events(request: Request, user=Depends(current_user)) -> EventSourceResponse:
    """Open the caller's SSE stream: a job.snapshot first, then live frames.
    The stream closes once its viewer is deactivated, demoted or signed out
    (see services/events.py)."""
    # current_user leaves whichever credential it accepted on the request
    api_token = getattr(request.state, "api_token", None)
    client = events_service.register_client(
        user,
        family_id=getattr(request.state, "session_family", None),
        token_id=api_token.id if api_token is not None else None,
    )
    # captured before streaming starts — the ORM row detaches with the request
    user_id, is_admin = user.id, user.role == "admin"

    async def stream() -> AsyncIterator[dict]:
        # snapshot queried inside the generator: the request-scoped session
        # would be long gone by the time an SSE body starts streaming
        try:
            yield await events_service.snapshot_message(user_id, is_admin)
            loop = asyncio.get_running_loop()
            next_check = loop.time() + events_service.REAUTH_SECONDS
            while True:
                try:
                    message = await asyncio.wait_for(
                        client.queue.get(), timeout=max(0, next_check - loop.time())
                    )
                except TimeoutError:
                    message = None
                if loop.time() >= next_check:
                    # checked before the frame goes out, so a revoked viewer
                    # never gets one more
                    if not await events_service.still_authorized(client):
                        return
                    next_check = loop.time() + events_service.REAUTH_SECONDS
                if message is not None:
                    yield message
        finally:
            events_service.unregister_client(client)

    return EventSourceResponse(stream())
