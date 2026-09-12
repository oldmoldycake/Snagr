"""Agent runs — /api/runs  (Phase 3). Auth required.

triggerRun enqueues (status='queued') per BACKEND_REQUIREMENTS §7; the agent
worker claims it.
Live progress is pushed over /api/events (routers/events.py); the /events
sub-route here is the polling backfill for SSE reconnects.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import csrf_guard, current_user, require_scope
from app.core.errors import err
from app.database import get_db
from app.schemas.common import DataList, Paginated
from app.schemas.runs import (
    AgentRun,
    RunCreateRequest,
    RunEnvelope,
    RunEvent,
    RunListParams,
)
from app.services import runs as runs_service
from app.services.runs import build_agent_run

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post(
    "",
    response_model=RunEnvelope,
    # 202, not 201 — handlers.ts returns 202 and the mock is the oracle
    status_code=status.HTTP_202_ACCEPTED,
    # a run costs LLM money, so API tokens need the dedicated `runs` scope
    dependencies=[Depends(csrf_guard), Depends(require_scope("runs"))],
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
        return await runs_service.list_runs(db, user, filters)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.get("/{run_id}", response_model=AgentRun)
async def get_run(run_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        return build_agent_run(await runs_service.visible_run_or_404(db, run_id, user))
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
        run = await runs_service.visible_run_or_404(db, run_id, user)
        return DataList(data=await runs_service.visible_events(db, run, user, after_seq, limit))
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.post(
    "/{run_id}/cancel",
    response_model=AgentRun,
    dependencies=[Depends(csrf_guard), Depends(require_scope("runs"))],
)
async def cancel_run(run_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        run = await runs_service.cancel_run(db, run_id, user)
        return build_agent_run(run)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e
