"""Agent runs — /api/runs  (Phase 3). Auth required.

triggerRun enqueues (status='queued') per Decision D3; the agent claims it.
Live progress is pushed over /api/events (routers/events.py); the /events
sub-route here is the polling backfill for SSE reconnects.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import csrf_guard, current_user
from app.core.errors import err
from app.database import get_db
from app.models import AgentRuns, RunEvents
from app.schemas.common import DataList, PageMeta, Paginated
from app.schemas.runs import (
    AgentRun,
    RunCreateRequest,
    RunEnvelope,
    RunEvent,
    RunListParams,
)
from app.services import runs as runs_service
from app.services.runs import build_agent_run, build_run_event

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post(
    "",
    response_model=RunEnvelope,
    # 202, not 201 — handlers.ts returns 202 and the mock is the oracle
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(csrf_guard)],
)
async def trigger_run(
    body: RunCreateRequest, user=Depends(current_user), db: AsyncSession = Depends(get_db)
):
    try:
        run = await runs_service.enqueue_run(db, body.scope, body.scope_id, user.id)
        return RunEnvelope(run=build_agent_run(run))
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.get("", response_model=Paginated[AgentRun])
async def list_runs(
    filters: Annotated[RunListParams, Query()],
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        page = filters.page or 1
        per_page = filters.per_page or 25

        # per-user run privacy: own runs + system runs (user_id NULL); admins
        # see everything. Same rule as services.runs.run_visible, in SQL form
        # because meta.total has to count post-filter in the database.
        stmt = select(AgentRuns)
        if user.role != "admin":
            stmt = stmt.where(or_(AgentRuns.user_id.is_(None), AgentRuns.user_id == user.id))
        if filters.status is not None:
            stmt = stmt.where(AgentRuns.status == filters.status)
        # handlers.ts ignores `scope`, but RunListParams sends it — honor the contract
        if filters.scope is not None:
            stmt = stmt.where(AgentRuns.scope == filters.scope)

        total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

        rows = (
            (
                await db.execute(
                    stmt.order_by(AgentRuns.created_at.desc(), AgentRuns.id.desc())
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                )
            )
            .scalars()
            .all()
        )

        return Paginated(
            data=[build_agent_run(run) for run in rows],
            meta=PageMeta(page=page, per_page=per_page, total=total),
        )
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.get("/{run_id}", response_model=AgentRun)
async def get_run(run_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        run = await db.get(AgentRuns, run_id)

        # hidden ≡ nonexistent: another user's run 404s exactly like an unknown id
        if run is None or not runs_service.run_visible(run, user.id, user.role == "admin"):
            raise err(404, "not_found", f"Run {run_id} does not exist")

        return build_agent_run(run)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.get("/{run_id}/events", response_model=DataList[RunEvent])
async def get_run_events(
    run_id: int,
    after_seq: int = 0,
    limit: int = 500,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        run = await db.get(AgentRuns, run_id)
        is_admin = user.role == "admin"
        if run is None or not runs_service.run_visible(run, user.id, is_admin):
            raise err(404, "not_found", f"Run {run_id} does not exist")

        # filter-then-limit: up to `limit` VISIBLE events, so a filtered viewer
        # always advances from their last visible seq (limit-then-filter could
        # return [] forever once their events fall past the fetch window)
        stmt = (
            select(RunEvents)
            .where(RunEvents.run_id == run_id)
            .where(RunEvents.seq > after_seq)
            .order_by(RunEvents.seq)
        )
        rows = (await db.execute(stmt)).scalars().all()
        if not is_admin:
            refs = await runs_service.load_viewer_refs(db, user.id)
            rows = [event for event in rows if runs_service.event_visible(event, *refs)]

        return DataList(data=[build_run_event(event) for event in rows[:limit]])
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.post("/{run_id}/cancel", response_model=AgentRun, dependencies=[Depends(csrf_guard)])
async def cancel_run(run_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        run = await runs_service.cancel_run(db, run_id, user)
        return build_agent_run(run)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e
