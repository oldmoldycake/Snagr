"""The per-site circuit breaker.

A marketplace does not fail one listing at a time. When it decides the hunter
is a bot, every page becomes a challenge page — and under a daemon that is
every listing, every interval, forever, each failure ending in an LLM fallback
that fails too. The breaker turns that into five reads and silence.

Counting is per site and consecutive: any successful read resets it, so a
flaky page here and there never trips anything. At SITE_BREAKER_ERRORS the
site is paused — and paused means invisible, not deferred: agent/jobs.py's
claim query skips a paused site's work entirely, so no browser opens, no model
is asked to look, and the site's pending jobs are pushed out to the moment the
pause lifts so they do not all land at once when it does.

A wall that is still there after the pause trips again, and the wait doubles
each time up to SITE_BREAKER_CAP_MINUTES. The trip count is read off the error
counter rather than stored: a success is what resets it, so
`consecutive_errors // SITE_BREAKER_ERRORS` is exactly how many times this
site has tripped without ever answering in between.

Lifting a pause by hand is a backend concern (PATCH /api/sites/{id} with
paused_until: null), which is why nothing here ever shortens one.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from config import SITE_BREAKER_CAP_MINUTES, SITE_BREAKER_ERRORS, SITE_BREAKER_MINUTES
from database import AsyncSessionLocal, Jobs, Sites
from jobs import append_event
from sqlalchemy import case, select, update

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Pause:
    """A site the breaker has just stopped reading."""

    site_id: int
    site_name: str
    until: datetime
    reason: str


async def record_outcome(
    site_id: int, ok: bool, *, job_id: int | None = None, detail: str | None = None
) -> Pause | None:
    """Count one read of a site, and pause it when it has failed enough.

    Args:
      site_id: The site that was read. None-safe callers should not call at
        all — a job with no site (grounding) reads no marketplace.
      ok: Whether the page was readable. A price that was read and then
        disbelieved is still a successful read: the site answered.
      job_id: The job that made this read, so a trip can be announced on the
        job that caused it.
      detail: What the failure looked like ("challenge page"), quoted in the
        pause reason the UI shows.
    Returns:
      The Pause when this read tripped the breaker, else None.
    """
    async with AsyncSessionLocal() as session:
        site = await session.get(Sites, site_id, with_for_update=True)
        if site is None:
            log.warning(f"Outcome recorded for unknown site {site_id}")
            return None

        if ok:
            if site.consecutive_errors:
                log.info(f"{site.name} answered again; clearing {site.consecutive_errors} errors")
            site.consecutive_errors = 0
            await session.commit()
            return None

        site.consecutive_errors += 1
        errors = site.consecutive_errors
        if errors % SITE_BREAKER_ERRORS:
            await session.commit()
            return None

        trips = errors // SITE_BREAKER_ERRORS
        minutes = min(SITE_BREAKER_MINUTES * 2 ** (trips - 1), SITE_BREAKER_CAP_MINUTES)
        until = datetime.now(UTC) + timedelta(minutes=minutes)
        reason = f"{errors} consecutive read errors" + (f": {detail}" if detail else "")
        site.paused_until = until
        site.paused_reason = reason
        # nothing for this site runs before the pause lifts, and spreading the
        # backlog is the resume's problem, not this transaction's. A person's
        # own request keeps saying so: switching a watch's hunting off keeps
        # exactly the hunts whose reason is 'user'.
        await session.execute(
            update(Jobs)
            .where(Jobs.site_id == site_id)
            .where(Jobs.status == "pending")
            .where(Jobs.run_after < until)
            .values(
                run_after=until,
                reason=case((Jobs.reason == "user", Jobs.reason), else_="paused"),
            )
        )
        pause = Pause(site_id=site_id, site_name=site.name, until=until, reason=reason)
        await session.commit()

    log.warning(f"{pause.site_name} paused for {minutes} min — {reason}")
    if job_id is not None:
        await append_event(
            job_id,
            "warn",
            "site_paused",
            f"{pause.site_name} paused until {until:%H:%M} — {reason}",
            {
                "site_id": site_id,
                "paused_until": until.isoformat(),
                "paused_reason": reason,
            },
        )
    return pause


async def is_paused(site_id: int | None) -> datetime | None:
    """When this site's pause lifts, or None when it is not paused.

    The claim query already hides a paused site's jobs; this is for the reads
    that do not come from the queue — above all the LLM fallback, which must
    not be spent on a site that is answering challenge pages.
    """
    if site_id is None:
        return None
    async with AsyncSessionLocal() as session:
        until = await session.scalar(select(Sites.paused_until).where(Sites.id == site_id))
    return until if until is not None and until > datetime.now(UTC) else None
