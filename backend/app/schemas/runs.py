"""Agent-run schemas — mirror the "Agent runs" + "SSE stream" blocks of types.ts.

The SSE stream (routers/events.py) emits RunEvent objects plus a run.snapshot
on connect — see mocks/sse.ts for the exact wire format.
"""

from typing import Literal

from pydantic import BaseModel

RunScope = Literal["global", "category", "site", "item"]
RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
RunEventLevel = Literal["info", "success", "warn", "error"]
RunEventType = Literal[
    "run_started",
    "site_started",
    "item_started",
    "listing_check",
    "price_found",
    "listing_evaluated",  # candidate scored vs criteria — payload: url, title, match_score, match_summary, tracked
    "listing_discovered",
    "listing_ended",  # tracked listing sold/ended; slot freed — payload: listing_id, item_id
    "error",
    "run_finished",
]


class RunStats(BaseModel):
    listings_checked: int
    prices_found: int
    new_listings: int
    errors: int


class AgentRun(BaseModel):
    id: int
    scope: RunScope
    scope_id: int | None
    scope_label: str  # "Everything" | "Category: X" | "Site: Y" | "Item: Z"
    status: RunStatus
    started_at: str | None
    finished_at: str | None
    stats: RunStats | None
    error: str | None
    created_at: str
    last_seq: int  # highest event seq written so far


class RunEnvelope(BaseModel):
    """triggerRun response: {"run": AgentRun}."""

    run: AgentRun


class RunCreateRequest(BaseModel):
    scope: RunScope
    scope_id: int | None = None


class RunEvent(BaseModel):
    run_id: int
    seq: int
    ts: str
    level: RunEventLevel
    event_type: RunEventType
    message: str
    payload: dict | None


class RunListParams(BaseModel):
    status: RunStatus | None = None
    scope: RunScope | None = None
    page: int | None = None
    per_page: int | None = None


class RunSnapshotEntry(BaseModel):
    """One active run in the connect snapshot (a subset of AgentRun)."""

    id: int
    status: RunStatus
    scope: RunScope
    scope_label: str
    last_seq: int


class RunSnapshotData(BaseModel):
    active_runs: list[RunSnapshotEntry]
