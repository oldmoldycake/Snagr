"""Agent runs — /api/runs  (Phase 3). Auth required.

triggerRun enqueues (status='queued') per Decision D3; the agent claims it.
Live progress is pushed over /api/events (routers/events.py); the /events
sub-route here is the polling backfill for SSE reconnects.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import csrf_guard, current_user
from app.database import get_db
from app.schemas.common import DataList, Paginated
from app.schemas.runs import (
    AgentRun,
    RunCreateRequest,
    RunEnvelope,
    RunEvent,
    RunListParams,
)

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("", response_model=RunEnvelope, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(csrf_guard)])
async def trigger_run(body: RunCreateRequest, user=Depends(current_user),
                      db: AsyncSession = Depends(get_db)):
    # 409 run_in_progress (error.run_id = active run) if one is queued/running
    raise NotImplementedError


@router.get("", response_model=Paginated[AgentRun])
async def list_runs(filters: Annotated[RunListParams, Query()], user=Depends(current_user),
                    db: AsyncSession = Depends(get_db)):
    raise NotImplementedError


@router.get("/{run_id}", response_model=AgentRun)
async def get_run(run_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    # 404 not_found
    raise NotImplementedError


@router.get("/{run_id}/events", response_model=DataList[RunEvent])
async def get_run_events(run_id: int, after_seq: int = 0, limit: int = 500,
                         user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    raise NotImplementedError


@router.post("/{run_id}/cancel", response_model=AgentRun, dependencies=[Depends(csrf_guard)])
async def cancel_run(run_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    raise NotImplementedError
