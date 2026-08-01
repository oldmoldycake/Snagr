"""Chart / aggregate schemas — mirror the "Chart / aggregate endpoints" block of types.ts.

All the math (bucketing, deltas, sparklines) lives in services/aggregates.py.
Prices are decimal strings; the dashboard StatTiles are plain numbers.
"""

from pydantic import BaseModel

from app.schemas.common import TimeRange

# --- price history / summary ------------------------------------------------


class PricePoint(BaseModel):
    ts: str
    price: str
    in_stock: bool


class ListingSeries(BaseModel):
    listing_id: int
    site_name: str
    title: str | None
    active: bool
    points: list[PricePoint]


class PriceHistoryResponse(BaseModel):
    item_id: int
    target_price: str | None
    currency: str
    range: TimeRange
    series: list[ListingSeries]


class SummaryPoint(BaseModel):
    ts: str
    avg: str | None
    best: str | None


class PriceSummaryResponse(BaseModel):
    item_id: int
    target_price: str | None
    currency: str
    range: TimeRange
    points: list[SummaryPoint]


# --- category price change --------------------------------------------------


class CategoryItemChange(BaseModel):
    item_id: int
    name: str
    pct_change: str | None  # null when <2 prices in range
    old_best: str | None
    new_best: str | None


class CategoryPriceChangeResponse(BaseModel):
    category_id: int
    range: TimeRange
    items: list[CategoryItemChange]


# --- dashboard --------------------------------------------------------------


class StatTile(BaseModel):
    value: int
    delta: int  # vs the previous equal-length period
    spark: list[int]


class DashboardStats(BaseModel):
    tracked_items: StatTile
    active_listings: StatTile
    price_drops: StatTile
    snagged: StatTile


class PriceDrop(BaseModel):
    item_id: int
    item_name: str
    listing_id: int
    site_name: str
    old_price: str
    new_price: str
    currency: str
    pct_change: str  # signed percent, negative for drops
    checked_at: str
