"""Daily garbage collection (D-V12: nothing grows unbounded).

Row side: unreviewed listing images past the retention window are pruned,
then scans left with no images. Byte side: the bucket is reconciled against
every object_key a live row still references — this sweep, not the request
path, is what reclaims bytes after discards, cascades, and prunes (a hash
can back several rows, so delete-time refcounting would be fragile; a
periodic set difference is boring and correct)."""

import logging
import threading
import time
from datetime import UTC, datetime, timedelta

from config import VISION_RETENTION_DAYS
from db import SessionLocal, VisionListingImages, VisionReferences, VisionScans
from sqlalchemy import delete, select

log = logging.getLogger(__name__)

GC_INTERVAL_SECONDS = 24 * 60 * 60


def prune_stale_captures(session, now: datetime | None = None) -> int:
    """Delete unreviewed listing images older than the retention window,
    then scans that lost their last image; the pruned-image count.
    Confirmed images stay (their reference matters), discarded rows were
    already deleted at discard time."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=VISION_RETENTION_DAYS)
    pruned = session.execute(
        delete(VisionListingImages)
        .where(VisionListingImages.review_state.in_(("none", "suggested")))
        .where(VisionListingImages.created_at < cutoff)
    ).rowcount
    session.execute(
        delete(VisionScans).where(
            ~select(VisionListingImages.id)
            .where(VisionListingImages.scan_id == VisionScans.id)
            .exists()
        )
    )
    session.commit()
    return pruned


def reconcile_bucket(session, store) -> int:
    """Delete every object no live row references; the deleted count."""
    live_keys = set(session.scalars(select(VisionReferences.object_key)).all()) | set(
        session.scalars(select(VisionListingImages.object_key)).all()
    )
    deleted = 0
    for key in store.list_keys():
        if key not in live_keys:
            store.delete(key)
            deleted += 1
    return deleted


def _sweep(store) -> None:
    with SessionLocal() as session:
        pruned = prune_stale_captures(session)
        deleted = reconcile_bucket(session, store)
    log.info(f"GC: pruned {pruned} stale captures, reclaimed {deleted} objects")


def start_daily(store) -> None:
    """Run the sweep once a day on a daemon thread (sleep-first, so tests
    that build an app never race a sweep). A failed sweep logs and waits for
    the next day — GC must never take the service down, the same isolation
    contract as the grounding pre-pass."""

    def _loop() -> None:
        while True:
            time.sleep(GC_INTERVAL_SECONDS)
            try:
                _sweep(store)
            except Exception as exc:
                log.error(f"GC sweep failed (will retry tomorrow): {exc}")

    threading.Thread(target=_loop, name="vision-gc", daemon=True).start()
