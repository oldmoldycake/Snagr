"""Run lifecycle — enqueue, scope resolution, status transitions (Phase 3, D3).

Responsibilities:
  - resolve_scope(scope, scope_id): validate the target exists (404) and build
    the human scope_label ("Everything" / "Category: X" / "Site: Y" / "Item: Z").
  - enqueue_run(): 409 run_in_progress (with error.run_id) if a run is already
    queued/running; else insert agent_runs row status='queued' and NOTIFY.
  - cancel_run(): mark cancelled, emit the run.finished event.

Plain reads (list/get) live in routers/runs.py — thin CRUD stays in routers.

The agent (agent/*.py) is the CONSUMER: it claims queued rows
(SELECT ... FOR UPDATE SKIP LOCKED), runs, and writes run_events + updates
status/stats/last_seq. This module only produces/queries rows. Cancellation
of a RUNNING run is cooperative: cancel_run() only flips the row, and the
agent must re-check status between units of work and abort when it reads
'cancelled' — that check lands with the agent consumer work.
"""

# TODO: resolve_scope() and enqueue_run() land with trigger_run.

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import err
from app.models import AgentRuns, RunEvents


async def cancel_run(db: AsyncSession, run_id: int) -> AgentRuns:
    """Mark a queued/running run cancelled and append its terminal run_events row.

    Raises 404 not_found / 409 not_active (matching handlers.ts); commits on
    success and returns the updated row.
    """
    # FOR UPDATE serializes against the agent claiming/finishing this run —
    # otherwise the seq bump below could collide with the agent's (uq_run_seq)
    run = await db.get(AgentRuns, run_id, with_for_update=True)
    if run is None:
        raise err(404, "not_found", f"Run {run_id} does not exist")
    if run.status not in ("queued", "running"):
        raise err(409, "not_active", "This run has already finished")

    now = datetime.now(UTC)
    run.status = "cancelled"
    run.finished_at = now
    run.last_seq += 1
    db.add(
        RunEvents(
            run_id=run.id,
            seq=run.last_seq,
            ts=now,
            level="warn",
            event_type="run_finished",
            message="Run cancelled",
            payload=None,
        )
    )
    await db.commit()
    return run
