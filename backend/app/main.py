"""FastAPI application entrypoint.

Wires up: the error-envelope exception handler, every domain router, the MCP
sub-app (when MCP_ENABLED), and the two lifetime tasks (SSE hub, notification
dispatcher).
Run: `uvicorn app.main:app --reload --port 8000`

As each router is filled in, its endpoints go live. Until then they return
404 — which doubles as your build checklist against frontend endpoints.ts.
"""

import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastmcp.utilities.lifespan import combine_lifespans

from app.config import settings
from app.core.errors import ApiError, api_error_handler
from app.mcp.server import MCP_PATH, build_mcp_app
from app.routers import (
    admin,
    auth,
    categories,
    charts,
    events,
    instance,
    items,
    jobs,
    me,
    sites,
    vision,
)
from app.services import events as events_service
from app.services import notifications as notifications_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """The SSE hub's LISTEN connection and the notification dispatcher both
    live for the app's lifetime."""
    tasks = [
        asyncio.create_task(events_service.listen_pg()),
        asyncio.create_task(notifications_service.listen_pg()),
    ]
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task


# The MCP endpoint is a Starlette sub-app with its own lifespan (the session
# manager). It is registered as an exact-path route, not mounted — a Mount
# 307-redirects /api/mcp to /api/mcp/, which not every client follows.
mcp_app = build_mcp_app()

app = FastAPI(
    title="Snagr API",
    version="0.1.0",
    lifespan=combine_lifespans(lifespan, mcp_app.lifespan) if settings.MCP_ENABLED else lifespan,
)

app.add_exception_handler(ApiError, api_error_handler)

if settings.MCP_ENABLED:
    app.add_route(MCP_PATH, mcp_app, methods=["GET", "POST", "DELETE"])

for router in (
    instance.router,
    auth.router,
    me.router,
    categories.router,
    sites.router,
    items.router,
    charts.router,
    jobs.router,
    events.router,
    admin.router,
    vision.router,
):
    app.include_router(router)
