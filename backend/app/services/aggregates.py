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

async def price_history(db, user_id, item_id, range, points) -> list[ListingSeries]:
    pass

async def price_summary(db, user_id, item_id, range, points) -> list[SummaryPoint]:
    pass

async def item_rollups(db, user_id, item, range)-> dict:
    pass

async def dashboard_stats(db, user_id, range) -> DashboardStats:
    pass

async def price_Drops(db, user_id, range, limit) -> list[PriceDrop]:
    pass

async def category_price_change(db, user_id, item, range) -> list[CategoryItemChange]:
    pass



