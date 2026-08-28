"""Target-price push notifications via ntfy.

The agent is the only writer of price_checks, so "your target was hit" fires
here rather than in the API: save_price_check calls notify_target_met for
every real price it records. Off unless NTFY_SERVER_URL is set, exactly like
the vision sidecar — with it unset a run behaves as it always has."""

import logging
from datetime import UTC, datetime, timedelta

import httpx
from config import NTFY_COOLDOWN_HOURS, NTFY_SERVER_URL
from database import get_target_notification, mark_watch_notified

log = logging.getLogger(__name__)


async def notify_target_met(listing_id: int, check_id: int, price: float, currency: str) -> None:
    """
    Push a "target hit" notification for a listing that just checked in at or
    below its watch's target price.

    Edge-triggered: the watch's best price before this check must have been
    above target (or unknown), so a listing that simply stays cheap is
    announced once instead of on every nightly run. NTFY_COOLDOWN_HOURS is
    the spam floor on top of that, for a price that flaps across the target.

    Never raises. A push is a side effect of recording the observation, and
    losing the observation over a wedged ntfy server would be the worse
    outcome — every failure is logged and swallowed.

    Args:
      listing_id: The listing the price check belongs to.
      check_id: The price_checks id just written, excluded from the
        before-this-check comparison.
      price: The price observed, already known to be a real in-stock price.
      currency: The currency that price was quoted in.
    """
    if not NTFY_SERVER_URL:
        return

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
        hours=NTFY_COOLDOWN_HOURS
    ):
        log.info(f"Watch {row['watch_id']} hit its target but is still in cooldown")
        return

    message = f"{row['item_name']} — {price:.2f} {currency} on {row['site_name']} (target {target})"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(
                f"{NTFY_SERVER_URL.rstrip('/')}/{row['ntfy_topic']}",
                content=message,
                headers={
                    # Title stays ASCII: item names ride in the UTF-8 body
                    # because HTTP header values have no encoding to trust.
                    "Title": "Snagr target hit",
                    "Tags": "moneybag",
                    "Click": row["listing_url"],
                },
            )
            response.raise_for_status()
    except Exception as e:
        log.error(f"Could not push target-hit notification for listing {listing_id}: {e}")
        return

    log.info(f"Pushed target-hit notification for listing {listing_id} to {row['ntfy_topic']}")
    await mark_watch_notified(row["watch_id"])
