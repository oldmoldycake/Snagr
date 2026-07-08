"""FastAPI application entrypoint.

Wires up: the error-envelope exception handler and every domain router.
Run: `uvicorn app.main:app --reload --port 8000`

As each router is filled in, its endpoints go live. Until then they return
404 — which doubles as your build checklist against frontend endpoints.ts.
"""

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
)

app = FastAPI(title="Snagr API", version="0.1.0")

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
):
    app.include_router(router)
