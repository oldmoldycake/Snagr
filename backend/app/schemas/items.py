"""Item / listing / watch / price-check schemas — mirror the "Items / listings /
watches" block of types.ts.

DOMAIN MAPPING (see STRUCTURE.md): an API "item" spans three tables —
items + the caller's watch + watch_sites. services/items.py assembles these
shapes; the rollup fields (best_*, avg_price, spark, pct_change_range,
active_listing_count, target_met, last_checked_at) come from services/aggregates.py.
"""

from typing import Literal

from pydantic import BaseModel

from app.schemas.common import TimeRange
from app.schemas.vision import AuthenticityRead

SelectionMode = Literal["cheapest", "best_match"]
ItemStatusFilter = Literal["all", "snagged", "above_target", "no_listings"]


class Watch(BaseModel):
    id: int
    notify: bool
    target_price: str | None  # null = inherit the item's target_price


class ItemSummary(BaseModel):
    id: int
    name: str
    category_id: int
    category_name: str
    category_slug: str
    target_price: str | None
    currency: str
    criteria: str | None
    selection_mode: SelectionMode
    max_listings: int
    allow_reproductions: bool
    site_ids: list[int] | None  # null = all of the category's sites
    best_price: str | None
    best_listing_id: int | None
    best_site_name: str | None
    avg_price: str | None
    active_listing_count: int
    target_met: bool
    pct_change_range: str | None  # signed percent, e.g. "-8.30"
    last_checked_at: str | None
    created_at: str
    watch: Watch
    spark: list[str | None]  # <=30 bucketed best-price points; null = no data in bucket


class Listing(BaseModel):
    id: int
    site_id: int
    site_name: str
    url: str
    title: str | None
    site_sku: str | None
    active: bool
    latest_price: str | None
    in_stock: bool | None
    latest_status: str | None  # 'ok' | 'sold' | 'ended' | 'error'
    match_score: int | None
    match_summary: str | None
    # image-based authenticity read; null = never scanned (vision off, repro
    # allowed, or discovered before the feature)
    authenticity: AuthenticityRead | None
    last_checked_at: str | None
    created_at: str
    discovered_by_run_id: int | None


class ItemDetail(ItemSummary):
    listings: list[Listing]


class ItemCreateRequest(BaseModel):
    category_id: int
    name: str
    target_price: str | None
    criteria: str | None = None
    selection_mode: SelectionMode = "cheapest"
    max_listings: int = 5  # contract default (note: DB column defaults to 3)
    allow_reproductions: bool = False
    site_ids: list[int] | None = None


class ItemUpdateRequest(BaseModel):
    name: str | None = None
    target_price: str | None = None
    criteria: str | None = None
    selection_mode: SelectionMode | None = None
    max_listings: int | None = None
    allow_reproductions: bool | None = None
    site_ids: list[int] | None = None


class WatchUpdateRequest(BaseModel):
    notify: bool | None = None
    target_price: str | None = None


class ListingUpdateRequest(BaseModel):
    active: bool


class ItemListParams(BaseModel):
    category_id: int | None = None
    site_id: int | None = None
    status: ItemStatusFilter | None = None
    search: str | None = None
    range: TimeRange | None = None
    sort: str | None = None
    page: int | None = None
    per_page: int | None = None


class PriceCheck(BaseModel):
    id: int
    listing_id: int
    site_name: str
    price: str | None
    currency: str
    in_stock: bool | None
    status: str | None  # 'ok' | 'sold' | 'ended' | 'error'
    checked_at: str
