"""Price aggregation math — every computed number the contract asks for.

Consumed by routers/charts.py, routers/items.py, routers/categories.py.

Responsibilities:
  - price_history(item, range, points): per-listing series of PricePoints.
  - price_summary(item, range, points): bucketed avg/best over time.
  - item_rollups(item): best_price, best_listing_id, best_site_name, avg_price,
    active_listing_count, target_met, pct_change_range, spark[] (<=30 buckets).
  - dashboard_stats(user, range): the four StatTiles (value, delta vs prev
    equal-length period, spark[]).
  - price_drops(user, range, limit): biggest recent drops.
  - category_price_change(category, range).

Bucketing: split [now-range, now] into N buckets; each point is the best/avg
price whose latest check falls in that bucket; null when the bucket is empty.
Prices in and out are decimal STRINGS.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import floor

from sqlalchemy import extract, func, select

from app.models import Items, Listings, PriceChecks, Sites, Watches
from app.schemas.charts import (
    CategoryItemChange,
    DashboardStats,
    ListingSeries,
    PriceDrop,
    PricePoint,
    StatTile,
    SummaryPoint,
)

_RANGE_DELTAS: dict[str, timedelta | None] = {
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "1y": timedelta(days=365),
    "all": None,
}

# What range="all" becomes for callers that cannot work unbounded. Anything
# drawing a fixed-width chart or measuring growth needs a left edge, and the mock
# picks a year in both of those places. Shared so the two can't drift apart.
_ALL_RANGE_FALLBACK = timedelta(days=365)


async def _range_start(range: str) -> datetime | None:
    """Lower bound for a TimeRange, or None for "all" — which means no bound.

    What None *implies* is the caller's call, and they disagree on purpose:
    price_drops treats it as "don't filter", while dashboard_stats and
    _best_price_spark substitute _ALL_RANGE_FALLBACK because a growth tile and a
    sparkline both need some window to measure against.
    """
    delta = _RANGE_DELTAS[range]
    return None if delta is None else datetime.now(UTC) - delta


def _clamp_points(points: int) -> int:
    """Keep a caller-supplied `points` inside a range the math can survive.

    Both series functions divide by `points`, so 0 or a negative from the query
    string would be a 500. The upper bound mirrors the mock, which caps at 500
    before downsampling — past that the browser gains nothing from more dots.
    """
    return max(1, min(500, points))


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

        price_point_list.append(
            PricePoint(
                ts=current_check.checked_at.isoformat(),
                price=str(current_check.price),
                in_stock=current_check.in_stock,
            )
        )
        steps += step

    return price_point_list


async def _create_summary_points(checks, start, points) -> list[SummaryPoint]:
    """Bucket pooled checks into `points` equal time slices.

    One SummaryPoint per slice, stamped at the slice midpoint, carrying the
    average and cheapest price seen inside it. An empty slice reports None/None,
    never 0 — the contract distinguishes "unknown" from "free".

    With start=None ("all"), the window opens at the oldest check on record.
    """
    end = datetime.now(UTC)
    if start is None:
        if not checks:
            return []
        start = min(c.checked_at for c in checks)

    width = (end - start) / points
    out = []
    for i in range(points):
        left = start + i * width
        right = start + (i + 1) * width
        ts = left + width / 2

        prices = [c.price for c in checks if left <= c.checked_at < right]
        if prices:
            avg = str((sum(prices) / len(prices)).quantize(Decimal("0.01")))
            best = str(min(prices))
        else:
            avg = best = None

        out.append(SummaryPoint(ts=ts.isoformat(), avg=avg, best=best))
    return out


async def _generate_spark(now: int, before: int) -> list[int]:
    """12-point linear ramp from `before` to `now`.

    Deliberately not real history — it's a shape, matching growthSpark in the
    mock handlers. Every dashboard StatTile draws its sparkline this way.
    """
    return [round(before + (now - before) * b / 11) for b in range(12)]


# Bucket count for ItemSummary.spark. The contract says "<=30 points"; the mock
# emits exactly 30, or none at all, so we do too.
_SPARK_BUCKETS = 30


async def _best_price_spark(db, listings, range) -> list[str | None]:
    """`_SPARK_BUCKETS` buckets of cheapest-price-over-the-range, oldest first.

    Behavioral oracle: sparkline() in frontend/src/mocks/fixtures.ts.

    NOT the same thing as StatTile.spark, despite the contract calling both
    "spark". That one is a fake 12-point ramp between two counts
    (_generate_spark); this one is real bucketed price history. They share
    nothing but the name — don't unify them.

    `listings` is the caller's already-scoped active listings (from
    _active_listings_for_item). Ownership and the active filter live there, so
    this only has to bucket — hence no join back through watches.

    Returns [] — not `_SPARK_BUCKETS` nulls — when there are no live listings.
    The frontend draws nothing at all in that case rather than a flat line at
    zero, and the mock bails the same way before allocating its array.
    """
    if not listings:
        return []

    now = datetime.now(UTC)
    start = await _range_start(range)
    if start is None:
        start = now - _ALL_RANGE_FALLBACK
    width_seconds = (now - start).total_seconds() / _SPARK_BUCKETS

    # Bucketing happens in SQL so Postgres collapses a year of checks into at
    # most _SPARK_BUCKETS rows instead of shipping every one of them here.
    # least() clamps a clock-skewed future check into the last bucket instead of
    # indexing off the end — the same guard as the mock's Math.min.
    bucket = func.least(
        _SPARK_BUCKETS - 1,
        func.floor(extract("epoch", PriceChecks.checked_at - start) / width_seconds),
    ).label("bucket")

    stmt = (
        select(bucket, func.min(PriceChecks.price))
        .where(PriceChecks.listing_id.in_([listing.id for listing in listings]))
        # `price > 0` also drops unpriced checks (NULL > 0 is NULL, not true) —
        # the same filter the rest of this module uses.
        .where(PriceChecks.price > 0)
        .where(PriceChecks.checked_at >= start)
        .group_by(bucket)
    )

    # Empty buckets keep their None: the contract distinguishes "no data here"
    # from "free", so a gap must never serialize as 0.
    spark: list[str | None] = [None] * _SPARK_BUCKETS
    for bucket_index, best_price in (await db.execute(stmt)).all():
        spark[int(bucket_index)] = str(best_price)
    return spark


async def _active_listings_for_item(db, user_id, item_id) -> list[Listings]:
    """The caller's live listings for one item — the starting point for every
    per-item rollup in this module.

    Scoped through `watches`, so one user never sees another's listings even
    though `items` is a shared catalog.
    """
    stmt = (
        select(Listings)
        .join(Watches, Watches.id == Listings.watch_id)
        .where(Watches.user_id == user_id)
        .where(Listings.item_id == item_id)
        .where(Listings.active)
    )

    return (await db.execute(stmt)).scalars().all()


# What counts as a "price drop": consecutive checks on the same active listing
# where the price fell by MORE than this fraction. Mirrors the hardcoded 0.03 in
# frontend/src/mocks/handlers.ts (countDrops) — change both or neither.
_DROP_THRESHOLD = Decimal("0.03")


async def _count_listings_with_drop(db, user_id, start, end) -> int:
    """How many of the user's active listings dropped >3% within [start, end].

    Counts LISTINGS, not drop events: a listing that sawtooths five times still
    counts once (the mock `break`s after the first qualifying pair). LAG() pairs
    each check with the previous one for the same listing, so Postgres walks the
    series instead of us pulling every check into Python.

    Note the window is computed AFTER the WHERE clause — SQL evaluates window
    functions last — so a check just outside the range is never treated as the
    "previous" price. That matches the mock, which filters before it walks.
    """
    previous_price = (
        func.lag(PriceChecks.price)
        .over(
            partition_by=PriceChecks.listing_id,
            order_by=PriceChecks.checked_at,
        )
        .label("previous_price")
    )

    # `price > 0` also drops NULLs (NULL > 0 is NULL, not true) — same filter
    # item_rollups uses, so "a priced check" means one thing across this module.
    paired_checks = (
        select(PriceChecks.listing_id, PriceChecks.price, previous_price)
        .select_from(PriceChecks)
        .join(Listings, Listings.id == PriceChecks.listing_id)
        .join(Watches, Watches.id == Listings.watch_id)
        .where(Watches.user_id == user_id)
        .where(Listings.active)
        .where(PriceChecks.price > 0)
        .where(PriceChecks.checked_at >= start)
        .where(PriceChecks.checked_at <= end)
        .subquery()
    )

    drop_fraction = (
        paired_checks.c.previous_price - paired_checks.c.price
    ) / paired_checks.c.previous_price
    stmt = (
        select(func.count(func.distinct(paired_checks.c.listing_id)))
        .where(
            paired_checks.c.previous_price.is_not(None)
        )  # first check of a listing has no predecessor
        .where(paired_checks.c.previous_price > paired_checks.c.price)
        .where(drop_fraction > _DROP_THRESHOLD)
    )
    return (await db.execute(stmt)).scalar_one()


async def _count_snagged_watches(db, user_id) -> int:
    """Watches whose cheapest live listing is at or under their target price.

    Same rule as item_rollups' `target_met`, but answered for every watch in one
    query rather than per item. A watch with no target_price can never be
    snagged, so it is excluded rather than counted as met.
    """
    # rn == 1 picks the most recent check per listing; then take the cheapest of
    # those per watch. Two steps, because "latest" and "cheapest" disagree.
    latest_check_per_listing = (
        select(
            Listings.watch_id.label("watch_id"),
            PriceChecks.price.label("price"),
            func.row_number()
            .over(
                partition_by=PriceChecks.listing_id,
                order_by=PriceChecks.checked_at.desc(),
            )
            .label("rn"),
        )
        .select_from(PriceChecks)
        .join(Listings, Listings.id == PriceChecks.listing_id)
        .join(Watches, Watches.id == Listings.watch_id)
        .where(Watches.user_id == user_id)
        .where(Listings.active)
        .where(PriceChecks.price > 0)
        .subquery()
    )

    best_price_per_watch = (
        select(
            latest_check_per_listing.c.watch_id,
            func.min(latest_check_per_listing.c.price).label("best_price"),
        )
        .where(latest_check_per_listing.c.rn == 1)
        .group_by(latest_check_per_listing.c.watch_id)
        .subquery()
    )

    stmt = (
        select(func.count())
        .select_from(best_price_per_watch)
        .join(Watches, Watches.id == best_price_per_watch.c.watch_id)
        .where(Watches.target_price.is_not(None))
        .where(best_price_per_watch.c.best_price <= Watches.target_price)
    )
    return (await db.execute(stmt)).scalar_one()


async def price_history(db, user_id, item_id, range, points: int) -> list[ListingSeries]:
    """One time series per live listing — the multi-line price-history chart.

    Each series is thinned to at most `points` samples: a listing checked hourly
    for a year would otherwise ship ~8,700 points to the browser.

    Unpriced checks are skipped. The agent records a check with price=NULL when a
    listing is sold or unavailable (agent/tools.py save_price_check), and a chart
    point needs a number — the mock's downsample() drops them the same way.
    """
    listing_rows = await _active_listings_for_item(db, user_id, item_id)
    points = _clamp_points(points)

    # Resolved once per request, not per listing — _range_start reads the clock
    # on every call, so doing it inside the loop would give each series its own
    # slightly different window.
    start = await _range_start(range)

    listing_series_list = []
    for listing in listing_rows:
        stmt = (
            select(PriceChecks)
            .where(PriceChecks.listing_id == listing.id)
            .where(PriceChecks.price > 0)
            .order_by(PriceChecks.checked_at)
        )

        if start is not None:
            stmt = stmt.where(PriceChecks.checked_at >= start)

        checks = (await db.execute(stmt)).scalars().all()

        if len(checks) > points:
            price_points = await _create_price_points(checks, len(checks) / points)
        else:
            price_points = await _create_price_points(checks)

        site = await db.get(Sites, listing.site_id)
        listing_series_list.append(
            ListingSeries(
                listing_id=listing.id,
                site_name=site.name,
                title=listing.title,
                active=listing.active,
                points=price_points,
            )
        )

    return listing_series_list


async def price_summary(db, user_id, item_id, range, points) -> list[SummaryPoint]:
    """Item-level avg/best price over time, pooled across all live listings.

    price_history keeps listings apart for a multi-line chart; this flattens
    them into one series for the summary view.

    Unpriced checks are skipped — averaging over a NULL is not a number. See
    price_history for why they exist.
    """
    listing_rows = await _active_listings_for_item(db, user_id, item_id)
    points = _clamp_points(points)
    start = await _range_start(range)

    all_checks = []

    for listing in listing_rows:
        stmt = (
            select(PriceChecks)
            .where(PriceChecks.listing_id == listing.id)
            .where(PriceChecks.price > 0)
            .order_by(PriceChecks.checked_at)
        )
        if start is not None:
            stmt = stmt.where(PriceChecks.checked_at >= start)

        checks = (await db.execute(stmt)).scalars().all()
        all_checks.extend(checks)

    return await _create_summary_points(all_checks, start, points)


async def item_rollups(db, user_id, item, watch, range) -> dict:
    """The computed half of an ItemSummary row, keyed to splat straight in.

    Keys match ItemSummary's computed fields exactly, so build_item_summary can
    `**` the result. Every value is derived from listings + price_checks — none
    of it is stored, and none of it should become a column.

    Values stay Decimal/datetime while the math runs and are serialized to
    decimal strings / ISO timestamps in one pass at the end.
    """
    listing_rows = await _active_listings_for_item(db, user_id, item.id)

    start = await _range_start(range)

    item_rollup = {
        "best_price": None,
        "best_listing_id": None,
        "best_site_name": None,
        "avg_price": None,
        "active_listing_count": len(listing_rows),
        "target_met": None,
        "pct_change_range": None,
        "last_checked_at": None,
    }

    prices = []
    best_old_price = None
    best_site_id = None
    for listing in listing_rows:
        stmt = (
            select(PriceChecks)
            .where(PriceChecks.listing_id == listing.id)
            .where(PriceChecks.price > 0)
            .order_by(PriceChecks.checked_at.desc())
            .limit(1)
        )

        check = (await db.execute(stmt)).scalar_one_or_none()
        if check is None:
            continue

        if item_rollup["best_price"] is None or check.price < item_rollup["best_price"]:
            item_rollup["best_price"] = check.price
            item_rollup["best_listing_id"] = check.listing_id
            best_site_id = listing.site_id
        if (
            item_rollup["last_checked_at"] is None
            or check.checked_at > item_rollup["last_checked_at"]
        ):
            item_rollup["last_checked_at"] = check.checked_at

        if start is not None:
            stmt = (
                select(PriceChecks)
                .where(PriceChecks.listing_id == listing.id)
                .where(PriceChecks.price > 0)
                .where(PriceChecks.checked_at <= start)
                .order_by(PriceChecks.checked_at.desc())
                .limit(1)
            )
            old_check = (await db.execute(stmt)).scalar_one_or_none()

            if old_check and (best_old_price is None or old_check.price < best_old_price):
                best_old_price = old_check.price

        prices.append(check.price)

    item_rollup["best_site_name"] = (
        (await db.get(Sites, best_site_id)).name if best_site_id is not None else None
    )

    best_price = item_rollup["best_price"]  # still Decimal|None here; serialized below
    target = watch.target_price
    item_rollup["target_met"] = (
        best_price is not None and target is not None and best_price <= target
    )

    item_rollup["avg_price"] = (
        str((sum(prices) / len(prices)).quantize(Decimal("0.01"))) if prices else None
    )

    if best_price is not None and best_old_price is not None and best_old_price > 0:
        change = (best_price - best_old_price) / best_old_price * 100
        item_rollup["pct_change_range"] = f"{change:+.2f}"
    else:
        item_rollup["pct_change_range"] = None

    # serialize for the contract: prices as decimal strings, timestamps as ISO
    item_rollup["best_price"] = str(best_price) if best_price is not None else None
    if item_rollup["last_checked_at"] is not None:
        item_rollup["last_checked_at"] = item_rollup["last_checked_at"].isoformat()

    # Reuses the listings already fetched above — see _best_price_spark for why
    # it takes rows rather than re-querying, and why this is unrelated to the
    # dashboard's StatTile.spark.
    item_rollup["spark"] = await _best_price_spark(db, listing_rows, range)

    return item_rollup


async def dashboard_stats(db, user_id, range) -> DashboardStats:
    """The four dashboard StatTiles. Behavioral oracle: the mock handler for
    GET /api/dashboard/stats in frontend/src/mocks/handlers.ts.

    Every tile is {value, delta, spark}, but what `delta` compares against is
    NOT uniform — this mirrors the mock deliberately:

      tracked_items    | now vs. how many already existed at range start, so
      active_listings  | delta reads as "added during this range"
      price_drops      | now vs. the previous equal-length window — a true
                       | period-over-period comparison
      snagged          | placeholder; see the note at that tile

    `spark` is NOT real history. It's a 12-point linear ramp from the previous
    value to the current one (_generate_spark, mirroring the mock's growthSpark).
    The contract defines it that way — turning it into a real time series is a
    frontend-visible change, not a backend cleanup.
    """
    now = datetime.now(UTC)
    start = await _range_start(range)
    if start is None:
        # range="all" has no start bound, but the tiles still need a window to
        # measure growth against. The mock charts a year here; match it.
        start = now - _ALL_RANGE_FALLBACK

    # Tracked items
    stmt = select(func.count(Watches.id)).where(Watches.user_id == user_id)
    current_watch_count = (await db.execute(stmt)).scalar_one_or_none()

    stmt = (
        select(func.count(Watches.id))
        .where(Watches.user_id == user_id)
        .where(Watches.created_at <= start)
    )
    start_of_range_watch_count = (await db.execute(stmt)).scalar_one_or_none()

    tracked_item_spark = await _generate_spark(current_watch_count, start_of_range_watch_count)

    tracked_stat_tile = StatTile(
        value=current_watch_count,
        delta=(current_watch_count - start_of_range_watch_count),
        spark=tracked_item_spark,
    )

    # Listings
    stmt = (
        select(func.count(Listings.id))
        .join(Watches, Watches.id == Listings.watch_id)
        .where(Watches.user_id == user_id)
        .where(Listings.active)
    )

    current_active_listing_count = (await db.execute(stmt)).scalar_one_or_none()

    stmt = (
        select(func.count(Listings.id))
        .join(Watches, Watches.id == Listings.watch_id)
        .where(Watches.user_id == user_id)
        .where(Listings.active)
        .where(Listings.created_at <= start)
    )

    current_listings_at_start_of_range = (await db.execute(stmt)).scalar_one_or_none()

    listing_spark = await _generate_spark(
        current_active_listing_count, current_listings_at_start_of_range
    )

    listing_stat_tile = StatTile(
        value=current_active_listing_count,
        delta=(current_active_listing_count - current_listings_at_start_of_range),
        spark=listing_spark,
    )

    # Price drops
    # The one tile with a real period-over-period delta: this range's drops
    # against the immediately preceding window of the same length.
    previous_start = start - (now - start)
    current_drop_count = await _count_listings_with_drop(db, user_id, start, now)
    previous_drop_count = await _count_listings_with_drop(db, user_id, previous_start, start)

    price_drops_stat_tile = StatTile(
        value=current_drop_count,
        delta=(current_drop_count - previous_drop_count),
        spark=await _generate_spark(current_drop_count, previous_drop_count),
    )

    # Snagged
    # Watches sitting at or under their target price right now.
    # KNOWN GAP: delta is a placeholder. A truthful "how many were snagged at
    # range start" means replaying each watch's price history against its target
    # at that time; the mock punts with min(value, 1), so we mirror it to stay
    # contract-accurate. Revisit if the dashboard ever needs the real number.
    snagged_count = await _count_snagged_watches(db, user_id)

    snagged_stat_tile = StatTile(
        value=snagged_count,
        delta=min(snagged_count, 1),
        spark=await _generate_spark(snagged_count, max(0, snagged_count - 1)),
    )

    return DashboardStats(
        tracked_items=tracked_stat_tile,
        active_listings=listing_stat_tile,
        price_drops=price_drops_stat_tile,
        snagged=snagged_stat_tile,
    )


async def price_drops(db, user_id, range, limit) -> list[PriceDrop]:
    """The user's biggest recent price drops, newest first. Behavioral oracle:
    the mock handler for GET /api/dashboard/price-drops in
    frontend/src/mocks/handlers.ts.

    At most ONE row per listing — its most recent qualifying drop. A listing on
    a long slide would otherwise fill the whole table ("one drop per listing
    keeps the table varied", per the mock).

    Two rules differ from _count_listings_with_drop, both deliberately:

      * Only the NEWER check of a pair must fall inside the range. Its
        predecessor may be older than `start` — that's how a listing last
        checked months ago still reports a real drop when it's re-checked today.
      * range="all" means no lower bound at all, not the 365-day fallback that
        dashboard_stats uses for its growth window.

    They share the >3% threshold (_DROP_THRESHOLD) and the "active listings,
    priced checks only" filters.
    """
    start = await _range_start(range)
    limit = max(0, limit)  # Postgres rejects a negative LIMIT outright

    # Step 1 — pair every priced check with its predecessor on the same listing.
    # Deliberately NOT range-filtered: see the docstring, `previous_price` is
    # allowed to come from before the window.
    previous_price = (
        func.lag(PriceChecks.price)
        .over(
            partition_by=PriceChecks.listing_id,
            order_by=PriceChecks.checked_at,
        )
        .label("previous_price")
    )

    paired_checks = (
        select(
            PriceChecks.listing_id,
            PriceChecks.price,
            PriceChecks.currency,
            PriceChecks.checked_at,
            previous_price,
        )
        .select_from(PriceChecks)
        .join(Listings, Listings.id == PriceChecks.listing_id)
        .join(Watches, Watches.id == Listings.watch_id)
        .where(Watches.user_id == user_id)
        .where(Listings.active)
        .where(PriceChecks.price > 0)
        .subquery()
    )

    # Step 2 — keep the pairs that are real drops landing inside the range, and
    # rank each listing's drops newest-first so step 3 can take just the latest.
    drop_fraction = (
        paired_checks.c.previous_price - paired_checks.c.price
    ) / paired_checks.c.previous_price
    qualifying = (
        select(
            paired_checks.c.listing_id,
            paired_checks.c.price,
            paired_checks.c.previous_price,
            paired_checks.c.currency,
            paired_checks.c.checked_at,
            func.row_number()
            .over(
                partition_by=paired_checks.c.listing_id,
                order_by=paired_checks.c.checked_at.desc(),
            )
            .label("recency_rank"),
        )
        .where(
            paired_checks.c.previous_price.is_not(None)
        )  # first check of a listing has no predecessor
        .where(paired_checks.c.previous_price > paired_checks.c.price)
        .where(drop_fraction > _DROP_THRESHOLD)
    )
    if start is not None:
        qualifying = qualifying.where(paired_checks.c.checked_at >= start)
    qualifying = qualifying.subquery()

    # Step 3 — one row per listing (the newest drop), joined to the names the
    # table displays, newest first, capped at `limit`.
    stmt = (
        select(
            qualifying.c.listing_id,
            qualifying.c.price,
            qualifying.c.previous_price,
            qualifying.c.currency,
            qualifying.c.checked_at,
            Items.id.label("item_id"),
            Items.name.label("item_name"),
            Sites.name.label("site_name"),
        )
        .select_from(qualifying)
        .join(Listings, Listings.id == qualifying.c.listing_id)
        .join(Items, Items.id == Listings.item_id)
        .join(Sites, Sites.id == Listings.site_id)
        .where(qualifying.c.recency_rank == 1)
        .order_by(qualifying.c.checked_at.desc())
        .limit(limit)
    )

    rows = (await db.execute(stmt)).all()

    return [
        PriceDrop(
            item_id=row.item_id,
            item_name=row.item_name,
            listing_id=row.listing_id,
            site_name=row.site_name,
            old_price=str(row.previous_price),
            new_price=str(row.price),
            currency=row.currency,
            # Always negative — we only selected drops — so the minus sign comes
            # for free. That's why this is `.2f` and not the `+.2f` that
            # item_rollups needs for pct_change_range, which can go either way.
            pct_change=f"{(row.price - row.previous_price) / row.previous_price * 100:.2f}",
            checked_at=row.checked_at.isoformat(),
        )
        for row in rows
    ]


async def _best_price_per_item_as_of(db, user_id, category_id, as_of) -> dict[int, Decimal]:
    """{item_id: cheapest live price} for the user's watched items in one
    category, as the world looked at `as_of`. Pass as_of=None for "right now".

    Mirrors bestPriceAt() in frontend/src/mocks/fixtures.ts: per active listing
    take its most recent check at-or-before `as_of`, then the cheapest of those
    across the item's listings. Items with no priced check yet are simply absent
    from the dict — callers treat missing as null, not zero.
    """
    latest_check_per_listing = (
        select(
            Listings.item_id.label("item_id"),
            PriceChecks.price.label("price"),
            func.row_number()
            .over(
                partition_by=PriceChecks.listing_id,
                order_by=PriceChecks.checked_at.desc(),
            )
            .label("rn"),
        )
        .select_from(PriceChecks)
        .join(Listings, Listings.id == PriceChecks.listing_id)
        .join(Watches, Watches.id == Listings.watch_id)
        .join(Items, Items.id == Listings.item_id)
        .where(Watches.user_id == user_id)
        .where(Items.category_id == category_id)
        .where(Listings.active)
        .where(PriceChecks.price > 0)
    )
    if as_of is not None:
        # The rank is computed over the filtered rows, so rn == 1 is the newest
        # check that had already happened at `as_of` — not the newest overall.
        latest_check_per_listing = latest_check_per_listing.where(PriceChecks.checked_at <= as_of)
    latest_check_per_listing = latest_check_per_listing.subquery()

    stmt = (
        select(
            latest_check_per_listing.c.item_id,
            func.min(latest_check_per_listing.c.price),
        )
        .where(latest_check_per_listing.c.rn == 1)
        .group_by(latest_check_per_listing.c.item_id)
    )
    return {item_id: price for item_id, price in (await db.execute(stmt)).all()}


async def category_price_change(db, user_id, category_id, range) -> list[CategoryItemChange]:
    """Per-item best-price movement across one category, oldest baseline vs now.
    Behavioral oracle: the mock handler for GET /api/categories/:id/price-change
    in frontend/src/mocks/handlers.ts.

    DIVERGENCE FROM THE MOCK, on purpose: the mock lists every item in the
    category because its store has only one user. Here we list the caller's
    WATCHED items in that category, matching GET /api/items — otherwise one
    user's catalog would leak into another's category view.

    range="all" yields a null pct_change for every item. There is no baseline
    before the beginning of time, and the mock agrees: it asks for the best
    price at epoch, which is always null. Absent data stays null, never 0.
    """
    start = await _range_start(range)

    watched_items = (
        select(Items.id, Items.name)
        .join(Watches, Watches.item_id == Items.id)
        .where(Watches.user_id == user_id)
        .where(Items.category_id == category_id)
        .order_by(Items.name)
    )
    item_rows = (await db.execute(watched_items)).all()

    new_best_by_item = await _best_price_per_item_as_of(db, user_id, category_id, None)
    # start is None only for range="all" — see the docstring; no baseline exists.
    old_best_by_item = (
        {} if start is None else await _best_price_per_item_as_of(db, user_id, category_id, start)
    )

    changes = []
    for item_id, item_name in item_rows:
        old_best = old_best_by_item.get(item_id)
        new_best = new_best_by_item.get(item_id)

        # Needs both ends to be a change at all; old_best > 0 guards the divide.
        # Signed like item_rollups' pct_change_range — this one can go up or
        # down, unlike price_drops which is always negative.
        pct_change = None
        if old_best is not None and new_best is not None and old_best > 0:
            pct_change = f"{(new_best - old_best) / old_best * 100:+.2f}"

        changes.append(
            CategoryItemChange(
                item_id=item_id,
                name=item_name,
                pct_change=pct_change,
                old_best=str(old_best) if old_best is not None else None,
                new_best=str(new_best) if new_best is not None else None,
            )
        )
    return changes
