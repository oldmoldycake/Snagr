"""Run tools — the agent's job history, and starting or stopping a run."""

from fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import err
from app.mcp.refs import Ref, resolve_category, resolve_site
from app.mcp.schemas import RunDetail
from app.mcp.server import READ_ONLY, RUNS, caller_session
from app.schemas.common import Paginated
from app.schemas.runs import AgentRun, RunListParams, RunScope, RunStatus
from app.services import runs as runs_service
from app.services.runs import build_agent_run

# get_run tails the log rather than paging it: an agent wants "what happened",
# not a cursor. The REST backfill route serves reconnecting UIs.
RUN_TAIL = 50


async def _scope_id(db: AsyncSession, scope: str, target: Ref | None) -> int | None:
    """The scope_id for a run request from the agent's loose reference."""
    if scope == "global" or target is None:
        return None
    if scope == "category":
        return (await resolve_category(db, target)).id
    if scope == "site":
        return (await resolve_site(db, target)).id
    if isinstance(target, int) or target.strip().isdigit():
        return int(target)
    raise err(422, "validation_error", "Items are addressed by id", fields={"target": "Not an id"})


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

    @mcp.tool(auth=RUNS)
    async def trigger_run(scope: RunScope = "global", target: Ref | None = None) -> AgentRun:
        """Start an agent run now: it re-checks every tracked listing's price
        and availability, then searches the sites for new listings. A run
        spends LLM tokens and takes minutes, and only one runs at a time
        instance-wide — don't call this in a loop.

        Args:
          scope: global (everything) | category | site | item
          target: for a non-global scope — the category (id or slug), the
            site (id or name) or the item (id)
        Errors: `run_in_progress` (carrying run_id) while another run is
        queued or running — wait for it or cancel it; `not_found` for an
        unknown target.
        """
        async with caller_session() as (db, user):
            scope_id = await _scope_id(db, scope, target)
            run = await runs_service.enqueue_run(db, scope, scope_id, user.id)
            return build_agent_run(run)

    @mcp.tool(auth=RUNS)
    async def cancel_run(run_id: int) -> AgentRun:
        """Cancel one of this user's queued or running runs (admins: any run).
        Errors: `not_found` for a run you can't see, `forbidden` for a system
        run unless you're admin, `not_active` once it has already finished."""
        async with caller_session() as (db, user):
            return build_agent_run(await runs_service.cancel_run(db, run_id, user))
