"""Target-price notifications: the agent detects, the backend delivers.

The agent process is the only writer of price_checks, so it is the only place
that can see a watch's best price CROSS its target. What it writes is a
durable notification_outbox row — the backend's dispatcher fans it out to
whatever channels the owner configured (ntfy, Discord, signed webhook) and
owns delivery retries. The agent never talks to a push service, so there is
no server URL to configure here.

What lives in this file is the *decision* only, as one pure function: is this
reading a crossing, and if so what is the owner told. The SQL around it — the
row lock, the cooldown take, the outbox insert — belongs to
agent/observations.py, which does all of it inside the transaction that
records the price. Keeping the decision pure and non-raising is what
guarantees a notification bug can never cost an observation.
"""

from decimal import Decimal


def target_hit_payload(
    row,
    best_price_before: Decimal | None,
    price: Decimal,
    currency: str,
    listing_id: int,
    method: str,
) -> dict | None:
    """The notification for a price that just crossed its watch's target, or
    None when this reading is not a crossing.

    Edge-triggered: the watch's best price before this check must have been
    above target (or unknown), so a listing that simply stays cheap is
    announced once instead of on every sweep. The spam floor on top of that
    is NOTIFY_COOLDOWN_HOURS, which observations.py takes as it queues.

    Args:
      row: The watch/item/site/listing facts, already filtered to watches
        that notify and have a target price.
      best_price_before: The watch's best believed price across its active
        listings, excluding the check just written. None when it had none.
      price: The price observed, already validated and believed.
      currency: The currency it was quoted in.
      listing_id: The listing observed.
      method: How the price was read — carried so a consumer can tell a
        model's reading from a replayed locator.
    Returns:
      The payload to queue, or None to stay quiet.
    """
    target = row["target_price"]
    if price > target:
        return None
    if best_price_before is not None and best_price_before <= target:
        return None  # already at target before this check — not a crossing

    # Display facts frozen at enqueue: the dispatcher renders every channel
    # from these, and prices are decimal strings as they are everywhere else.
    return {
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
        "method": method,
        "confirmed": True,
    }
