"""Price aggregation math — every computed number the contract asks for.

Consumed by routers/charts.py, routers/items.py, routers/categories.py, routers/sites.py.

Responsibilities:
  - price_history(item, range, points): per-listing series of PricePoints.
  - price_summary(item, range, points): bucketed avg/best over time.
  - item_rollups(item): best_price, best_listing_id, best_site_name, avg_price,
    active_listing_count, target_met, pct_change_range, spark[] (<=30 buckets).
  - dashboard_stats(user, range): the four StatTiles (value, delta vs prev
    equal-length period, spark[]).
  - price_drops(user, range, limit): biggest recent drops.
  - category_price_change(category, range) and site/category counts.

Bucketing: split [now-range, now] into N buckets; each point is the best/avg
price whose latest check falls in that bucket; null when the bucket is empty.
Prices in and out are decimal STRINGS.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from math import floor
from sqlalchemy import func, select
from app.schemas.charts import ListingSeries, StatTile, SummaryPoint, PricePoint, DashboardStats, CategoryItemChange, PriceDrop
from app.models import Items, Listings, PriceChecks, Watches, Sites


_RANGE_DELTAS: dict[str, timedelta | None] = {
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "1y": timedelta(days=365),
    "all": None,
}

async def _range_start(range: str) -> datetime | None:
    """Lower bound for a TimeRange, or None for "all" — which means no bound.

    What None *implies* is the caller's call, and they disagree on purpose:
    price_drops treats it as "don't filter", dashboard_stats substitutes a year
    because a growth tile needs some window to measure against.
    """
    delta = _RANGE_DELTAS[range]
    return None if delta is None else datetime.now(timezone.utc) - delta


async def _create_price_points(checks, step: float = 1) -> list[PricePoint]:
    """Serialize checks into contract PricePoints, taking every `step`-th one.

    step=1 keeps everything. A fractional step walks the list at even intervals
    and floors to an index, thinning a long series while preserving the shape of
    the curve. The caller computes the step; this just walks it.
    """
    steps = 0
    price_point_list = []

    while steps < len(checks):
        current_check = checks[floor(steps)]

        price_point_list.append(PricePoint(
            ts=current_check.checked_at.isoformat(),
            price=str(current_check.price),
            in_stock=current_check.in_stock
        ))
        steps += step

    return price_point_list


async def _create_summary_points(checks, start, points) -> list[SummaryPoint]:
    """Bucket pooled checks into `points` equal time slices.

    One SummaryPoint per slice, stamped at the slice midpoint, carrying the
    average and cheapest price seen inside it. An empty slice reports None/None,
    never 0 — the contract distinguishes "unknown" from "free".

    With start=None ("all"), the window opens at the oldest check on record.
    """
    end = datetime.now(timezone.utc)
    if start is None:
        if not checks:
            return []
        start = min(c.checked_at for c in checks)

    width = (end - start) / points
    out = []
    for i in range(points):
        left    = start + i * width
        right   = start + (i + 1) * width
        ts      = left + width / 2

        prices = [c.price for c in checks if left <= c.checked_at < right]
        if prices:
            avg     = str((sum(prices) / len(prices)).quantize(Decimal("0.01")))
            best    = str(min(prices))
        else:
            avg = best = None

        out.append(SummaryPoint(
            ts=ts.isoformat(),
            avg=avg,
            best=best
        ))
    return out

async def _active_listings_for_item(db, user_id, item_id) -> list[Listings]:
    """The caller's live listings for one item — the starting point for every
    per-item rollup in this module.

    Scoped through `watches`, so one user never sees another's listings even
    though `items` is a shared catalog.
    """
    stmt = select(Listings
                ).join(Watches, Watches.id == Listings.watch_id
                ).where(Watches.user_id == user_id
                ).where(Listings.item_id == item_id
                ).where(Listings.active)

    return (await db.execute(stmt)).scalars().all()


# What counts as a "price drop": consecutive checks on the same active listing
# where the price fell by MORE than this fraction. Mirrors the hardcoded 0.03 in
# frontend/src/mocks/handlers.ts (countDrops) — change both or neither.
async def price_history(db, user_id, item_id, range, points: int) -> list[ListingSeries]:
    """One time series per live listing — the multi-line price-history chart.

    Each series is thinned to at most `points` samples: a listing checked hourly
    for a year would otherwise ship ~8,700 points to the browser.
    """
    listing_rows = await _active_listings_for_item(db, user_id, item_id)

    # Resolved once per request, not per listing — _range_start reads the clock
    # on every call, so doing it inside the loop would give each series its own
    # slightly different window.
    start = await _range_start(range)

    listing_series_list = []
    for listing in listing_rows:
        stmt = select(PriceChecks
                    ).where(PriceChecks.listing_id == listing.id
                    ).order_by(PriceChecks.checked_at)

        if start is not None:
            stmt = stmt.where(PriceChecks.checked_at >= start)

        checks = (await db.execute(stmt)).scalars().all()

        if len(checks) > points:
            price_points = await _create_price_points(checks, len(checks) / points)
        else:
            price_points = await _create_price_points(checks)

        site = await db.get(Sites, listing.site_id)
        listing_series_list.append(ListingSeries(
            listing_id=listing.id,
            site_name=site.name,
            title=listing.title,
            active=listing.active,
            points=price_points
        ))

    return listing_series_list


async def price_summary(db, user_id, item_id, range, points) -> list[SummaryPoint]:
    """Item-level avg/best price over time, pooled across all live listings.

    price_history keeps listings apart for a multi-line chart; this flattens
    them into one series for the summary view.
    """
    listing_rows = await _active_listings_for_item(db, user_id, item_id)
    start = await _range_start(range)

    all_checks = []

    for listing in listing_rows:
        stmt = select(PriceChecks
                ).where(PriceChecks.listing_id == listing.id
                ).order_by(PriceChecks.checked_at
                )
        if start is not None:
            stmt = stmt.where(PriceChecks.checked_at >= start)

        checks = (await db.execute(stmt)).scalars().all()
        all_checks.extend(checks)

    return await _create_summary_points(all_checks, start, points)

async def item_rollups(db, user_id, item, range)-> dict:
    pass


async def dashboard_stats(db, user_id, range) -> DashboardStats:
    pass


async def price_drops(db, user_id, range, limit) -> list[PriceDrop]:
    pass


async def category_price_change(db, user_id, item, range) -> list[CategoryItemChange]:
    pass


