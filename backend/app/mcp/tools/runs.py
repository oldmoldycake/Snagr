"""Run tools — the agent's job history. Reads only here; trigger/cancel land
with the write surface and its `runs` scope."""

from fastmcp import FastMCP

from app.mcp.schemas import RunDetail
from app.mcp.server import READ_ONLY, caller_session
from app.schemas.common import Paginated
from app.schemas.runs import AgentRun, RunListParams, RunScope, RunStatus
from app.services import runs as runs_service
from app.services.runs import build_agent_run

# get_run tails the log rather than paging it: an agent wants "what happened",
# not a cursor. The REST backfill route serves reconnecting UIs.
RUN_TAIL = 50


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def list_runs(
        status: RunStatus | None = None,
        scope: RunScope | None = None,
        page: int = 1,
        per_page: int = 25,
    ) -> Paginated[AgentRun]:
        """Agent runs this user may see — their own plus system runs (admins
        see everyone's) — newest first, with scope, status (queued | running |
        succeeded | failed | cancelled), timings and result counts."""
        async with caller_session() as (db, user):
            filters = RunListParams(status=status, scope=scope, page=page, per_page=per_page)
            return await runs_service.list_runs(db, user, filters)

    @mcp.tool(annotations=READ_ONLY)
    async def get_run(run_id: int) -> RunDetail:
        """One run with the last 50 log events this user may see — sites and
        items visited, listings found or rejected, errors. A run you can't see
        is `not_found`, exactly like one that never existed."""
        async with caller_session() as (db, user):
            run = await runs_service.visible_run_or_404(db, run_id, user)
            events = await runs_service.visible_events(
                db, run, user, after_seq=0, limit=run.last_seq
            )
            return RunDetail(**build_agent_run(run).model_dump(), events=events[-RUN_TAIL:])
