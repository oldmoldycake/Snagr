"""Run lifecycle — enqueue, scope resolution, status transitions (Phase 3, D3).

Responsibilities:
  - resolve_scope(scope, scope_id): validate the target exists (404) and build
    the human scope_label ("Everything" / "Category: X" / "Site: Y" / "Item: Z").
  - enqueue_run(): 409 run_in_progress (with error.run_id) if a run is already
    queued/running; else insert agent_runs row status='queued'. Migration 007's
    trigger NOTIFYs on commit and services/events.py fans it out to SSE clients.
  - cancel_run(): mark cancelled, emit the run.finished event.

The reads (list_runs / visible_run_or_404 / visible_events) live here too
since the REST router and the MCP tools both need them.

The agent (agent/*.py) is the CONSUMER: it claims queued rows
(SELECT ... FOR UPDATE SKIP LOCKED), runs, and writes run_events + updates
status/stats/last_seq. This module only produces/queries rows. Cancellation
of a RUNNING run is cooperative: cancel_run() only flips the row, and the
agent re-checks status between units of work and aborts when it reads
'cancelled' (agent/agent.py, around each listing and each watch).
"""

from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import err
from app.models import AgentRuns, Categories, Items, Listings, RunEvents, Sites, User, Watches
from app.schemas.common import PageMeta, Paginated
from app.schemas.runs import AgentRun, RunEvent, RunListParams


def build_agent_run(run: AgentRuns) -> AgentRun:
    """One agent_runs row -> AgentRun. Shared by routers/runs.py and the SSE hub."""
    return AgentRun(
        id=run.id,
        user_id=run.user_id,
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


def build_run_event(event: RunEvents) -> RunEvent:
    """One run_events row -> RunEvent. Shared by routers/runs.py and the SSE hub."""
    return RunEvent(
        run_id=event.run_id,
        seq=event.seq,
        ts=event.ts.isoformat(),
        level=event.level,
        event_type=event.event_type,
        message=event.message,
        payload=event.payload,
    )


# --- visibility (per-user run privacy) ----------------------------------------
# ONE predicate for every surface: routers/runs.py (list/detail/backfill/cancel)
# and the SSE hub (services/events.py) both call these — the REST and push
# channels must never disagree about what a viewer may see. Composition rule:
# run_visible gates first; event_visible filters only WITHIN a visible run.


def run_visible(run: AgentRuns, viewer_id: int, is_admin: bool) -> bool:
    """A viewer sees their own runs, system runs (user_id NULL), and — as
    admin — everything. A hidden run must behave exactly like a nonexistent
    one (404, absent from lists) so its existence never leaks."""
    return is_admin or run.user_id is None or run.user_id == viewer_id


async def load_viewer_refs(db: AsyncSession, viewer_id: int) -> tuple[set[int], set[int]]:
    """The viewer's (watched item_ids, owned listing_ids) — the two sets
    event_visible keys on. Two small indexed queries; callers load once per
    request/notification rather than caching (household scale)."""
    items = (
        await db.execute(select(Watches.item_id).where(Watches.user_id == viewer_id))
    ).scalars()
    listings = (
        await db.execute(
            select(Listings.id)
            .join(Watches, Listings.watch_id == Watches.id)
            .where(Watches.user_id == viewer_id)
        )
    ).scalars()
    return set(items), set(listings)


def event_visible(
    event: RunEvents, watched_item_ids: set[int], owned_listing_ids: set[int]
) -> bool:
    """Event-level rule, applied only within runs the viewer can already see:
    a payload with no item/listing reference (lifecycle, sweep counts) shows to
    every viewer of the run; an item reference shows to that item's watchers
    (a shared catalog item legitimately has several); a listing reference only
    to the listing's owner (listings are per-watch). Admins skip this check."""
    payload = event.payload or {}
    item_id = payload.get("item_id")
    listing_id = payload.get("listing_id")
    if item_id is None and listing_id is None:
        return True
    return item_id in watched_item_ids or listing_id in owned_listing_ids


async def resolve_scope(db: AsyncSession, scope: str, scope_id: int | None) -> str:
    """Validate the scope target exists and build the human scope_label.

    Raises 404 not_found when a scoped target is missing (matching handlers.ts);
    `global` never fails and ignores scope_id.
    """
    if scope == "global":
        return "Everything"

    # `item` resolves the shared catalog, not the caller's watches — any user
    # may target any catalog item; the run itself is stamped with its creator
    kinds = {"category": (Categories, "Category"), "site": (Sites, "Site"), "item": (Items, "Item")}
    model, noun = kinds[scope]
    # db.get() rejects a None ident, so a missing scope_id is a missing target
    target = await db.get(model, scope_id) if scope_id is not None else None
    if target is None:
        raise err(404, "not_found", f"{noun} {scope_id} does not exist")
    return f"{noun}: {target.name}"


async def enqueue_run(
    db: AsyncSession, scope: str, scope_id: int | None, user_id: int
) -> AgentRuns:
    """Insert a queued agent_runs row, owned by the caller, for the agent to claim.

    Raises 409 run_in_progress (with error.run_id) if any run is queued or
    running — one active run at a time, instance-wide (there is a single agent
    worker), even when the active run belongs to someone else. Commits on
    success and returns the new row.
    """
    # active check before scope validation — handlers.ts checks hasActiveRun()
    # before even reading the body
    active = (
        await db.execute(
            select(AgentRuns).where(AgentRuns.status.in_(("queued", "running"))).limit(1)
        )
    ).scalar_one_or_none()
    if active is not None:
        raise err(409, "run_in_progress", "A run is already active", run_id=active.id)

    # The check-then-insert race is benign: a single-instance app, and the agent
    # claims oldest-first anyway. A DB-level guard needs a partial unique index
    # (= a migration) — not worth it for a button double-click.
    label = await resolve_scope(db, scope, scope_id)
    run = AgentRuns(user_id=user_id, scope=scope, scope_id=scope_id, scope_label=label)
    db.add(run)
    await db.commit()
    # created_at is a server default; the async ORM can't lazy-fetch it later
    await db.refresh(run)
    return run


async def cancel_run(db: AsyncSession, run_id: int, viewer: User) -> AgentRuns:
    """Mark a queued/running run cancelled and append its terminal run_events row.

    Raises 404 not_found for unknown AND hidden runs (never confirm another
    user's run exists), 403 forbidden for a system run and a non-admin caller,
    409 not_active for finished runs (matching handlers.ts); commits on
    success and returns the updated row.
    """
    # FOR UPDATE serializes against the agent claiming/finishing this run —
    # otherwise the seq bump below could collide with the agent's (uq_run_seq)
    run = await db.get(AgentRuns, run_id, with_for_update=True)
    is_admin = viewer.role == "admin"
    if run is None or not run_visible(run, viewer.id, is_admin):
        raise err(404, "not_found", f"Run {run_id} does not exist")
    # permission before state: "you may never cancel this" holds regardless of
    # status. A visible non-system run is the caller's own (or they're admin).
    if run.user_id is None and not is_admin:
        raise err(403, "forbidden", "Only an admin can cancel a system run")
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


# --- reads --------------------------------------------------------------------


async def list_runs(db: AsyncSession, viewer: User, filters: RunListParams) -> Paginated[AgentRun]:
    """The runs the viewer may see, newest first, paged."""
    page = filters.page or 1
    per_page = filters.per_page or 25

    # per-user run privacy: own runs + system runs (user_id NULL); admins
    # see everything. Same rule as run_visible, in SQL form because
    # meta.total has to count post-filter in the database.
    stmt = select(AgentRuns)
    if viewer.role != "admin":
        stmt = stmt.where(or_(AgentRuns.user_id.is_(None), AgentRuns.user_id == viewer.id))
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


async def visible_run_or_404(db: AsyncSession, run_id: int, viewer: User) -> AgentRuns:
    """The run row, or 404 — hidden ≡ nonexistent: another user's run 404s
    exactly like an unknown id."""
    run = await db.get(AgentRuns, run_id)
    if run is None or not run_visible(run, viewer.id, viewer.role == "admin"):
        raise err(404, "not_found", f"Run {run_id} does not exist")
    return run


async def visible_events(
    db: AsyncSession, run: AgentRuns, viewer: User, after_seq: int = 0, limit: int = 500
) -> list[RunEvent]:
    """Up to `limit` events of a visible run that the viewer may see, in seq order."""
    # filter-then-limit: up to `limit` VISIBLE events, so a filtered viewer
    # always advances from their last visible seq (limit-then-filter could
    # return [] forever once their events fall past the fetch window)
    stmt = (
        select(RunEvents)
        .where(RunEvents.run_id == run.id)
        .where(RunEvents.seq > after_seq)
        .order_by(RunEvents.seq)
    )
    rows = (await db.execute(stmt)).scalars().all()
    if viewer.role != "admin":
        refs = await load_viewer_refs(db, viewer.id)
        rows = [event for event in rows if event_visible(event, *refs)]
    return [build_run_event(event) for event in rows[:limit]]
