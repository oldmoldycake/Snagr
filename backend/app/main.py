"""FastAPI application entrypoint.

Wires up: the error-envelope exception handler and every domain router.
Run: `uvicorn app.main:app --reload --port 8000`

As each router is filled in, its endpoints go live. Until then they return
404 — which doubles as your build checklist against frontend endpoints.ts.
"""

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.core.errors import ApiError, api_error_handler
from app.routers import (
    admin,
    auth,
    categories,
    charts,
    events,
    instance,
    items,
    me,
    runs,
    sites,
    vision,
)
from app.services import events as events_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """The SSE hub's LISTEN connection lives for the app's lifetime."""
    listener = asyncio.create_task(events_service.listen_pg())
    yield
    listener.cancel()
    with suppress(asyncio.CancelledError):
        await listener


app = FastAPI(title="Snagr API", version="0.1.0", lifespan=lifespan)

app.add_exception_handler(ApiError, api_error_handler)

for router in (
    instance.router,
    auth.router,
    me.router,
    categories.router,
    sites.router,
    items.router,
    charts.router,
    runs.router,
    events.router,
    admin.router,
    vision.router,
):
    app.include_router(router)
