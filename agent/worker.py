"""The hunter: a daemon that claims jobs and works them.

Two pools, because the two kinds of work cost different things. The check pool
re-reads listings — cheap, usually browserless, several at once, so one wedged
page never holds up the listing behind it. The hunt pool carries the model, so
it is narrow by default; grounding runs there too, being model work with no
browser.

Wake-ups come from Postgres. Migration 015's trigger announces every job
insert and status change on 'snagr_jobs'; the listener nudges every worker,
and each drains its own kind until the queue is empty. A 30-second tick does
exactly the same thing, so nothing depends on a NOTIFY arriving — a missed
one costs seconds, a dropped LISTEN connection costs one reconnect.

Every job opens and closes its own MCP session (its own isolated browser
context), which is what lets "check prices now" overtake a hunt instead of
queueing behind it.

Shutdown is a single statement, not per-task cleanup: the pools are cancelled,
then everything this process still holds goes back to pending in one UPDATE.
Cancellation is exactly when awaiting is least reliable, and the reaper is
the backstop for whatever a hard kill loses anyway.
"""

import asyncio
import json
import logging
import os
import socket
from datetime import UTC, datetime

import asyncpg
import breaker
import jobs as job_queue
from config import (
    CHEAP_RECHECK,
    HUNT_CONCURRENCY,
    JOB_HEARTBEAT_INTERVAL_SECONDS,
    RECHECK_CONCURRENCY,
)
from database import (
    DATABASE_URL,
    get_ground_unit,
    get_grounding_candidates,
    get_hunt_unit,
    get_recheck_unit,
)
from llm import build_llm
from pricing import ground_item, select_grounding_work
from recheck import recheck_deterministic
from sqlalchemy.exc import SQLAlchemyError

from agent import Cancelled as JobCancelled
from agent import (
    bounded,
    build_hunt_agent,
    build_recheck_agent,
    flush_traces,
    open_browser_session,
    recheck_listing,
    run_hunt_job,
)

log = logging.getLogger(__name__)

CHANNEL = "snagr_jobs"
# The safety net under LISTEN, and the clock that starts work whose run_after
# passed while nothing was being inserted.
TICK_SECONDS = 30
# Housekeeping: the reaper has to run faster than a stale job matters, the
# retention sweep does not.
SCHEDULER_INTERVAL_SECONDS = 60
PRUNE_EVERY_TICKS = 60

CHECK_KINDS = ("recheck",)
HUNT_KINDS = ("hunt", "ground")


def worker_ids() -> list[str]:
    """One stable name per pool member: host, pid and slot.

    Recorded on every claimed row, so an abandoned job names the process that
    had it — and so shutdown can hand back exactly this process's work
    without touching another instance's.
    """
    origin = f"{socket.gethostname()}:{os.getpid()}"
    return [f"{origin}#check-{i}" for i in range(RECHECK_CONCURRENCY)] + [
        f"{origin}#hunt-{i}" for i in range(HUNT_CONCURRENCY)
    ]


# --- running one job -------------------------------------------------------


async def _with_heartbeat(job_id: int, work):
    """Run one job with its heartbeat beating beside it.

    The claim stamped the first beat, hence sleep-then-beat. The heartbeat is
    the only thing standing between a slow job and the reaper.
    """

    async def beat() -> None:
        while True:
            await asyncio.sleep(JOB_HEARTBEAT_INTERVAL_SECONDS)
            await job_queue.heartbeat(job_id)

    heart = asyncio.create_task(beat())
    try:
        return await work
    finally:
        heart.cancel()


async def run_job(job: dict) -> dict | None:
    """Do one job and return its stats, or None when there was nothing to do.

    Raises when the job failed — the caller decides whether that is a retry
    or the end of it.
    """
    started = datetime.now(UTC)
    if job["kind"] == "recheck":
        stats = await _run_recheck(job)
    elif job["kind"] == "hunt":
        stats = await _run_hunt(job)
    else:
        stats = await _run_ground(job)
    if stats is None:
        return None
    return {**stats, "duration_ms": int((datetime.now(UTC) - started).total_seconds() * 1000)}


def answered(stats: dict) -> bool:
    """Whether the site answered this unit at all.

    A price that was read and then disbelieved still counts: the site served
    a page. What does not count is a unit that read nothing and recorded an
    error — a challenge page, a dead host, a layout the model could not make
    sense of. Mixed results count as an answer, so one unreadable listing
    among five does not put a working marketplace on the breaker's clock.
    """
    return stats.get("errors", 0) == 0 or stats.get("prices_found", 0) > 0


def _empty(**extra) -> dict:
    return {
        "listings_checked": 0,
        "prices_found": 0,
        "new_listings": 0,
        "errors": 0,
        "tokens_in": 0,
        "tokens_out": 0,
        **extra,
    }


async def _run_recheck(job: dict) -> dict | None:
    """Re-read one listing's price — the cheap path first, the model last.

    The deterministic ladder gets first refusal: when it reads the page, no
    model ran at all. Only when it cannot — the locator is gone, the page is
    blocked, the reading is implausible — is a model built and asked, and that
    read is what relearns the locator for next time. CHEAP_RECHECK=false skips
    the ladder entirely, which is how the agent behaved before locators
    existed.
    """
    row = await get_recheck_unit(job["listing_id"])
    if row is None:
        log.info(f"Listing {job['listing_id']} is no longer tracked; nothing to re-read")
        return _empty()

    async with open_browser_session() as (browser_tools, browser):
        if CHEAP_RECHECK:
            outcome = await bounded(recheck_deterministic(browser, row))
            if outcome.handled:
                log.info(
                    f"Listing {row['listing_id']} read by {outcome.method} over "
                    f"{outcome.transport}" + (f" ({outcome.note})" if outcome.note else "")
                )
                await breaker.record_outcome(row["site_id"], True)
                return _empty(
                    listings_checked=1,
                    prices_found=1 if outcome.method else 0,
                    method=outcome.method,
                    transport=outcome.transport,
                )
            log.info(f"Listing {row['listing_id']} needs the model")

        agent = build_recheck_agent(build_llm(), browser_tools)
        stats = await bounded(
            recheck_listing(agent, f"job-{job['id']}", row, browser, job_id=job["id"])
        )
    # a model that could not read the page says so by recording an error, not
    # by raising — which is the usual shape of "this site has stopped talking"
    await breaker.record_outcome(
        row["site_id"], answered(stats), job_id=job["id"], detail="unreadable page"
    )
    return _empty(**stats, method="llm", transport="browser")


async def _run_hunt(job: dict) -> dict | None:
    """Search one (watch, site) pair for listings that fit the watch."""
    row = await get_hunt_unit(job["watch_id"], job["site_id"])
    if row is None:
        log.info(f"Watch {job['watch_id']} no longer searches site {job['site_id']}")
        return _empty()

    async with open_browser_session() as (browser_tools, browser):
        agent = build_hunt_agent(build_llm(), browser_tools)
        stats = await bounded(run_hunt_job(agent, job["id"], row, browser))
    await breaker.record_outcome(
        row["site_id"], answered(stats), job_id=job["id"], detail="unreadable page"
    )
    return _empty(**stats)


async def _run_ground(job: dict) -> dict | None:
    """Refresh one item's market-price stats. No browser: grounding reads
    search results and guide pages over plain HTTP."""
    row = await get_ground_unit(job["item_id"])
    if row is None:
        log.info(f"Item {job['item_id']} is gone; nothing to ground")
        return _empty()

    payload = await ground_item(row["item_id"], row["item_name"], row["category_id"])
    observations = payload.get("observations") or []
    await job_queue.append_event(
        job["id"],
        "success" if payload["status"] == "ok" else "warn",
        "job_finished",
        f"Market price for {row['item_name']}: {payload['status']} "
        f"({len(observations)} observations, {payload['confidence']} confidence)",
        {"item_id": row["item_id"]},
    )
    return _empty(listings_checked=len(observations), prices_found=len(observations))


# --- the pools -------------------------------------------------------------


async def _work_one(worker: str, job: dict) -> None:
    """Run one claimed job and write its terminal state, whatever happens."""
    job_id = job["id"]
    try:
        stats = await _with_heartbeat(job_id, run_job(job))
    except JobCancelled:
        # the API already wrote 'cancelled'; say so in the log the page shows
        log.info(f"Job {job_id} was cancelled mid-flight")
        await job_queue.append_event(job_id, "warn", "job_finished", "Cancelled by you")
        await job_queue.complete(job_id, None)
    except Exception as e:
        log.error(f"{job['kind'].title()} job {job_id} failed: {e}")
        await breaker.record_outcome(job["site_id"], False, job_id=job_id, detail=str(e)[:120])
        await job_queue.append_event(job_id, "error", "error", str(e)[:500])
        await job_queue.fail_or_retry(job_id, str(e))
    else:
        if job["kind"] == "hunt":
            await job_queue.append_event(
                job_id,
                "success",
                "job_finished",
                f"Hunt complete — {stats['new_listings']} new · {stats['listings_checked']} seen",
            )
        await job_queue.complete(job_id, stats)
    finally:
        flush_traces()


async def _pool(worker: str, kinds: tuple[str, ...], wake: asyncio.Event) -> None:
    """One worker: drain every job of these kinds, then wait to be nudged.

    Clearing the flag before claiming is what makes a missed wake impossible
    to sleep through for long: a NOTIFY that lands between the clear and the
    last empty claim is lost, and the 30-second tick picks it up.
    """
    while True:
        wake.clear()
        while (job := await job_queue.claim(worker, kinds)) is not None:
            await _work_one(worker, job)
        await wake.wait()


async def _listen(wakes: list[asyncio.Event]) -> None:
    """Hold one LISTEN connection and nudge every worker on any job news.

    Reconnects forever on DB loss (the LAN database rides a flaky VPN); each
    (re)connect nudges the pools, so anything inserted during an outage is
    picked up as soon as the connection is back.
    """
    dsn = DATABASE_URL.replace("+asyncpg", "")
    pending: asyncio.Queue[str] = asyncio.Queue()

    def _on_notify(_conn, _pid, _channel, payload: str) -> None:
        pending.put_nowait(payload)

    while True:
        try:
            conn = await asyncpg.connect(dsn)
            try:
                await conn.add_listener(CHANNEL, _on_notify)
                log.info("Listening for jobs")
                _nudge(wakes)
                while True:
                    try:
                        payload = await asyncio.wait_for(pending.get(), timeout=TICK_SECONDS)
                        while not pending.empty():  # coalesce a burst into one nudge
                            pending.get_nowait()
                        log.debug(f"Job news: {json.loads(payload)}")
                    except TimeoutError:
                        # idle: surface a silently-dead TCP link, and start
                        # whatever came due while nothing was being inserted
                        await conn.execute("SELECT 1")
                    _nudge(wakes)
            finally:
                await conn.close()
        except (OSError, asyncpg.PostgresError) as e:
            log.error(f"Lost Postgres ({e}); retrying in 5s")
            await asyncio.sleep(5)


def _nudge(wakes: list[asyncio.Event]) -> None:
    for wake in wakes:
        wake.set()


# --- housekeeping ----------------------------------------------------------


async def queue_grounding() -> int:
    """Queue a `ground` job for every item whose market stats are due.

    The selection rule is unchanged (never-grounded items first and exempt
    from the per-pass cap, stale ones oldest-first under it); what changed is
    that the work goes through the queue like everything else, so it is
    visible, cancellable and bounded by the same concurrency.
    """
    candidates = await get_grounding_candidates()
    queued = 0
    for row in select_grounding_work(list(candidates), datetime.now(UTC)):
        if await job_queue.enqueue_ground(row["item_id"]):
            queued += 1
    if queued:
        log.info(f"Queued grounding for {queued} item(s)")
    return queued


async def housekeeping(ticks: int = 0) -> None:
    """One scheduler pass: take back abandoned jobs, queue due grounding, and
    now and then sweep terminal rows past their retention."""
    await job_queue.reap()
    await queue_grounding()
    if ticks % PRUNE_EVERY_TICKS == 0:
        await job_queue.prune()


async def _scheduler() -> None:
    """The housekeeping loop. Errors here log and continue: a scheduler that
    dies takes the reaper with it, and a wedged job would then never be
    noticed by anything."""
    ticks = 0
    while True:
        try:
            await housekeeping(ticks)
        except (SQLAlchemyError, OSError) as e:
            log.error(f"Housekeeping pass failed: {e}")
        ticks += 1
        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)


# --- entry points ----------------------------------------------------------


async def serve() -> None:
    """Run until stopped: the pools, the listener and the scheduler."""
    workers = worker_ids()
    wakes = [asyncio.Event() for _ in workers]
    pools = [
        asyncio.create_task(_pool(worker, CHECK_KINDS if "#check-" in worker else HUNT_KINDS, wake))
        for worker, wake in zip(workers, wakes, strict=True)
    ]
    tasks = [*pools, asyncio.create_task(_listen(wakes)), asyncio.create_task(_scheduler())]
    log.info(
        f"Hunter serving — {RECHECK_CONCURRENCY} check worker(s), {HUNT_CONCURRENCY} hunt worker(s)"
    )
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await job_queue.release_all(workers)


async def once() -> None:
    """Queue what is due, drain the queue until it is empty, and stop.

    The cron mode. It does the same work `serve` does and in the same order —
    housekeeping first, so a job a dead process abandoned is taken back before
    anything else is claimed — but it never waits: when nothing is due, it is
    finished.
    """
    workers = worker_ids()
    await housekeeping()
    try:
        for worker in workers:
            kinds = CHECK_KINDS if "#check-" in worker else HUNT_KINDS
            while (job := await job_queue.claim(worker, kinds)) is not None:
                await _work_one(worker, job)
    finally:
        await job_queue.release_all(workers)
