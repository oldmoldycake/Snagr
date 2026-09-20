"""Job tools — what the hunter is doing, and asking it to do something now."""

from fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import err
from app.mcp.refs import Ref, resolve_category, resolve_site
from app.mcp.schemas import JobDetail
from app.mcp.server import JOBS, READ_ONLY, caller_session
from app.schemas.common import Paginated
from app.schemas.jobs import Job, JobListParams, JobScope, JobsSummary
from app.services import jobs as jobs_service

# get_job tails the log rather than paging it: an agent wants "what happened",
# not a cursor. The REST backfill route serves reconnecting UIs.
EVENT_TAIL = 50


async def _scope_id(db: AsyncSession, scope: str, target: Ref | None) -> int | None:
    """The scope_id for a job request, from the agent's loose reference."""
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
    async def list_jobs(
        kind: str | None = None,
        status: str | None = None,
        item_id: int | None = None,
        page: int = 1,
        per_page: int = 20,
    ) -> Paginated[Job]:
        """The hunter's work you may see: `hunt` (searching a site for one of
        your watches), `recheck` (re-reading one listing's price) and `ground`
        (refreshing an item's market stats), with status (pending | running |
        done | failed | cancelled), timings and result counts.

        Args:
          kind: one kind, or a comma-separated list ("hunt,ground")
          status: one status, or a comma-separated list ("done,failed")
          item_id: only work about this item
        A list of exactly `pending` jobs comes back as a queue — soonest due
        first; anything else is history, newest first."""
        async with caller_session() as (db, user):
            filters = JobListParams(
                kind=kind, status=status, item_id=item_id, page=page, per_page=per_page
            )
            return await jobs_service.list_jobs(db, user, filters)

    @mcp.tool(annotations=READ_ONLY)
    async def jobs_summary() -> JobsSummary:
        """What the hunter is doing right now, in one object: how many hunts
        and checks are running, how many checks are queued and when the next
        one is due, today's hunt count, your last finished hunt, and any site
        the circuit breaker has paused (a paused site is read by nothing until
        its pause lifts)."""
        async with caller_session() as (db, user):
            return await jobs_service.summary(db, user)

    @mcp.tool(annotations=READ_ONLY)
    async def get_job(job_id: int) -> JobDetail:
        """One job with the last 50 lines of its log — what the hunt searched,
        which candidates it judged and why, what it saved, what failed. Checks
        have no log (their whole output is the price check they write). A job
        you can't see is `not_found`, exactly like one that never existed."""
        async with caller_session() as (db, user):
            job = await jobs_service.visible_job_or_404(db, job_id, user)
            events = await jobs_service.visible_events(db, job, 0, jobs_service.MAX_EVENTS)
            detail = await jobs_service.get_job(db, job_id, user)
            return JobDetail(**detail.model_dump(), events=events[-EVENT_TAIL:])

    @mcp.tool(auth=JOBS)
    async def enqueue_jobs(
        kind: str = "hunt", scope: JobScope = "global", target: Ref | None = None
    ) -> list[Job]:
        """Ask the hunter for something now, and get back the jobs it queued.

        `hunt` searches every site of every watch in scope that still has an
        open slot — it spends LLM tokens and takes minutes, so don't call it
        in a loop. `recheck` re-reads the prices of the tracked listings in
        scope, which is cheap and usually finishes in seconds.

        Args:
          kind: hunt | recheck
          scope: global (everything you watch) | category | site | item
          target: for a non-global scope — the category (id or slug), the
            site (id or name) or the item (id)
        Asking twice is asking once: a pair that is already queued is brought
        forward, never duplicated, so there is no "already running" error. An
        empty list means there was nothing to do — every watch in scope is
        full. Errors: `not_found` for a target that does not exist or holds
        none of your watches."""
        async with caller_session() as (db, user):
            scope_id = await _scope_id(db, scope, target)
            return await jobs_service.enqueue(db, user, kind, scope, scope_id)

    @mcp.tool(auth=JOBS)
    async def cancel_job(job_id: int) -> Job:
        """Cancel one of your pending or running hunts (admins: any job). A
        running hunt stops between model steps, so it may write one more thing
        before it does. Errors: `not_found` for a job you can't see,
        `forbidden` for one the hunter queued itself unless you're admin,
        `validation_error` for a check — they finish in seconds — and
        `job_finished` once it is over."""
        async with caller_session() as (db, user):
            return await jobs_service.cancel_job(db, job_id, user)
