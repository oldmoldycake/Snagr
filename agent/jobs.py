"""The hunter's work queue.

One table, claimed one row at a time. A `hunt` searches a (watch, site) pair
with the model; a `recheck` re-reads one listing's price without one; a
`ground` refreshes an item's market stats. The backend inserts jobs when a
user asks for something; everything else the hunter queues for itself.

Two rules carry most of the design:

**One open job per target.** Migration 015's partial unique index enforces it,
so "check this listing now" is an UPDATE of the pending row, never a second
row, and a double-click cannot queue two hunts of the same pair. Every insert
here is `ON CONFLICT DO NOTHING` for the same reason: losing a duplicate is
always the right answer.

**A listing always has exactly one recheck ahead of it.** Completing a check
inserts the next one in the same transaction, and so does failing one — a
listing that dropped out of the queue would silently stop being watched, which
is the one failure nobody would notice. Untracking the listing is what ends
the chain.

Failures here PROPAGATE. Unlike the read helpers in database.py, which answer
with an empty default so a hiccup skips optional work, a swallowed failure in
this module strands a job in 'running' forever or loses a listing's next check.
The reaper is the backstop for a worker that dies, not for one that lies.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from config import (
    HUNT_RETENTION_DAYS,
    JOB_MAX_ATTEMPTS,
    JOB_RETENTION_DAYS,
    JOB_STALE_AFTER_SECONDS,
    RECHECK_INTERVAL_MINUTES,
)
from database import AsyncSessionLocal, JobEvents, Jobs, Listings, Sites
from sqlalchemy import bindparam, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert

log = logging.getLogger(__name__)

OPEN_STATUSES = ("pending", "running")
TERMINAL_STATUSES = ("done", "failed", "cancelled")

# Everything the worker needs to run a job without a second query for the
# basics; the pools load the unit's own context separately.
_CLAIMED = "id, kind, user_id, watch_id, site_id, listing_id, item_id, priority, attempts, reason"

# One statement, so the window between picking a row and owning it does not
# exist. SKIP LOCKED is what lets several workers claim concurrently; FOR
# UPDATE OF j is required because a paused site sits on the nullable side of
# the join and Postgres will not lock that.
_CLAIM = text(
    f"""
    UPDATE jobs SET
        status = 'running',
        locked_by = :worker,
        heartbeat_at = now(),
        started_at = now(),
        attempts = attempts + 1
     WHERE id = (
            SELECT j.id
              FROM jobs j
              LEFT JOIN sites s ON s.id = j.site_id
             WHERE j.status = 'pending'
               AND j.kind IN :kinds
               AND j.run_after <= now()
               AND (s.paused_until IS NULL OR s.paused_until <= now())
             ORDER BY j.priority DESC, j.run_after, j.id
             FOR UPDATE OF j SKIP LOCKED
             LIMIT 1
     )
    RETURNING {_CLAIMED}
    """
).bindparams(bindparam("kinds", expanding=True))


async def claim(worker: str, kinds: Sequence[str]) -> dict | None:
    """Take the most urgent due job of these kinds, or None when there is none.

    Highest priority first (a user's "hunt now" is 100), then oldest due, then
    oldest row. Jobs for a paused site are invisible here — that is the
    circuit breaker: while a site answers challenge pages, its work is not
    claimed at all, so no browser opens and no model is asked to look at it.

    Args:
      worker: An identifier for this worker, recorded on the row so an
        abandoned job can be traced back to the process that had it.
      kinds: Which kinds this pool works — ("recheck",) or ("hunt", "ground").
    Returns:
      The claimed row as a plain dict (captured before commit expires it), or
      None when nothing is due.
    """
    async with AsyncSessionLocal() as session:
        row = (
            (await session.execute(_CLAIM, {"worker": worker, "kinds": list(kinds)}))
            .mappings()
            .one_or_none()
        )
        await session.commit()
    if row is None:
        return None
    job = dict(row)
    log.info(f"Claimed {job['kind']} job {job['id']}")
    return job


async def heartbeat(job_id: int) -> bool:
    """Stamp a running job's heartbeat — what keeps the reaper off a job that
    is merely slow. Best-effort: one missed beat costs nothing until several
    are missed in a row, whereas failing the job over one would."""
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                update(Jobs)
                .where(Jobs.id == job_id, Jobs.status == "running")
                .values(heartbeat_at=datetime.now(UTC))
            )
            await session.commit()
            return True
        except Exception as e:
            log.error(f"Error stamping heartbeat for job {job_id}: {e}")
            return False


async def status(job_id: int) -> str | None:
    """A job's current status — the cooperative-cancellation poll a running
    hunt makes between units of model work. None means "keep going": a DB
    hiccup must not stop a job, only an explicit 'cancelled' does."""
    async with AsyncSessionLocal() as session:
        try:
            return await session.scalar(select(Jobs.status).where(Jobs.id == job_id))
        except Exception as e:
            log.error(f"Error reading status of job {job_id}: {e}")
            return None


async def complete(job_id: int, stats: dict | None = None) -> bool:
    """Mark a job done and, for a recheck, queue the listing's next one.

    A job the API cancelled while it was running keeps the cancelled state —
    the row lock makes that check atomic — but a cancelled recheck still gets
    its successor, because the chain is what keeps the listing watched.
    """
    return await _finish(job_id, "done", stats=stats)


async def fail_or_retry(job_id: int, error: str) -> str:
    """Put a failed job back in the queue, or give up on it.

    An attempt is spent on claim, so a job that has burned JOB_MAX_ATTEMPTS is
    failed for good; anything else goes back to pending, due immediately. A
    failed recheck still queues its successor: the page being unreadable today
    is not a reason to stop watching the listing.

    Returns:
      The status the job ended up in — 'pending' or 'failed'.
    """
    async with AsyncSessionLocal() as session:
        job = await session.get(Jobs, job_id, with_for_update=True)
        if job is None:
            log.error(f"Cannot fail unknown job {job_id}")
            return "failed"
        if job.status in TERMINAL_STATUSES:
            log.info(f"Job {job_id} is already {job.status}; leaving its terminal state")
            return job.status

        job.error = error[:1000]
        if job.attempts >= JOB_MAX_ATTEMPTS:
            job.status = "failed"
            job.finished_at = datetime.now(UTC)
            await _queue_successor(session, job)
            log.warning(f"Job {job_id} failed after {job.attempts} attempts: {error}")
        else:
            job.status = "pending"
            job.locked_by = None
            job.started_at = None
            job.run_after = datetime.now(UTC)
            log.warning(f"Job {job_id} attempt {job.attempts} failed, retrying: {error}")
        outcome = job.status
        await session.commit()
        return outcome


async def release(job_id: int) -> bool:
    """Hand a job back to the queue untouched — the shutdown path.

    A worker that is stopping has not failed: the job is due again at once,
    with no attempt held against it beyond the one it spent, so `docker compose
    stop` costs a restart rather than a retry budget.
    """
    async with AsyncSessionLocal() as session:
        job = await session.get(Jobs, job_id, with_for_update=True)
        if job is None or job.status != "running":
            return False
        job.status = "pending"
        job.locked_by = None
        job.started_at = None
        job.run_after = datetime.now(UTC)
        await session.commit()
        log.info(f"Returned job {job_id} to the queue")
        return True


async def release_all(workers: Sequence[str]) -> int:
    """Hand back everything these workers still hold — the shutdown sweep.

    One statement, run after the pools have stopped, because per-task cleanup
    during cancellation is exactly when awaiting is least reliable. Anything
    missed is the reaper's problem a few minutes later; this just makes
    `docker compose stop` cost seconds instead of minutes.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(Jobs)
            .where(Jobs.status == "running")
            .where(Jobs.locked_by.in_(workers))
            .values(status="pending", locked_by=None, started_at=None, run_after=datetime.now(UTC))
        )
        await session.commit()
        if result.rowcount:
            log.info(f"Returned {result.rowcount} in-flight jobs to the queue")
        return result.rowcount


async def _finish(job_id: int, outcome: str, stats: dict | None) -> bool:
    async with AsyncSessionLocal() as session:
        job = await session.get(Jobs, job_id, with_for_update=True)
        if job is None:
            log.error(f"Cannot finish unknown job {job_id}")
            return False
        cancelled = job.status == "cancelled"
        if not cancelled:
            job.status = outcome
            job.finished_at = datetime.now(UTC)
            job.stats = stats
        await _queue_successor(session, job)
        await session.commit()
        return not cancelled


async def _queue_successor(session, job: Jobs) -> None:
    """Queue the next recheck of this job's listing, in the caller's transaction.

    Only for rechecks, and only while the listing is still tracked: untracking
    is how the chain ends, and a successor for an inactive listing would
    resurrect it on the next tick.
    """
    if job.kind != "recheck" or job.listing_id is None:
        return
    active = await session.scalar(select(Listings.active).where(Listings.id == job.listing_id))
    if not active:
        return
    due = datetime.now(UTC) + timedelta(minutes=RECHECK_INTERVAL_MINUTES)
    # A paused site is not read whatever the queue says, so a due time inside
    # the pause would be a time this check cannot be run at — and the page
    # would count it down as if it could.
    paused_until = await session.scalar(select(Sites.paused_until).where(Sites.id == job.site_id))
    await _insert(
        session,
        kind="recheck",
        watch_id=job.watch_id,
        item_id=job.item_id,
        site_id=job.site_id,
        listing_id=job.listing_id,
        run_after=max(due, paused_until) if paused_until is not None else due,
        reason="paused" if paused_until is not None and paused_until > due else None,
    )


async def _insert(session, **values) -> None:
    """Insert one job, or nothing when the target already has an open one.

    The bare ON CONFLICT DO NOTHING is deliberate: the open-job index is
    partial and built on coalesce() expressions, so naming it as a conflict
    target would couple this statement to the exact expression list in
    migration 015 — and "any unique violation means the work is already
    queued" is true of every unique constraint this table has.
    """
    await session.execute(insert(Jobs).values(**values).on_conflict_do_nothing())


async def enqueue_recheck(
    session,
    *,
    listing_id: int,
    watch_id: int,
    item_id: int,
    site_id: int,
    delay_minutes: int = 0,
) -> None:
    """Queue a listing's first check, in the caller's transaction.

    save_listing calls this the moment it saves a listing, so a discovery is
    being watched before the hunt that found it has even finished.
    """
    await _insert(
        session,
        kind="recheck",
        watch_id=watch_id,
        item_id=item_id,
        site_id=site_id,
        listing_id=listing_id,
        run_after=datetime.now(UTC) + timedelta(minutes=delay_minutes),
    )


async def bump_rechecks(session, listing_id: int, *, delay_minutes: int, priority: int) -> None:
    """Bring a listing's pending check forward, in the caller's transaction.

    A running check is left alone — it is seconds from writing its own
    observation, and its successor will honour the new time anyway.
    """
    await session.execute(
        update(Jobs)
        .where(Jobs.kind == "recheck")
        .where(Jobs.listing_id == listing_id)
        .where(Jobs.status == "pending")
        .values(run_after=datetime.now(UTC) + timedelta(minutes=delay_minutes), priority=priority)
    )


async def cancel_recheck(session, listing_id: int) -> None:
    """Drop a listing's pending check, in the caller's transaction — what
    untracking a listing means to the queue."""
    await session.execute(
        update(Jobs)
        .where(Jobs.kind == "recheck")
        .where(Jobs.listing_id == listing_id)
        .where(Jobs.status == "pending")
        .values(status="cancelled", finished_at=datetime.now(UTC))
    )


async def enqueue_ground(item_id: int) -> bool:
    """Queue a market-price refresh for one item. False when one is already
    open, which is the usual answer on a busy scheduler tick."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            insert(Jobs).values(kind="ground", item_id=item_id).on_conflict_do_nothing()
        )
        await session.commit()
        return result.rowcount == 1


async def reap() -> list[int]:
    """Take back every job whose worker went silent.

    A live worker beats every JOB_HEARTBEAT_INTERVAL_SECONDS, so a merely slow
    job is never mistaken for a dead one. Left alone, a row abandoned by a
    SIGKILL would hold its target's open-job slot forever — nothing else would
    ever notice, because the unique index would refuse every replacement.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=JOB_STALE_AFTER_SECONDS)
    async with AsyncSessionLocal() as session:
        stale = list(
            (
                await session.execute(
                    select(Jobs.id)
                    .where(Jobs.status == "running")
                    .where(func.coalesce(Jobs.heartbeat_at, Jobs.started_at) < cutoff)
                    .order_by(Jobs.id)
                )
            )
            .scalars()
            .all()
        )

    minutes = JOB_STALE_AFTER_SECONDS // 60
    error = f"The worker stopped responding (no heartbeat for over {minutes} min)"
    for job_id in stale:
        log.warning(f"Job {job_id} has had no heartbeat for over {minutes} min; taking it back")
        await fail_or_retry(job_id, error)
    return stale


async def prune() -> int:
    """Delete terminal jobs past their retention, cascading their events.

    Fifty listings on a half-hour cadence write ~2,400 recheck rows a day; the
    price history they produced lives in price_checks, so keeping the jobs
    themselves beyond a week buys nothing. A hunt is a story — what the model
    looked at and why it saved or skipped it — and is kept far longer.
    """
    now = datetime.now(UTC)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(Jobs)
            .where(Jobs.status.in_(TERMINAL_STATUSES))
            .where(
                (
                    Jobs.kind.in_(("recheck", "ground"))
                    & (Jobs.finished_at < now - timedelta(days=JOB_RETENTION_DAYS))
                )
                | (
                    (Jobs.kind == "hunt")
                    & (Jobs.finished_at < now - timedelta(days=HUNT_RETENTION_DAYS))
                )
            )
        )
        await session.commit()
        if result.rowcount:
            log.info(f"Pruned {result.rowcount} finished jobs past retention")
        return result.rowcount


async def add_event(
    session,
    job_id: int,
    level: str,
    event_type: str,
    message: str,
    payload: dict | None = None,
) -> int | None:
    """Append one line to a job's log, in the caller's transaction.

    seq comes from bumping jobs.last_seq under SELECT ... FOR UPDATE, so
    concurrent writers never collide on uq_job_seq; deriving it from MAX(seq)+1
    unlocked would. Callers that already hold a lock on a watch take this one
    after it — watch, then site, then job, everywhere.
    """
    job = await session.get(Jobs, job_id, with_for_update=True)
    if job is None:
        log.error(f"Cannot append an event to unknown job {job_id}")
        return None

    job.last_seq += 1
    session.add(
        JobEvents(
            job_id=job_id,
            seq=job.last_seq,
            ts=datetime.now(UTC),
            level=level,
            event_type=event_type,
            message=message,
            payload=payload,
        )
    )
    return job.last_seq


async def append_event(
    job_id: int, level: str, event_type: str, message: str, payload: dict | None = None
) -> int | None:
    """Append one line to a job's log on its own, and return its seq.

    Returns None if the job is missing or the write fails: progress events are
    best-effort and must never take a job down. Writers who are already in a
    transaction call add_event instead, so the line lands with what it
    describes or not at all.
    """
    async with AsyncSessionLocal() as session:
        try:
            seq = await add_event(session, job_id, level, event_type, message, payload)
            await session.commit()
            return seq
        except Exception as e:
            log.error(f"Error appending an event to job {job_id}: {e}")
            return None
