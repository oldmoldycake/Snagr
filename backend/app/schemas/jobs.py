"""Job schemas — mirror the "Jobs" and "SSE stream" blocks of types.ts.

A job is one unit of the hunter's work: a `hunt` searches a (watch, site)
pair with the model, a `recheck` re-reads one listing's price without one, a
`ground` refreshes an item's market stats.

The SSE stream (routers/events.py) emits JobEvent and ListingChecked objects
plus a job.snapshot on connect — see mocks/sse.ts for the exact wire format.
"""

from typing import Literal

from pydantic import BaseModel

JobKind = Literal["hunt", "recheck", "ground"]
JobStatus = Literal["pending", "running", "done", "failed", "cancelled"]
# the scope vocabulary a user asks in — the four the UI has always offered
JobScope = Literal["global", "category", "site", "item"]
JobEventLevel = Literal["info", "success", "warn", "error"]
JobEventType = Literal[
    "job_started",
    "listing_check",
    # candidate scored vs criteria — payload: url, title, match_score, match_summary, tracked
    "listing_evaluated",
    "price_found",
    "listing_discovered",
    "listing_ended",  # tracked listing sold/ended; slot freed — payload: listing_id, item_id
    "site_paused",  # the breaker tripped — payload: site_id, paused_until, paused_reason
    "error",
    "job_finished",
]


class JobStats(BaseModel):
    """A job's terminal tally. Every field has a default because the agent
    writes this as JSON: a row from an older worker, or one that failed before
    it could count anything, still serializes to the shape the UI reads."""

    listings_checked: int = 0
    prices_found: int = 0
    new_listings: int = 0
    errors: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int | None = None
    method: str | None = None  # recheck only: llm | jsonld | meta | microdata | locator
    transport: Literal["static", "browser"] | None = None  # recheck only


class Job(BaseModel):
    id: int
    kind: JobKind
    status: JobStatus
    user_id: int | None  # None = the hunter queued it itself; shown as "system"
    watch_id: int | None
    item_id: int | None
    item_name: str | None
    site_id: int | None
    site_name: str | None
    listing_id: int | None
    # "Game Boy Color × eBay" (hunt) · "… · check" (recheck) · "… · market price" (ground)
    label: str
    priority: int
    run_after: str  # the queue sorts pending jobs by this
    attempts: int
    started_at: str | None
    finished_at: str | None
    error: str | None  # one sentence for a human
    stats: JobStats | None
    reason: str | None  # user | created | slot_freed | sweep | paused
    last_seq: int  # highest event seq written so far (hunts and ground only)
    created_at: str


class PausedSite(BaseModel):
    site_id: int
    site_name: str
    paused_until: str
    paused_reason: str


class JobsSummary(BaseModel):
    """The presence sentence, the ticker and the queue's checks line all read
    this one object."""

    hunts_running: int
    checks_running: int
    checks_pending: int
    next_check_at: str | None
    next_hunt_at: str | None
    hunts_today: int
    listings_watched: int
    last_hunt: Job | None
    paused_sites: list[PausedSite]


# kind/scope are loose here: the contract's 422 validation_error envelope
# (fields.kind / fields.scope / fields.scope_id) is what the mock answers, so
# the service validates them itself instead of letting Pydantic reply with
# FastAPI's default detail shape (the ApiTokenCreateRequest precedent).
class JobCreateRequest(BaseModel):
    kind: str | None = None
    scope: str | None = None
    scope_id: int | None = None  # required unless scope is global


class JobListParams(BaseModel):
    page: int | None = None
    per_page: int | None = None
    kind: str | None = None  # one kind or a comma-separated list
    status: str | None = None  # one status or a comma-separated list
    item_id: int | None = None


class JobEvent(BaseModel):
    job_id: int
    seq: int
    ts: str
    level: JobEventLevel
    event_type: JobEventType
    message: str
    payload: dict | None


class JobEnvelope(BaseModel):
    """A lifecycle SSE frame: {"job": Job}."""

    job: Job


class JobSnapshotData(BaseModel):
    """The connect snapshot: every non-terminal hunt and ground job the viewer
    may see. Rechecks are not in it — they have no events and are over in
    seconds."""

    jobs: list[Job]


class ListingChecked(BaseModel):
    """One recheck result, as the SSE frame carries it. Built from the
    price_checks row the trigger announced, whichever path read it."""

    listing_id: int
    item_id: int
    item_name: str
    site_name: str
    price: str | None
    currency: str
    status: str | None
    method: str | None
    confirmed: bool
    slot_freed: bool  # this check ended or sold the listing and a slot opened
    checked_at: str
