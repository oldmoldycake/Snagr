"""Run lifecycle — enqueue, scope resolution, status transitions (Phase 3, D3).

Responsibilities:
  - resolve_scope(scope, scope_id): validate the target exists (404) and build
    the human scope_label ("Everything" / "Category: X" / "Site: Y" / "Item: Z").
  - enqueue_run(): 409 run_in_progress (with error.run_id) if a run is already
    queued/running; else insert agent_runs row status='queued'. (The NOTIFY that
    wakes the SSE hub lands with services/events.py — nothing listens yet.)
  - cancel_run(): mark cancelled, emit the run.finished event.

Plain reads (list/get) live in routers/runs.py — thin CRUD stays in routers.

The agent (agent/*.py) is the CONSUMER: it claims queued rows
(SELECT ... FOR UPDATE SKIP LOCKED), runs, and writes run_events + updates
status/stats/last_seq. This module only produces/queries rows. Cancellation
of a RUNNING run is cooperative: cancel_run() only flips the row, and the
agent must re-check status between units of work and abort when it reads
'cancelled' — that check lands with the agent consumer work.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import err
from app.models import AgentRuns, Categories, Items, Listings, RunEvents, Sites, User, Watches
from app.schemas.runs import AgentRun, RunEvent


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
