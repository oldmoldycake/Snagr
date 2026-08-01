"""services/aggregates.py — the computed half of the contract.

None of these numbers are stored. best_price, sparklines, dashboard tiles and
percentage moves are all derived from `listings` + `price_checks` on every
request, which makes this module the easiest place in the backend to break
something silently: a wrong aggregate still returns 200.

The behavioral oracle is the frontend mock (`frontend/src/mocks/handlers.ts` and
`fixtures.ts`). Where a rule looks arbitrary, it is almost always mirroring the
mock on purpose, and the test says so.

These call the service functions directly rather than going through HTTP — the
router layer is covered in test_charts_api.py. `sc` is the Scenario builder from
tests/factories.py; see that module for the graph it builds.

Two invariants are asserted all over this file rather than in one place, because
they are the two that actually break in practice:
  * prices are decimal STRINGS ("80.00"), never numbers
  * absent data is None, never 0
"""

from datetime import UTC
from decimal import Decimal

import pytest
from app.services.aggregates import (
    _clamp_points,
    _count_listings_with_drop,
    _range_start,
    category_price_change,
    dashboard_stats,
    item_rollups,
    price_drops,
    price_history,
    price_summary,
)

# --- range + points plumbing --------------------------------------------------
#
# _range_start returns None for "all", and each caller decides what that means.
# The disagreement is deliberate: price_drops treats None as "no lower bound",
# dashboard_stats substitutes a year because a growth tile needs a window.

async def test_range_start_is_none_for_all():
    assert await _range_start("all") is None


@pytest.mark.parametrize("range_name,expected_days", [
    ("7d", 7), ("30d", 30), ("90d", 90), ("1y", 365),
])
async def test_range_start_offsets_by_the_named_window(range_name, expected_days):
    from datetime import datetime
    start = await _range_start(range_name)
    actual_days = (datetime.now(UTC) - start).days
    assert actual_days == expected_days


def test_points_below_one_is_clamped():
    # Both series functions divide by `points`; 0 from the query string used to
    # be a 500. Guarded rather than rejected, so the endpoint stays lenient.
    assert _clamp_points(0) == 1
    assert _clamp_points(-5) == 1


def test_points_capped_at_the_mock_ceiling():
    # The mock caps at 500 before downsampling; past that the browser gains
    # nothing from more dots.
    assert _clamp_points(9999) == 500
    assert _clamp_points(300) == 300


# --- price_history ------------------------------------------------------------
#
# One series per LIVE listing the caller owns, each thinned to <= `points`.

async def test_price_history_one_series_per_active_listing(sc):
    item, watch = await sc.tracked()
    first = await sc.listing(watch, item, "a")
    second = await sc.listing(watch, item, "b")
    await sc.checks(first, (10, "100.00"))
    await sc.checks(second, (10, "120.00"))

    series = await price_history(sc.db, sc.user_id, item.id, "30d", 300)

    assert {s.listing_id for s in series} == {first.id, second.id}


async def test_price_history_excludes_inactive_listings(sc):
    item, watch = await sc.tracked()
    live = await sc.listing(watch, item, "live")
    dead = await sc.listing(watch, item, "dead", active=False)
    await sc.checks(live, (10, "100.00"))
    await sc.checks(dead, (10, "1.00"))

    series = await price_history(sc.db, sc.user_id, item.id, "30d", 300)

    assert [s.listing_id for s in series] == [live.id]


async def test_price_history_excludes_other_users_listings(sc):
    # `items` is a shared catalog, so two users can watch the same item. Every
    # query joins through `watches` to keep their listings apart.
    item = await sc.item()
    mine = await sc.watch(item)
    theirs = await sc.watch(item, user=await sc.other_user())
    my_listing = await sc.listing(mine, item, "mine")
    their_listing = await sc.listing(theirs, item, "theirs")
    await sc.checks(my_listing, (10, "100.00"))
    await sc.checks(their_listing, (10, "5.00"))

    series = await price_history(sc.db, sc.user_id, item.id, "30d", 300)

    assert [s.listing_id for s in series] == [my_listing.id]


async def test_price_history_skips_unpriced_checks(sc):
    """Regression: an unpriced check used to serialize as the string "None".

    The agent writes price=NULL when a listing is sold or unavailable
    (agent/tools.py save_price_check), so this is live data, not a corner case.
    """
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (10, "100.00"), (5, None))

    series = await price_history(sc.db, sc.user_id, item.id, "30d", 300)

    assert [p.price for p in series[0].points] == ["100.00"]


async def test_price_history_downsamples_to_points(sc):
    # 10 checks thinned to 5 walks the list at stride 2 -> indices 0,2,4,6,8.
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, *[(20 - 2 * i, str(100 - i) + ".00") for i in range(10)])

    series = await price_history(sc.db, sc.user_id, item.id, "30d", 5)

    assert [p.price for p in series[0].points] == [
        "100.00", "98.00", "96.00", "94.00", "92.00",
    ]


async def test_price_history_keeps_everything_under_the_cap(sc):
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, *[(20 - 2 * i, str(100 - i) + ".00") for i in range(10)])

    series = await price_history(sc.db, sc.user_id, item.id, "30d", 300)

    assert len(series[0].points) == 10


async def test_price_history_respects_the_range_window(sc):
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (40, "200.00"), (10, "100.00"))

    within = await price_history(sc.db, sc.user_id, item.id, "30d", 300)
    everything = await price_history(sc.db, sc.user_id, item.id, "all", 300)

    assert [p.price for p in within[0].points] == ["100.00"]
    assert [p.price for p in everything[0].points] == ["200.00", "100.00"]


async def test_price_history_is_empty_without_listings(sc):
    item, _ = await sc.tracked()
    assert await price_history(sc.db, sc.user_id, item.id, "30d", 300) == []


async def test_price_history_survives_points_zero(sc):
    # Regression: `?points=0` divided by zero and 500'd.
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (10, "100.00"))

    series = await price_history(sc.db, sc.user_id, item.id, "30d", 0)

    assert len(series[0].points) == 1


# --- price_summary ------------------------------------------------------------
#
# Same checks as price_history, but pooled across listings and bucketed into
# `points` equal time slices with an avg and a best per slice.

async def test_price_summary_returns_one_point_per_bucket(sc):
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (10, "100.00"))

    assert len(await price_summary(sc.db, sc.user_id, item.id, "30d", 4)) == 4


async def test_price_summary_empty_bucket_is_null_never_zero(sc):
    # "No data" and "free" must not look the same to the chart.
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (2, "100.00"))     # only the newest bucket has data

    points = await price_summary(sc.db, sc.user_id, item.id, "30d", 4)

    assert points[0].avg is None and points[0].best is None
    assert not any(p.avg == "0.00" or p.best == "0.00" for p in points)


async def test_price_summary_averages_and_takes_the_best(sc):
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    # all three land in the newest quarter of a 30d window
    await sc.checks(listing, (6, "90.00"), (4, "80.00"), (2, "70.00"))

    newest = (await price_summary(sc.db, sc.user_id, item.id, "30d", 4))[-1]

    assert newest.avg == "80.00"     # (90 + 80 + 70) / 3
    assert newest.best == "70.00"


async def test_price_summary_pools_across_listings(sc):
    item, watch = await sc.tracked()
    cheap = await sc.listing(watch, item, "cheap")
    dear = await sc.listing(watch, item, "dear")
    await sc.checks(cheap, (2, "50.00"))
    await sc.checks(dear, (2, "150.00"))

    newest = (await price_summary(sc.db, sc.user_id, item.id, "30d", 4))[-1]

    assert newest.avg == "100.00"    # one series, not two
    assert newest.best == "50.00"


async def test_price_summary_skips_unpriced_checks(sc):
    """Regression: a NULL price raised TypeError inside the average."""
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (2, "100.00"), (1, None))

    newest = (await price_summary(sc.db, sc.user_id, item.id, "30d", 4))[-1]

    assert newest.avg == "100.00"


async def test_price_summary_is_empty_for_all_range_without_checks(sc):
    # "all" has no lower bound to anchor buckets to, so with nothing recorded
    # there is no window at all — an empty list, not N empty buckets.
    item, watch = await sc.tracked()
    await sc.listing(watch, item)

    assert await price_summary(sc.db, sc.user_id, item.id, "all", 4) == []


async def test_price_summary_survives_points_zero(sc):
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (10, "100.00"))

    assert len(await price_summary(sc.db, sc.user_id, item.id, "30d", 0)) == 1


# --- item_rollups -------------------------------------------------------------
#
# The computed fields on an item-list row. Returns a dict whose keys are splatted
# straight into ItemSummary, so key names are part of the contract.

async def test_item_rollups_takes_the_cheapest_live_listing(sc):
    item, watch = await sc.tracked(target_price="85.00")
    cheap = await sc.listing(watch, item, "cheap")
    dear = await sc.listing(watch, item, "dear")
    await sc.checks(cheap, (40, "100.00"), (5, "80.00"))
    await sc.checks(dear, (40, "120.00"), (5, "90.00"))

    rollup = await item_rollups(sc.db, sc.user_id, item, watch, "30d")

    assert rollup["best_price"] == "80.00"
    assert rollup["best_listing_id"] == cheap.id
    assert rollup["best_site_name"] == "TestBay"
    assert rollup["active_listing_count"] == 2
    assert rollup["avg_price"] == "85.00"      # mean of each listing's LATEST price


async def test_item_rollups_without_listings_is_all_null(sc):
    item, watch = await sc.tracked(target_price="85.00")

    rollup = await item_rollups(sc.db, sc.user_id, item, watch, "30d")

    assert rollup["best_price"] is None
    assert rollup["avg_price"] is None
    assert rollup["last_checked_at"] is None
    assert rollup["active_listing_count"] == 0
    assert rollup["target_met"] is False       # no price cannot meet a target


async def test_item_rollups_listing_without_priced_checks(sc):
    item, watch = await sc.tracked(target_price="85.00")
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (5, None))        # sold, no price

    rollup = await item_rollups(sc.db, sc.user_id, item, watch, "30d")

    assert rollup["active_listing_count"] == 1   # the listing exists...
    assert rollup["best_price"] is None          # ...but has no usable price


async def test_item_rollups_target_met_on_exact_match(sc):
    # The comparison is <=, so landing exactly on the target counts as snagged.
    item, watch = await sc.tracked(target_price="80.00")
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (5, "80.00"))

    rollup = await item_rollups(sc.db, sc.user_id, item, watch, "30d")

    assert rollup["target_met"] is True


async def test_item_rollups_target_met_false_without_a_target(sc):
    item, watch = await sc.tracked(target_price=None)
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (5, "1.00"))

    rollup = await item_rollups(sc.db, sc.user_id, item, watch, "30d")

    assert rollup["target_met"] is False


async def test_item_rollups_pct_change_baselines_before_the_range(sc):
    # The baseline is the last check at or before range start, not the oldest
    # check inside it — otherwise the first move of the window is invisible.
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (40, "100.00"), (5, "80.00"))

    rollup = await item_rollups(sc.db, sc.user_id, item, watch, "30d")

    assert rollup["pct_change_range"] == "-20.00"


async def test_item_rollups_pct_change_is_signed_for_rises(sc):
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (40, "100.00"), (5, "120.00"))

    rollup = await item_rollups(sc.db, sc.user_id, item, watch, "30d")

    assert rollup["pct_change_range"] == "+20.00"


async def test_item_rollups_pct_change_null_without_baseline(sc):
    # range="all" has no "before", so there is nothing to compare against.
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (5, "80.00"))

    rollup = await item_rollups(sc.db, sc.user_id, item, watch, "all")

    assert rollup["pct_change_range"] is None


async def test_item_rollups_ignores_other_users_listings(sc):
    item = await sc.item()
    mine = await sc.watch(item, target_price="85.00")
    theirs = await sc.watch(item, user=await sc.other_user())
    my_listing = await sc.listing(mine, item, "mine")
    their_listing = await sc.listing(theirs, item, "theirs")
    await sc.checks(my_listing, (5, "100.00"))
    await sc.checks(their_listing, (5, "1.00"))    # cheaper, but not mine

    rollup = await item_rollups(sc.db, sc.user_id, item, mine, "30d")

    assert rollup["best_price"] == "100.00"
    assert rollup["active_listing_count"] == 1


# --- item_rollups: spark ------------------------------------------------------
#
# 30 buckets of best-price-over-the-range. Oracle: sparkline() in
# frontend/src/mocks/fixtures.ts.
#
# Do not confuse this with StatTile.spark. The contract calls both "spark", but
# the dashboard one is a fake 12-point ramp between two counts (_generate_spark)
# and this one is real bucketed price history. They share nothing but the name.
#
# Bucket arithmetic: a "30d" range over 30 buckets is one bucket per day, so a
# check `D` days ago lands in bucket `30 - D`. Tests use half-day offsets to keep
# timestamps mid-bucket — an exact integer offset sits on a boundary, and which
# side it falls on depends on the microseconds between `sc.now` and the clock
# read inside the service.

async def test_item_rollups_spark_has_thirty_buckets(sc):
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (4.5, "80.00"))

    spark = (await item_rollups(sc.db, sc.user_id, item, watch, "30d"))["spark"]

    assert len(spark) == 30


async def test_item_rollups_spark_runs_oldest_to_newest(sc):
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (25.5, "100.00"), (4.5, "80.00"))

    spark = (await item_rollups(sc.db, sc.user_id, item, watch, "30d"))["spark"]

    assert spark[4] == "100.00"
    assert spark[25] == "80.00"
    # every other bucket is empty — null, never 0
    assert [i for i, price in enumerate(spark) if price is not None] == [4, 25]


async def test_item_rollups_spark_keeps_the_cheapest_price_in_a_bucket(sc):
    # It is a BEST-price spark: two listings checked in the same bucket collapse
    # to the lower of the two, not an average and not the newer one.
    item, watch = await sc.tracked()
    cheap = await sc.listing(watch, item, "cheap")
    dear = await sc.listing(watch, item, "dear")
    await sc.checks(cheap, (4.5, "80.00"))
    await sc.checks(dear, (4.6, "120.00"))

    spark = (await item_rollups(sc.db, sc.user_id, item, watch, "30d"))["spark"]

    assert spark[25] == "80.00"


async def test_item_rollups_spark_is_empty_without_any_listing(sc):
    # [] rather than 30 nulls. The mock bails before allocating the array, and
    # the frontend draws nothing at all instead of a flat line at zero.
    item, watch = await sc.tracked()

    assert (await item_rollups(sc.db, sc.user_id, item, watch, "30d"))["spark"] == []


async def test_item_rollups_spark_is_empty_when_every_listing_is_inactive(sc):
    item, watch = await sc.tracked()
    dead = await sc.listing(watch, item, "dead", active=False)
    await sc.checks(dead, (4.5, "80.00"))

    assert (await item_rollups(sc.db, sc.user_id, item, watch, "30d"))["spark"] == []


async def test_item_rollups_spark_excludes_checks_before_the_range(sc):
    # Unlike pct_change_range, which deliberately reaches back before the window
    # for a baseline, the spark only charts what happened inside it.
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (40, "50.00"), (4.5, "80.00"))

    spark = (await item_rollups(sc.db, sc.user_id, item, watch, "30d"))["spark"]

    assert "50.00" not in spark
    assert spark[25] == "80.00"


async def test_item_rollups_spark_skips_unpriced_checks(sc):
    # The agent writes price=NULL for a sold listing. The listing is still
    # active, so we still emit 30 buckets — they are just all empty.
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (4.5, None))

    spark = (await item_rollups(sc.db, sc.user_id, item, watch, "30d"))["spark"]

    assert len(spark) == 30
    assert all(price is None for price in spark)


async def test_item_rollups_spark_for_all_spans_one_year(sc):
    # "all" means "no lower bound" everywhere else in this module, but a
    # fixed-width sparkline needs a left edge. dashboard_stats picks the same
    # 365-day fallback for the same reason.
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (400, "50.00"), (200, "80.00"))

    spark = (await item_rollups(sc.db, sc.user_id, item, watch, "all"))["spark"]

    assert "50.00" not in spark
    assert "80.00" in spark


async def test_item_rollups_spark_ignores_other_users_listings(sc):
    item = await sc.item()
    mine = await sc.watch(item)
    theirs = await sc.watch(item, user=await sc.other_user())
    my_listing = await sc.listing(mine, item, "mine")
    their_listing = await sc.listing(theirs, item, "theirs")
    await sc.checks(my_listing, (4.5, "100.00"))
    await sc.checks(their_listing, (4.5, "1.00"))    # cheaper, but not mine

    spark = (await item_rollups(sc.db, sc.user_id, item, mine, "30d"))["spark"]

    assert spark[25] == "100.00"
    assert "1.00" not in spark


async def test_item_rollups_spark_clamps_a_future_check_into_the_last_bucket(sc):
    # A clock-skewed check dated ahead of `now` computes bucket 30, one past the
    # end. The mock clamps with Math.min(buckets - 1, ...); without that this is
    # an IndexError (or a silent 31st bucket) on real data.
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (-1, "80.00"))

    spark = (await item_rollups(sc.db, sc.user_id, item, watch, "30d"))["spark"]

    assert len(spark) == 30
    assert spark[29] == "80.00"


# --- drop detection -----------------------------------------------------------
#
# A "drop" is consecutive checks on one active listing where the price fell by
# MORE than 3%. Strictly more — the mock uses `> 0.03`, so exactly 3% is not a
# drop. _count_listings_with_drop counts LISTINGS, not events.

async def _one_listing_with(sc, *checks):
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, *checks)
    return listing


async def test_drop_of_exactly_three_percent_is_not_counted(sc):
    await _one_listing_with(sc, (20, "100.00"), (10, "97.00"))   # exactly 3%
    assert await _count_listings_with_drop(sc.db, sc.user_id, sc.ago(30), sc.now) == 0


async def test_drop_just_over_three_percent_is_counted(sc):
    await _one_listing_with(sc, (20, "100.00"), (10, "96.99"))   # 3.01%
    assert await _count_listings_with_drop(sc.db, sc.user_id, sc.ago(30), sc.now) == 1


async def test_listing_that_drops_repeatedly_counts_once(sc):
    await _one_listing_with(sc, (20, "100.00"), (15, "90.00"), (10, "80.00"))
    assert await _count_listings_with_drop(sc.db, sc.user_id, sc.ago(30), sc.now) == 1


async def test_price_increase_is_not_a_drop(sc):
    await _one_listing_with(sc, (20, "100.00"), (10, "150.00"))
    assert await _count_listings_with_drop(sc.db, sc.user_id, sc.ago(30), sc.now) == 0


async def test_a_single_check_has_no_predecessor(sc):
    await _one_listing_with(sc, (10, "100.00"))
    assert await _count_listings_with_drop(sc.db, sc.user_id, sc.ago(30), sc.now) == 0


async def test_drop_counter_ignores_checks_outside_the_window(sc):
    # Unlike price_drops, this one requires BOTH checks of a pair to be inside
    # the window — the WHERE runs before LAG, so out-of-range rows never pair.
    await _one_listing_with(sc, (50, "100.00"), (40, "50.00"))
    assert await _count_listings_with_drop(sc.db, sc.user_id, sc.ago(30), sc.now) == 0


# --- dashboard_stats ----------------------------------------------------------
#
# Four tiles, and `delta` deliberately means different things per tile. The
# growth tiles compare against range start; price_drops uses a true previous
# equal-length window; snagged's delta is a known placeholder.

async def test_dashboard_for_an_empty_account_is_all_zeros(sc):
    stats = await dashboard_stats(sc.db, sc.user_id, "30d")

    for tile in (stats.tracked_items, stats.active_listings,
                 stats.price_drops, stats.snagged):
        assert tile.value == 0
        assert tile.delta == 0


async def test_dashboard_every_spark_has_twelve_points(sc):
    # The frontend renders a fixed-width sparkline; a short list would break it.
    item, watch = await sc.tracked()
    await sc.listing(watch, item)

    stats = await dashboard_stats(sc.db, sc.user_id, "30d")

    for tile in (stats.tracked_items, stats.active_listings,
                 stats.price_drops, stats.snagged):
        assert len(tile.spark) == 12


async def test_dashboard_tracked_items_delta_is_growth_in_range(sc):
    old_item = await sc.item("Old")
    await sc.watch(old_item, days_ago=200)          # existed before the window
    new_item = await sc.item("New")
    await sc.watch(new_item, days_ago=10)           # added inside it

    stats = await dashboard_stats(sc.db, sc.user_id, "30d")

    assert stats.tracked_items.value == 2
    assert stats.tracked_items.delta == 1


async def test_dashboard_active_listings_excludes_inactive(sc):
    item, watch = await sc.tracked()
    await sc.listing(watch, item, "live")
    await sc.listing(watch, item, "dead", active=False)

    stats = await dashboard_stats(sc.db, sc.user_id, "30d")

    assert stats.active_listings.value == 1


async def test_dashboard_snagged_counts_watches_at_or_under_target(sc):
    under_item, under = await sc.tracked("Under", target_price="100.00")
    over_item, over = await sc.tracked("Over", target_price="10.00")
    await sc.checks(await sc.listing(under, under_item, "u"), (5, "80.00"))
    await sc.checks(await sc.listing(over, over_item, "o"), (5, "80.00"))

    stats = await dashboard_stats(sc.db, sc.user_id, "30d")

    assert stats.snagged.value == 1


async def test_dashboard_snagged_ignores_watches_without_a_target(sc):
    item, watch = await sc.tracked(target_price=None)
    await sc.checks(await sc.listing(watch, item), (5, "1.00"))

    stats = await dashboard_stats(sc.db, sc.user_id, "30d")

    assert stats.snagged.value == 0


async def test_dashboard_drops_compare_against_the_previous_window(sc):
    # For range=30d the previous window is [T-60d, T-30d]. One drop in each
    # means value=1 and delta=0 — which is how we know the previous window is
    # actually being measured rather than ignored.
    item, watch = await sc.tracked()
    recent = await sc.listing(watch, item, "recent")
    older = await sc.listing(watch, item, "older")
    await sc.checks(recent, (20, "100.00"), (10, "50.00"))
    await sc.checks(older, (50, "100.00"), (40, "50.00"))

    stats = await dashboard_stats(sc.db, sc.user_id, "30d")

    assert stats.price_drops.value == 1
    assert stats.price_drops.delta == 0


async def test_dashboard_isolates_users(sc):
    stranger = await sc.other_user()
    item = await sc.item()
    their_watch = await sc.watch(item, user=stranger)   # uq_item_user: one per (user, item)
    await sc.listing(their_watch, item, "theirs")

    stats = await dashboard_stats(sc.db, sc.user_id, "30d")

    assert stats.tracked_items.value == 0
    assert stats.active_listings.value == 0


# --- price_drops --------------------------------------------------------------
#
# The dashboard's "biggest recent drops" table. Shares the 3% threshold with the
# counter above but differs on two rules, both mirroring the mock.

async def test_price_drops_reports_only_the_newest_drop_per_listing(sc):
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (25, "100.00"), (20, "90.00"), (15, "85.00"))

    drops = await price_drops(sc.db, sc.user_id, "30d", 10)

    assert len(drops) == 1
    assert (drops[0].old_price, drops[0].new_price) == ("90.00", "85.00")


async def test_price_drops_predecessor_may_predate_the_window(sc):
    """Only the NEW price must be in range — its predecessor can be older.

    This is what lets a listing last checked months ago report a real drop the
    day it is re-checked. The dashboard counter deliberately differs here.
    """
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (50, "200.00"), (10, "100.00"))

    drops = await price_drops(sc.db, sc.user_id, "30d", 10)

    assert len(drops) == 1
    assert drops[0].old_price == "200.00"


async def test_price_drops_are_newest_first_and_capped(sc):
    item, watch = await sc.tracked()
    recent = await sc.listing(watch, item, "recent")
    older = await sc.listing(watch, item, "older")
    await sc.checks(recent, (12, "100.00"), (5, "50.00"))
    await sc.checks(older, (25, "100.00"), (20, "50.00"))

    everything = await price_drops(sc.db, sc.user_id, "30d", 10)
    capped = await price_drops(sc.db, sc.user_id, "30d", 1)

    assert [d.listing_id for d in everything] == [recent.id, older.id]
    assert [d.listing_id for d in capped] == [recent.id]


@pytest.mark.parametrize("limit", [0, -5])
async def test_price_drops_limit_zero_or_negative_returns_nothing(sc, limit):
    # Postgres rejects a negative LIMIT outright, so the service clamps.
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (20, "100.00"), (10, "50.00"))

    assert await price_drops(sc.db, sc.user_id, "30d", limit) == []


async def test_price_drops_pct_change_is_negative_and_two_places(sc):
    # Always negative here, so no explicit sign — unlike pct_change_range, which
    # can go either way and therefore formats with an explicit +.
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (20, "200.00"), (10, "100.00"))

    drops = await price_drops(sc.db, sc.user_id, "30d", 10)

    assert drops[0].pct_change == "-50.00"


async def test_price_drops_all_range_has_no_lower_bound(sc):
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (100, "200.00"), (90, "100.00"))   # long ago

    assert await price_drops(sc.db, sc.user_id, "30d", 10) == []
    assert len(await price_drops(sc.db, sc.user_id, "all", 10)) == 1


async def test_price_drops_excludes_inactive_and_other_users(sc):
    item = await sc.item()
    mine = await sc.watch(item)
    theirs = await sc.watch(item, user=await sc.other_user())
    dead = await sc.listing(mine, item, "dead", active=False)
    stranger = await sc.listing(theirs, item, "stranger")
    await sc.checks(dead, (20, "100.00"), (10, "10.00"))
    await sc.checks(stranger, (20, "100.00"), (10, "10.00"))

    assert await price_drops(sc.db, sc.user_id, "30d", 10) == []


async def test_price_drops_carries_the_display_names(sc):
    item, watch = await sc.tracked("Nikon FM2")
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (20, "200.00"), (10, "100.00"))

    drop = (await price_drops(sc.db, sc.user_id, "30d", 10))[0]

    assert drop.item_id == item.id
    assert drop.item_name == "Nikon FM2"
    assert drop.site_name == "TestBay"
    assert drop.currency == "USD"


# --- category_price_change ----------------------------------------------------
#
# Per-item best-price movement across one category. Scoped to the CALLER's
# watched items — a deliberate divergence from the single-user mock.

async def test_category_change_compares_baseline_to_now(sc):
    item, watch = await sc.tracked("Alpha")
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (40, "100.00"), (5, "80.00"))

    rows = await category_price_change(sc.db, sc.user_id, (await sc.category()).id, "30d")

    assert len(rows) == 1
    assert rows[0].old_best == "100.00"
    assert rows[0].new_best == "80.00"
    assert rows[0].pct_change == "-20.00"


async def test_category_change_takes_the_cheapest_across_listings(sc):
    item, watch = await sc.tracked("Alpha")
    cheap = await sc.listing(watch, item, "cheap")
    dear = await sc.listing(watch, item, "dear")
    await sc.checks(cheap, (40, "100.00"), (5, "80.00"))
    await sc.checks(dear, (40, "120.00"), (5, "95.00"))

    row = (await category_price_change(sc.db, sc.user_id, (await sc.category()).id, "30d"))[0]

    assert row.old_best == "100.00"
    assert row.new_best == "80.00"


async def test_category_change_is_signed_for_rises(sc):
    item, watch = await sc.tracked("Alpha")
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (40, "50.00"), (5, "60.00"))

    row = (await category_price_change(sc.db, sc.user_id, (await sc.category()).id, "30d"))[0]

    assert row.pct_change == "+20.00"


async def test_category_change_unchanged_price_is_plus_zero(sc):
    item, watch = await sc.tracked("Alpha")
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (40, "50.00"), (5, "50.00"))

    row = (await category_price_change(sc.db, sc.user_id, (await sc.category()).id, "30d"))[0]

    assert row.pct_change == "+0.00"


async def test_category_change_null_without_a_baseline(sc):
    # Nothing recorded before range start, so there is no "old" to compare to.
    item, watch = await sc.tracked("Alpha")
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (5, "30.00"))

    row = (await category_price_change(sc.db, sc.user_id, (await sc.category()).id, "30d"))[0]

    assert row.old_best is None
    assert row.pct_change is None
    assert row.new_best == "30.00"      # the current price is still reported


async def test_category_change_all_range_has_no_baseline(sc):
    item, watch = await sc.tracked("Alpha")
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (40, "100.00"), (5, "80.00"))

    row = (await category_price_change(sc.db, sc.user_id, (await sc.category()).id, "all"))[0]

    assert row.pct_change is None
    assert row.new_best == "80.00"


async def test_category_change_inactive_listing_reports_nulls(sc):
    item, watch = await sc.tracked("Alpha")
    dead = await sc.listing(watch, item, "dead", active=False)
    await sc.checks(dead, (40, "100.00"), (5, "80.00"))

    row = (await category_price_change(sc.db, sc.user_id, (await sc.category()).id, "30d"))[0]

    assert row.old_best is None and row.new_best is None and row.pct_change is None


async def test_category_change_is_ordered_by_name(sc):
    cameras = await sc.category()
    for name in ("Zulu", "Alpha", "Mike"):
        it, w = await sc.tracked(name)
        await sc.checks(await sc.listing(w, it, name), (5, "10.00"))

    rows = await category_price_change(sc.db, sc.user_id, cameras.id, "30d")

    assert [r.name for r in rows] == ["Alpha", "Mike", "Zulu"]


async def test_category_change_only_lists_watched_items(sc):
    """Divergence from the mock, on purpose.

    The mock lists every item in the category because its store has one user.
    Here an item the caller doesn't watch — including one another user watches —
    must not appear, or catalogs leak between accounts.
    """
    cameras = await sc.category()
    mine, my_watch = await sc.tracked("Mine")
    await sc.checks(await sc.listing(my_watch, mine, "m"), (5, "10.00"))

    theirs = await sc.item("Theirs")
    their_watch = await sc.watch(theirs, user=await sc.other_user())
    await sc.checks(await sc.listing(their_watch, theirs, "t"), (5, "10.00"))

    unwatched = await sc.item("Unwatched")   # in the catalog, nobody watching

    rows = await category_price_change(sc.db, sc.user_id, cameras.id, "30d")

    assert [r.name for r in rows] == ["Mine"]
    assert unwatched.id not in {r.item_id for r in rows}


async def test_category_change_empty_for_a_category_with_no_watches(sc):
    lenses = await sc.category("Lenses")
    assert await category_price_change(sc.db, sc.user_id, lenses.id, "30d") == []


# --- cross-cutting contract rules ---------------------------------------------

async def test_every_price_field_is_a_decimal_string(sc):
    """Prices cross the wire as "80.00", never as 80.0.

    JSON numbers would reintroduce float rounding on money, which is exactly
    what Numeric(10,2) + str() exists to prevent.
    """
    item, watch = await sc.tracked(target_price="85.00")
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (40, "100.00"), (5, "80.00"))
    cat_id = (await sc.category()).id

    rollup = await item_rollups(sc.db, sc.user_id, item, watch, "30d")
    series = await price_history(sc.db, sc.user_id, item.id, "30d", 300)
    summary = await price_summary(sc.db, sc.user_id, item.id, "30d", 4)
    drops = await price_drops(sc.db, sc.user_id, "30d", 10)
    changes = await category_price_change(sc.db, sc.user_id, cat_id, "30d")

    priced = [rollup["best_price"], rollup["avg_price"]]
    priced += [p.price for p in series[0].points]
    priced += [p.avg for p in summary] + [p.best for p in summary]
    priced += [d.old_price for d in drops] + [d.new_price for d in drops]
    priced += [c.old_best for c in changes] + [c.new_best for c in changes]

    for value in priced:
        assert value is None or isinstance(value, str), f"{value!r} is not a string"
        assert not isinstance(value, (int, float, Decimal))


async def test_timestamps_are_iso_utc(sc):
    item, watch = await sc.tracked()
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (20, "200.00"), (5, "100.00"))

    rollup = await item_rollups(sc.db, sc.user_id, item, watch, "30d")
    series = await price_history(sc.db, sc.user_id, item.id, "30d", 300)
    drops = await price_drops(sc.db, sc.user_id, "30d", 10)

    stamps = [rollup["last_checked_at"], series[0].points[0].ts, drops[0].checked_at]
    for ts in stamps:
        assert ts.endswith("+00:00"), f"{ts} is not UTC ISO-8601"
