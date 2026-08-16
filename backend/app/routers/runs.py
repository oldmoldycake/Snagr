"""Agent runs — /api/runs  (Phase 3). Auth required.

triggerRun enqueues (status='queued') per Decision D3; the agent claims it.
Live progress is pushed over /api/events (routers/events.py); the /events
sub-route here is the polling backfill for SSE reconnects.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select
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

router = APIRouter(prefix="/api/runs", tags=["runs"])


def build_agent_run(run: AgentRuns) -> AgentRun:
    """One agent_runs row -> AgentRun. Shared by every endpoint in this router."""
    return AgentRun(
        id=run.id,
        scope=run.scope,
        scope_id=run.scope_id,
        scope_label=run.scope_label,
        status=run.status,
        started_at=run.started_at.isoformat() if run.started_at is not None else None,
        finished_at=run.finished_at.isoformat() if run.finished_at is not None else None,
        stats=run.stats,
        error=run.error,
        created_at=run.created_at.isoformat(),
        last_seq=run.last_seq,
    )


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
        run = await runs_service.enqueue_run(db, body.scope, body.scope_id)
        return RunEnvelope(run=build_agent_run(run))
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.get("", response_model=Paginated[AgentRun])
async def list_runs(
    filters: Annotated[RunListParams, Query()],
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    # run history is instance-wide (agent_runs has no user_id) — auth only, no ownership scope
    try:
        page = filters.page or 1
        per_page = filters.per_page or 25

        stmt = select(AgentRuns)
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

        if run is None:
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
    # an unknown run is an empty backfill, not a 404 — handlers.ts never 404s here
    try:
        stmt = (
            select(RunEvents)
            .where(RunEvents.run_id == run_id)
            .where(RunEvents.seq > after_seq)
            .order_by(RunEvents.seq)
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()

        return DataList(
            data=[
                RunEvent(
                    run_id=event.run_id,
                    seq=event.seq,
                    ts=event.ts.isoformat(),
                    level=event.level,
                    event_type=event.event_type,
                    message=event.message,
                    payload=event.payload,
                )
                for event in rows
            ]
        )
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.post("/{run_id}/cancel", response_model=AgentRun, dependencies=[Depends(csrf_guard)])
async def cancel_run(run_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        run = await runs_service.cancel_run(db, run_id)
        return build_agent_run(run)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e
