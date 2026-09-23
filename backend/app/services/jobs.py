"""The job queue, from the API's side — enqueue, scope expansion, reads, cancel.

The agent owns the queue's mechanics (claiming, retrying, the recheck chain);
this module owns what a *person* can ask of it, and what they are allowed to
see of it. Both write the same table, and the partial unique index on open
jobs is what lets them do that without coordinating: every insert here is
"queue this unless it is already queued".

Visibility is ONE predicate (`visible`), in SQL, used by every surface —
the list (so meta.total counts post-filter in the database), detail, the
events backfill, the summary and cancel, and the SSE hub. A viewer sees jobs
for their own watches and `ground` jobs for items they watch; admins see
everything; a hidden job 404s exactly like an unknown id, so its existence
never leaks. This is peer privacy only: the instance operator can always read
the DB.

Callers: routers/jobs.py, routers/items.py (through services/items.py),
mcp/tools/jobs.py and services/events.py.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select, true, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import err
from app.models import (
    Items,
    JobEvents,
    Jobs,
    Listings,
    SiteCategories,
    Sites,
    User,
    Watches,
    WatchSites,
)
from app.schemas.common import PageMeta, Paginated
from app.schemas.items import HuntFacts, RecheckFacts
from app.schemas.jobs import (
    Job,
    JobEvent,
    JobListParams,
    JobsSummary,
    PausedSite,
)

OPEN_STATUSES = ("pending", "running")
TERMINAL_STATUSES = ("done", "failed", "cancelled")
KINDS = ("hunt", "recheck", "ground")
REQUESTABLE_KINDS = ("hunt", "recheck")
SCOPES = ("global", "category", "site", "item")
# what a person asked for goes to the front of the queue
USER_PRIORITY = 100

MAX_PER_PAGE = 100
MAX_EVENTS = 500


# --- serializers --------------------------------------------------------------


def job_label(kind: str, item_name: str | None, site_name: str | None) -> str:
    """What the row says it is. Kind is said in words, not glyphs."""
    item = item_name or "Unknown item"
    if kind == "hunt":
        return f"{item} × {site_name}" if site_name else item
    if kind == "ground":
        return f"{item} · market price"
    return f"{item} · check"


def build_job(job: Jobs, item_name: str | None, site_name: str | None) -> Job:
    """One jobs row -> Job. Shared by the router, the MCP tools and the SSE hub."""
    return Job(
        id=job.id,
        kind=job.kind,
        status=job.status,
        user_id=job.user_id,
        watch_id=job.watch_id,
        item_id=job.item_id,
        item_name=item_name,
        site_id=job.site_id,
        site_name=site_name,
        listing_id=job.listing_id,
        label=job_label(job.kind, item_name, site_name),
        priority=job.priority,
        run_after=job.run_after.isoformat(),
        attempts=job.attempts,
        started_at=job.started_at.isoformat() if job.started_at is not None else None,
        finished_at=job.finished_at.isoformat() if job.finished_at is not None else None,
        error=job.error,
        stats=job.stats,
        reason=job.reason,
        last_seq=job.last_seq,
        created_at=job.created_at.isoformat(),
    )


def build_job_event(event: JobEvents) -> JobEvent:
    """One job_events row -> JobEvent. Shared by the router and the SSE hub."""
    return JobEvent(
        job_id=event.job_id,
        seq=event.seq,
        ts=event.ts.isoformat(),
        level=event.level,
        event_type=event.event_type,
        message=event.message,
        payload=event.payload,
    )


def _named():
    """The select every read starts from: the job plus the two names its
    label needs. Outer joins — a global job has neither."""
    return (
        select(Jobs, Items.name, Sites.name)
        .outerjoin(Items, Items.id == Jobs.item_id)
        .outerjoin(Sites, Sites.id == Jobs.site_id)
    )


async def _build_rows(rows) -> list[Job]:
    return [build_job(job, item_name, site_name) for job, item_name, site_name in rows]


# --- visibility ---------------------------------------------------------------


def visible_to(user_id: int, is_admin: bool):
    """The one predicate: jobs for this viewer's own watches, plus `ground`
    jobs for items they watch. Admins see everything.

    Takes the identity rather than the row because the SSE hub holds only
    that — and push and backfill must never disagree about what a viewer may
    see."""
    if is_admin:
        return true()
    mine = select(Watches.id).where(Watches.user_id == user_id)
    watched = select(Watches.item_id).where(Watches.user_id == user_id)
    return or_(
        Jobs.watch_id.in_(mine),
        and_(Jobs.watch_id.is_(None), Jobs.item_id.in_(watched)),
    )


def visible(viewer: User):
    """visible_to for a loaded user row — what every REST surface passes."""
    return visible_to(viewer.id, viewer.role == "admin")


async def sees_job(db: AsyncSession, job_id: int, user_id: int, is_admin: bool) -> bool:
    """Whether one viewer may see one job — the push side of `visible_to`.

    One small indexed query per client per frame, looked up fresh rather than
    cached: household scale, and no invalidation coupled to watch mutations.
    """
    return (
        await db.scalar(
            select(Jobs.id).where(Jobs.id == job_id).where(visible_to(user_id, is_admin))
        )
    ) is not None


async def live_jobs(db: AsyncSession, user_id: int, is_admin: bool) -> list[Job]:
    """Every non-terminal hunt and ground job this viewer may see — the
    connect snapshot. Rechecks are left out: they write no events and are
    over in seconds, so a client would only ever see them as history."""
    rows = (
        await db.execute(
            _named()
            .where(visible_to(user_id, is_admin))
            .where(Jobs.kind.in_(("hunt", "ground")))
            .where(Jobs.status.in_(OPEN_STATUSES))
            .order_by(Jobs.id)
        )
    ).all()
    return await _build_rows(rows)


async def named_job(db: AsyncSession, job_id: int) -> Job | None:
    """One job with its names, ungated — the hub filters per viewer itself."""
    row = (await db.execute(_named().where(Jobs.id == job_id))).one_or_none()
    return build_job(*row) if row is not None else None


async def visible_job_or_404(db: AsyncSession, job_id: int, viewer: User) -> Jobs:
    """The job row, or 404 — hidden is nonexistent: another user's job 404s
    exactly like an unknown id."""
    job = await db.scalar(select(Jobs).where(Jobs.id == job_id).where(visible(viewer)))
    if job is None:
        raise err(404, "not_found", f"Job {job_id} does not exist")
    return job


async def _named_or_404(db: AsyncSession, job_id: int, viewer: User) -> Job:
    row = (await db.execute(_named().where(Jobs.id == job_id).where(visible(viewer)))).one_or_none()
    if row is None:
        raise err(404, "not_found", f"Job {job_id} does not exist")
    return build_job(*row)


# --- reads --------------------------------------------------------------------


async def list_jobs(db: AsyncSession, viewer: User, filters: JobListParams) -> Paginated[Job]:
    """The jobs the viewer may see, filtered and paged.

    Order is the one thing here that is not obvious: a list of *pending* jobs
    is a queue and reads forwards, by when each is due; everything else is
    history and reads backwards.
    """
    page = filters.page or 1
    per_page = min(filters.per_page or 20, MAX_PER_PAGE)

    stmt = _named().where(visible(viewer))
    kinds = _csv(filters.kind)
    statuses = _csv(filters.status)
    if kinds:
        stmt = stmt.where(Jobs.kind.in_(kinds))
    if statuses:
        stmt = stmt.where(Jobs.status.in_(statuses))
    if filters.item_id is not None:
        stmt = stmt.where(Jobs.item_id == filters.item_id)

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    order = (
        (Jobs.run_after.asc(), Jobs.id.asc())
        if statuses == ["pending"]
        else (Jobs.created_at.desc(), Jobs.id.desc())
    )
    rows = (
        await db.execute(stmt.order_by(*order).offset((page - 1) * per_page).limit(per_page))
    ).all()

    return Paginated(
        data=await _build_rows(rows),
        meta=PageMeta(page=page, per_page=per_page, total=total),
    )


def _csv(value: str | None) -> list[str]:
    """'done,failed' -> ['done', 'failed']. Empty means "no filter"."""
    return [part for part in (value or "").split(",") if part]


async def get_job(db: AsyncSession, job_id: int, viewer: User) -> Job:
    return await _named_or_404(db, job_id, viewer)


async def visible_events(
    db: AsyncSession, job: Jobs, after_seq: int = 0, limit: int = 200
) -> list[JobEvent]:
    """Up to `limit` of a visible job's events, in seq order.

    No per-event filter, unlike the runs this replaced: a job belongs to one
    watch, so seeing the job is seeing its events. A recheck answers with an
    empty list, because it writes none.
    """
    rows = (
        (
            await db.execute(
                select(JobEvents)
                .where(JobEvents.job_id == job.id)
                .where(JobEvents.seq > after_seq)
                .order_by(JobEvents.seq)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [build_job_event(event) for event in rows]


async def summary(db: AsyncSession, viewer: User) -> JobsSummary:
    """The numbers the Activity page's presence sentence and the ticker read."""
    mine = visible(viewer)

    async def count(*clauses) -> int:
        stmt = select(func.count()).select_from(Jobs).where(mine)
        for clause in clauses:
            stmt = stmt.where(clause)
        return (await db.execute(stmt)).scalar_one()

    async def soonest(*clauses) -> str | None:
        stmt = select(func.min(Jobs.run_after)).where(mine).where(Jobs.status == "pending")
        for clause in clauses:
            stmt = stmt.where(clause)
        due = (await db.execute(stmt)).scalar_one()
        return due.isoformat() if due is not None else None

    # "today" is the operator's day, not UTC's — this is a household dashboard
    midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)

    last = (
        await db.execute(
            _named()
            .where(mine)
            .where(Jobs.kind == "hunt")
            .where(Jobs.status.in_(TERMINAL_STATUSES))
            .order_by(Jobs.finished_at.desc().nullslast(), Jobs.id.desc())
            .limit(1)
        )
    ).one_or_none()

    watched = (
        await db.execute(
            select(func.count())
            .select_from(Listings)
            .join(Watches, Watches.id == Listings.watch_id)
            .where(Watches.user_id == viewer.id)
            .where(Listings.active)
        )
    ).scalar_one()

    return JobsSummary(
        hunts_running=await count(Jobs.kind == "hunt", Jobs.status == "running"),
        checks_running=await count(Jobs.kind == "recheck", Jobs.status == "running"),
        checks_pending=await count(Jobs.kind == "recheck", Jobs.status == "pending"),
        next_check_at=await soonest(Jobs.kind == "recheck"),
        next_hunt_at=await soonest(Jobs.kind.in_(("hunt", "ground"))),
        hunts_today=await count(
            Jobs.kind == "hunt", Jobs.status.in_(TERMINAL_STATUSES), Jobs.finished_at >= midnight
        ),
        listings_watched=watched,
        last_hunt=build_job(*last) if last is not None else None,
        # sites are shared, so a pause is everyone's news
        paused_sites=await paused_sites(db),
    )


async def paused_sites(db: AsyncSession) -> list[PausedSite]:
    """Every site the breaker currently has stopped."""
    rows = (
        (
            await db.execute(
                select(Sites)
                .where(Sites.paused_until.is_not(None))
                .where(Sites.paused_until > datetime.now(UTC))
                .order_by(Sites.paused_until)
            )
        )
        .scalars()
        .all()
    )
    return [
        PausedSite(
            site_id=site.id,
            site_name=site.name,
            paused_until=site.paused_until.isoformat(),
            paused_reason=site.paused_reason or "",
        )
        for site in rows
    ]


# --- writes -------------------------------------------------------------------


async def enqueue(
    db: AsyncSession, viewer: User, kind: str | None, scope: str | None, scope_id: int | None
) -> list[Job]:
    """Turn "hunt this category" or "check this item's prices" into jobs.

    Never 409s: the open-job index means asking twice is asking once, so a
    pair that is already queued is simply brought forward and handed back. An
    empty list is a legitimate answer — a watch with every slot filled has
    nothing to hunt for (PR 2b turns that into a swap hunt).
    """
    _validate(kind, scope, scope_id)
    watches = await _scoped_watches(db, viewer, scope, scope_id)
    # an unknown target and one holding none of the caller's watches are the
    # same 404: neither is anything this caller can ask the hunter about
    if not watches:
        raise err(404, "not_found", f"Nothing to {kind} in that scope")

    queued = (
        await _hunts(db, watches, viewer.id, scope, scope_id)
        if kind == "hunt"
        else await _bump_scoped_rechecks(db, watches, scope, scope_id)
    )
    await db.commit()
    return await _build_rows(
        (await db.execute(_named().where(Jobs.id.in_([job.id for job in queued])))).all()
    )


def _validate(kind: str | None, scope: str | None, scope_id: int | None) -> None:
    fields: dict[str, str] = {}
    if kind not in REQUESTABLE_KINDS:
        fields["kind"] = "Ask for a hunt or a recheck"
    if scope not in SCOPES:
        fields["scope"] = "Unknown scope"
    elif scope != "global" and scope_id is None:
        fields["scope_id"] = "Required unless the scope is global"
    if fields:
        raise err(422, "validation_error", "Check the job request", fields=fields)


async def _scoped_watches(
    db: AsyncSession, viewer: User, scope: str | None, scope_id: int | None
) -> list[Watches]:
    """The caller's watches inside a scope. Empty means "nothing here for you",
    which covers both an unknown target and someone else's."""
    stmt = select(Watches).where(Watches.user_id == viewer.id)
    if scope == "category":
        stmt = stmt.join(Items, Items.id == Watches.item_id).where(Items.category_id == scope_id)
    elif scope == "item":
        stmt = stmt.where(Watches.item_id == scope_id)
    elif scope == "site":
        # a watch searches a site when it pinned that site, or pinned nothing
        # and its category is linked to it
        pinned_any = select(WatchSites.site_id).where(WatchSites.watch_id == Watches.id)
        pinned_this = pinned_any.where(WatchSites.site_id == scope_id)
        linked_this = (
            select(SiteCategories.site_id)
            .join(Items, Items.category_id == SiteCategories.category_id)
            .where(Items.id == Watches.item_id)
            .where(SiteCategories.site_id == scope_id)
        )
        stmt = stmt.where(
            or_(pinned_this.exists(), and_(~pinned_any.exists(), linked_this.exists()))
        )
    return list((await db.execute(stmt)).scalars().all())


async def watch_sites(db: AsyncSession, watch: Watches) -> list[int]:
    """Which sites a watch is searched on: its own subset (the API's
    site_ids), else every site its category is linked to."""
    pinned = list(
        (await db.execute(select(WatchSites.site_id).where(WatchSites.watch_id == watch.id)))
        .scalars()
        .all()
    )
    if pinned:
        return pinned
    return list(
        (
            await db.execute(
                select(SiteCategories.site_id)
                .join(Items, Items.category_id == SiteCategories.category_id)
                .where(Items.id == watch.item_id)
            )
        )
        .scalars()
        .all()
    )


async def open_slots(db: AsyncSession, watch: Watches) -> int:
    """How much room the watch has left. max_listings is one budget across
    every site, never per site (PR #31)."""
    tracked = (
        await db.execute(
            select(func.count())
            .select_from(Listings)
            .where(Listings.watch_id == watch.id)
            .where(Listings.active)
        )
    ).scalar_one()
    return max(0, watch.max_listings - tracked)


async def _hunts(
    db: AsyncSession, watches: list[Watches], user_id: int, scope: str | None, scope_id: int | None
) -> list[Jobs]:
    queued = []
    for watch in watches:
        if await open_slots(db, watch) <= 0:
            continue  # a full watch has nothing to hunt for (decision 9)
        for site_id in await watch_sites(db, watch):
            if scope == "site" and site_id != scope_id:
                continue
            job = await enqueue_hunt(db, watch, site_id, user_id=user_id, reason="user")
            if job is not None:
                queued.append(job)
    return queued


async def enqueue_hunt(
    db: AsyncSession,
    watch: Watches,
    site_id: int,
    *,
    user_id: int | None,
    reason: str,
    priority: int = USER_PRIORITY,
) -> Jobs | None:
    """Queue one (watch, site) hunt, in the caller's transaction.

    At most one open hunt per pair: the insert is ON CONFLICT DO NOTHING, and
    when it does nothing the open job is brought forward and handed back
    instead. A running one is left exactly as it is — it is already doing
    what was asked.
    """
    inserted = await db.scalar(
        insert(Jobs)
        .values(
            kind="hunt",
            user_id=user_id,
            watch_id=watch.id,
            item_id=watch.item_id,
            site_id=site_id,
            priority=priority,
            reason=reason,
        )
        .on_conflict_do_nothing()
        .returning(Jobs.id)
    )
    if inserted is not None:
        return await db.get(Jobs, inserted)

    open_job = await db.scalar(
        select(Jobs)
        .where(Jobs.kind == "hunt")
        .where(Jobs.watch_id == watch.id)
        .where(Jobs.site_id == site_id)
        .where(Jobs.status.in_(OPEN_STATUSES))
        .limit(1)
    )
    if open_job is not None and open_job.status == "pending":
        open_job.run_after = datetime.now(UTC)
        open_job.priority = priority
        open_job.reason = reason
        open_job.user_id = user_id
    return open_job


async def enqueue_hunts_for_watch(
    db: AsyncSession, watch: Watches, *, user_id: int | None, reason: str
) -> list[Jobs]:
    """Every site a new watch will be searched on, queued at once — what makes
    a just-added item start hunting in seconds rather than on some tick."""
    queued = []
    for site_id in await watch_sites(db, watch):
        job = await enqueue_hunt(db, watch, site_id, user_id=user_id, reason=reason)
        if job is not None:
            queued.append(job)
    return queued


async def enqueue_ground(db: AsyncSession, item_id: int, *, user_id: int | None) -> Jobs | None:
    """Queue a market-price refresh, in the caller's transaction. None when
    one is already open."""
    inserted = await db.scalar(
        insert(Jobs)
        .values(kind="ground", user_id=user_id, item_id=item_id, reason="created")
        .on_conflict_do_nothing()
        .returning(Jobs.id)
    )
    return await db.get(Jobs, inserted) if inserted is not None else None


async def _bump_scoped_rechecks(
    db: AsyncSession, watches: list[Watches], scope: str | None, scope_id: int | None
) -> list[Jobs]:
    """Bring forward every pending check of an active listing in scope.

    A running check is left alone and not returned: it is seconds from writing
    its own observation, so asking for it again would be asking for what is
    already happening.
    """
    listings = (
        select(Listings.id)
        .where(Listings.watch_id.in_([watch.id for watch in watches]))
        .where(Listings.active)
    )
    if scope == "site":
        listings = listings.where(Listings.site_id == scope_id)

    rows = (
        (
            await db.execute(
                update(Jobs)
                .where(Jobs.kind == "recheck")
                .where(Jobs.status == "pending")
                .where(Jobs.listing_id.in_(listings))
                .values(run_after=datetime.now(UTC), priority=USER_PRIORITY)
                .returning(Jobs)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def cancel_recheck(db: AsyncSession, listing_id: int) -> None:
    """Drop a listing's pending check, in the caller's transaction — what
    untracking it means to the queue. The agent does the same thing when the
    model retires a listing."""
    await db.execute(
        update(Jobs)
        .where(Jobs.kind == "recheck")
        .where(Jobs.listing_id == listing_id)
        .where(Jobs.status == "pending")
        .values(status="cancelled", finished_at=datetime.now(UTC))
    )


def effective_interval(watch: Watches) -> int:
    """Minutes between a watch's rechecks — the rule agent/jobs.py schedules
    successors by: the watch's own interval, else the instance default, never
    below the floor."""
    return max(
        watch.recheck_interval_minutes or settings.RECHECK_INTERVAL_MINUTES,
        settings.RECHECK_INTERVAL_FLOOR_MINUTES,
    )


async def pull_rechecks_forward(db: AsyncSession, watch: Watches) -> None:
    """Bring a watch's pending checks within its interval, in the caller's
    transaction — what shortening the interval means to the queue.

    Without it the new interval only applies from each listing's next
    successor, so a 6 h watch switched to 15 m would still wait out the 6 h.
    A longer interval moves nothing: the successors pick it up. Checks on a
    paused site stay where the breaker put them, and only tracked listings'
    checks move — untracking cancels a check, so one left pending on an
    untracked listing is a stray, not work.
    """
    now = datetime.now(UTC)
    due = now + timedelta(minutes=effective_interval(watch))
    tracked = select(Listings.id).where(Listings.watch_id == watch.id).where(Listings.active)
    await db.execute(
        update(Jobs)
        .where(Jobs.kind == "recheck")
        .where(Jobs.watch_id == watch.id)
        .where(Jobs.status == "pending")
        .where(Jobs.listing_id.in_(tracked))
        .where(Jobs.run_after > due)
        .where(Jobs.site_id.not_in(select(Sites.id).where(Sites.paused_until > now)))
        .values(run_after=due)
    )


async def enqueue_recheck(db: AsyncSession, listing: Listings) -> Jobs | None:
    """Put a listing back in the check rotation — what re-tracking it means.
    None when it already has one open."""
    inserted = await db.scalar(
        insert(Jobs)
        .values(
            kind="recheck",
            watch_id=listing.watch_id,
            item_id=listing.item_id,
            site_id=listing.site_id,
            listing_id=listing.id,
        )
        .on_conflict_do_nothing()
        .returning(Jobs.id)
    )
    return await db.get(Jobs, inserted) if inserted is not None else None


async def cancel_job(db: AsyncSession, job_id: int, viewer: User) -> Job:
    """Cancel a pending or running job.

    404 for unknown AND hidden jobs (never confirm another user's job
    exists), 403 for one the caller does not own, 422 for a check — they
    finish in seconds and there is nothing to stop — and 409 once it is
    terminal. Permission is checked before state: "you may never cancel this"
    holds regardless of status.

    A running hunt is stopped cooperatively: this only flips the row, and the
    worker notices between model steps. The final warn event is written here
    because this is the only place that knows a person did it.
    """
    if await db.scalar(select(Jobs.id).where(Jobs.id == job_id).where(visible(viewer))) is None:
        raise err(404, "not_found", f"Job {job_id} does not exist")
    # FOR UPDATE serialises against the worker finishing this job — otherwise
    # the seq bump below could collide with the agent's (uq_job_seq)
    job = await db.get(Jobs, job_id, with_for_update=True)

    owns = job.watch_id is not None and await db.scalar(
        select(Watches.id).where(Watches.id == job.watch_id).where(Watches.user_id == viewer.id)
    )
    if not owns and viewer.role != "admin":
        raise err(403, "forbidden", "Only an admin can cancel a system job")
    if job.kind == "recheck":
        raise err(422, "validation_error", "Checks finish in seconds and cannot be cancelled")
    if job.status not in OPEN_STATUSES:
        raise err(409, "job_finished", "This job has already finished")

    now = datetime.now(UTC)
    was_running = job.status == "running"
    job.status = "cancelled"
    job.finished_at = now
    if was_running:
        job.last_seq += 1
        db.add(
            JobEvents(
                job_id=job.id,
                seq=job.last_seq,
                ts=now,
                level="warn",
                event_type="job_finished",
                message="Cancelled by you",
                payload=None,
            )
        )
    await db.commit()
    return await _named_or_404(db, job_id, viewer)


# --- the item page's facts line -----------------------------------------------


async def hunt_facts(db: AsyncSession, watch: Watches) -> HuntFacts:
    """What the hunter will do next about finding listings for this watch."""
    running = await db.scalar(
        select(Jobs.id)
        .where(Jobs.kind == "hunt")
        .where(Jobs.watch_id == watch.id)
        .where(Jobs.status == "running")
        .limit(1)
    )
    next_at = await db.scalar(
        select(func.min(Jobs.run_after))
        .where(Jobs.kind == "hunt")
        .where(Jobs.watch_id == watch.id)
        .where(Jobs.status == "pending")
    )
    last = await db.scalar(
        select(Jobs)
        .where(Jobs.kind == "hunt")
        .where(Jobs.watch_id == watch.id)
        .where(Jobs.status.in_(TERMINAL_STATUSES))
        .order_by(Jobs.finished_at.desc().nullslast(), Jobs.id.desc())
        .limit(1)
    )
    return HuntFacts(
        running=running is not None,
        next_at=next_at.isoformat() if next_at is not None else None,
        last_at=last.finished_at.isoformat() if last is not None and last.finished_at else None,
        last_result=_last_result(last),
        slots_open=await open_slots(db, watch),
    )


def _last_result(job: Jobs | None) -> str | None:
    """What the last hunt came to, in the four words the item page says."""
    if job is None:
        return None
    if job.status in ("failed", "cancelled"):
        return job.status
    return "found" if (job.stats or {}).get("new_listings", 0) > 0 else "nothing"


async def recheck_facts(db: AsyncSession, watch: Watches) -> RecheckFacts:
    """What the hunter will do next about the prices it already tracks."""
    running = (
        await db.execute(
            select(func.count())
            .select_from(Jobs)
            .where(Jobs.kind == "recheck")
            .where(Jobs.watch_id == watch.id)
            .where(Jobs.status == "running")
        )
    ).scalar_one()
    next_at = await db.scalar(
        select(func.min(Jobs.run_after))
        .where(Jobs.kind == "recheck")
        .where(Jobs.watch_id == watch.id)
        .where(Jobs.status == "pending")
    )
    return RecheckFacts(
        running=running,
        next_at=next_at.isoformat() if next_at is not None else None,
        interval_minutes=effective_interval(watch),
    )
