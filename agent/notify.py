"""Target-price notifications: the agent detects, the backend delivers.

The agent is the only writer of price_checks, so it is the only place that
can see a watch's best price CROSS its target: save_price_check calls
notify_target_met for every real price it records. What used to be a direct
ntfy POST is now a durable notification_outbox row — the backend's
dispatcher fans it out to whatever channels the owner configured (ntfy,
Discord, signed webhook) and owns delivery retries. The agent never talks
to a push service, so there is no server URL to configure here."""

import logging
from datetime import UTC, datetime, timedelta

from config import NOTIFY_COOLDOWN_HOURS
from database import enqueue_notification, get_target_notification, mark_watch_notified

log = logging.getLogger(__name__)


async def notify_target_met(listing_id: int, check_id: int, price: float, currency: str) -> None:
    """
    Queue a "target hit" notification for a listing that just checked in at or
    below its watch's target price.

    Edge-triggered: the watch's best price before this check must have been
    above target (or unknown), so a listing that simply stays cheap is
    announced once instead of on every nightly run. NOTIFY_COOLDOWN_HOURS is
    the spam floor on top of that, for a price that flaps across the target.
    The cooldown stamp is written at enqueue, not delivery — the outbox owns
    retries, so "queued" is the moment the owner counts as told.

    Never raises. A notification is a side effect of recording the
    observation, and losing the observation to a failed enqueue would be the
    worse outcome — the DB helpers log and swallow their own failures.

    Args:
      listing_id: The listing the price check belongs to.
      check_id: The price_checks id just written, excluded from the
        before-this-check comparison.
      price: The price observed, already known to be a real in-stock price.
      currency: The currency that price was quoted in.
    """
    row = await get_target_notification(listing_id, check_id)
    if row is None:
        return

    target = row["target_price"]
    if price > target:
        return

    best_before = row["best_price_before"]
    if best_before is not None and best_before <= target:
        return  # already at target before this check — not a crossing

    last_notified_at = row["last_notified_at"]
    if last_notified_at is not None and datetime.now(UTC) - last_notified_at < timedelta(
        hours=NOTIFY_COOLDOWN_HOURS
    ):
        log.info(f"Watch {row['watch_id']} hit its target but is still in cooldown")
        return

    payload = {
        "watch_id": row["watch_id"],
        "item_id": row["item_id"],
        "listing_id": listing_id,
        "site_id": row["site_id"],
        "item_name": row["item_name"],
        "site_name": row["site_name"],
        "listing_url": row["listing_url"],
        "price": f"{price:.2f}",
        "currency": currency,
        "target_price": str(target),
    }
    if await enqueue_notification(row["user_id"], "target.hit", payload):
        log.info(f"Queued target-hit notification for listing {listing_id}")
        await mark_watch_notified(row["watch_id"])
