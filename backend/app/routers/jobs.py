"""The hunter's work queue — /api/jobs. Auth required.

POST /api/jobs is how a person asks for something ("hunt this category",
"check this item's prices"); the agent daemon claims the rows and does the
work. Live progress is pushed over /api/events (routers/events.py); the
/events sub-route here is the polling backfill for SSE reconnects.

Every behaviour lives in services/jobs.py, because the MCP tools are the
other caller and the two must never disagree about what a viewer may see.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import csrf_guard, current_user, require_scope
from app.core.errors import err
from app.database import get_db
from app.schemas.common import DataList, Paginated
from app.schemas.jobs import Job, JobCreateRequest, JobEvent, JobListParams, JobsSummary
from app.services import jobs as jobs_service

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post(
    "",
    response_model=DataList[Job],
    # 202, not 201 — handlers.ts returns 202 and the mock is the oracle
    status_code=status.HTTP_202_ACCEPTED,
    # a hunt spends LLM money, so API tokens need the dedicated `jobs` scope
    dependencies=[Depends(csrf_guard), Depends(require_scope("jobs"))],
)
async def enqueue_jobs(
    body: JobCreateRequest, user=Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """Queue hunts or rechecks for a scope; 202 with the jobs now open for it.

    Asking again brings an already-queued job forward instead of adding a second
    one. 404 when the scope holds none of the caller's watches; 409
    hunting_disabled for a hunt while HUNT_ENABLED is off. API tokens need the
    `jobs` scope."""
    try:
        queued = await jobs_service.enqueue(db, user, body.kind, body.scope, body.scope_id)
        return DataList(data=queued)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.get("", response_model=Paginated[Job])
async def list_jobs(
    filters: Annotated[JobListParams, Query()],
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """The jobs the caller may see, filtered and paged."""
    try:
        return await jobs_service.list_jobs(db, user, filters)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


# before /{id}: "summary" would otherwise be parsed as a job id
@router.get("/summary", response_model=JobsSummary)
async def jobs_summary(user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    """The queue at a glance: running and pending counts, next check and hunt,
    paused sites."""
    try:
        return await jobs_service.summary(db, user)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.get("/{job_id}", response_model=Job)
async def get_job(job_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    """One job; a job the caller may not see 404s like a missing one."""
    try:
        return await jobs_service.get_job(db, job_id, user)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.get("/{job_id}/events", response_model=DataList[JobEvent])
async def get_job_events(
    job_id: int,
    after_seq: int = 0,
    limit: int = 200,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """A job's events after `after_seq` — the backfill for an SSE reconnect.
    422 validation_error when `limit` exceeds MAX_EVENTS."""
    if limit > jobs_service.MAX_EVENTS:
        raise err(
            422,
            "validation_error",
            f"limit must be {jobs_service.MAX_EVENTS} or less",
            fields={"limit": f"limit must be {jobs_service.MAX_EVENTS} or less"},
        )
    try:
        job = await jobs_service.visible_job_or_404(db, job_id, user)
        return DataList(data=await jobs_service.visible_events(db, job, after_seq, limit))
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.post(
    "/{job_id}/cancel",
    response_model=Job,
    dependencies=[Depends(csrf_guard), Depends(require_scope("jobs"))],
)
async def cancel_job(job_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Cancel a pending or running hunt.

    404 for a job the caller may not see, 403 forbidden for one they don't own
    unless admin, 422 for a recheck, 409 job_finished once terminal. A running hunt
    stops at its next model step. API tokens need the `jobs` scope."""
    try:
        return await jobs_service.cancel_job(db, job_id, user)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e
