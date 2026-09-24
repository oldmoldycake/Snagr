"""Chart / aggregate schemas — mirror the "Chart / aggregate endpoints" block of types.ts.

All the math (bucketing, deltas, sparklines) lives in services/aggregates.py.
Prices are decimal strings; the dashboard StatTiles are plain numbers.
"""

from pydantic import BaseModel

from app.schemas.common import TimeRange

# --- price history / summary ------------------------------------------------


class PricePoint(BaseModel):
    """One confirmed price reading on a listing's history line."""

    ts: str
    price: str
    in_stock: bool


class ListingSeries(BaseModel):
    """One listing's price line in PriceHistoryResponse."""

    listing_id: int
    site_name: str
    title: str | None
    active: bool
    points: list[PricePoint]


class PriceHistoryResponse(BaseModel):
    """GET /api/items/{id}/price-history — one series per listing over the range."""

    item_id: int
    target_price: str | None
    currency: str
    range: TimeRange
    series: list[ListingSeries]


class SummaryPoint(BaseModel):
    """One time bucket of PriceSummaryResponse; null prices mean no readings fell in it."""

    ts: str
    avg: str | None
    best: str | None


class PriceSummaryResponse(BaseModel):
    """GET /api/items/{id}/price-summary — average and best price per bucket, listings pooled."""

    item_id: int
    target_price: str | None
    currency: str
    range: TimeRange
    points: list[SummaryPoint]


# --- category price change --------------------------------------------------


class CategoryItemChange(BaseModel):
    """One item's best-price movement in CategoryPriceChangeResponse."""

    item_id: int
    name: str
    pct_change: str | None  # null when <2 prices in range
    old_best: str | None
    new_best: str | None


class CategoryPriceChangeResponse(BaseModel):
    """GET /api/categories/{id}/price-change — per-item best-price change over the range."""

    category_id: int
    range: TimeRange
    items: list[CategoryItemChange]


# --- dashboard --------------------------------------------------------------


class StatTile(BaseModel):
    """One dashboard counter: its value, the change, and a sparkline."""

    value: int
    delta: int  # what it compares against differs per tile — see dashboard_stats
    spark: list[int]


class DashboardStats(BaseModel):
    """GET /api/dashboard/stats — the four dashboard tiles."""

    tracked_items: StatTile
    active_listings: StatTile
    price_drops: StatTile
    snagged: StatTile


class PriceDrop(BaseModel):
    """One row of GET /api/dashboard/price-drops: a listing whose price fell between two checks."""

    item_id: int
    item_name: str
    listing_id: int
    site_name: str
    old_price: str
    new_price: str
    currency: str
    pct_change: str  # signed percent, negative for drops
    checked_at: str
