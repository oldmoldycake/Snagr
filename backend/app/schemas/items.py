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
    # minutes between rechecks of this watch's listings; null = the instance
    # default (InstanceInfo.recheck_interval_default)
    recheck_interval_minutes: int | None
    # false = hunted only when someone presses Hunt now; rechecks carry on
    hunt: bool
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
    # the hunt job that saved this listing; null for rows older than jobs
    discovered_by_job_id: int | None


class HuntFacts(BaseModel):
    """What the hunter will do next for one item — computed from its jobs,
    never stored (except `enabled`, the watch's own switch)."""

    enabled: bool  # the watch's `hunt` switch
    running: bool
    next_at: str | None
    last_at: str | None
    last_result: Literal["found", "nothing", "failed", "cancelled"] | None
    slots_open: int
    # the wait the next hunt is on after coming back empty; null = not backing off
    backoff_minutes: int | None


class RecheckFacts(BaseModel):
    running: int  # how many of this item's checks are running right now
    next_at: str | None
    # minutes between checks for this item's listings: the watch's own
    # interval, else the instance default, never below the floor — the value
    # the agent schedules with (services/jobs.py::effective_interval)
    interval_minutes: int


class ItemDetail(ItemSummary):
    """The facts line's two objects are here and not on ItemSummary — list
    queries stay cheap. `hunt` here is the facts object and replaces the
    summary's boolean, which it carries as `hunt.enabled`."""

    listings: list[Listing]
    hunt: HuntFacts
    recheck: RecheckFacts


class ListingRow(Listing):
    """A listing outside its item — the MCP `list_listings` tool's row. Not in
    types.ts: REST has no cross-item listing route (the UI only ever shows
    listings inside an item), so this is the one shape the contract doesn't
    mirror. It lives here because services/items.py builds it."""

    item_id: int
    item_name: str


class ItemCreateRequest(BaseModel):
    category_id: int
    name: str
    target_price: str | None
    criteria: str | None = None
    selection_mode: SelectionMode = "cheapest"
    max_listings: int = 5  # contract default (note: DB column defaults to 3)
    allow_reproductions: bool = False
    recheck_interval_minutes: int | None = None  # null = the instance default
    hunt: bool = True
    site_ids: list[int] | None = None


class ItemUpdateRequest(BaseModel):
    name: str | None = None
    target_price: str | None = None
    criteria: str | None = None
    selection_mode: SelectionMode | None = None
    max_listings: int | None = None
    allow_reproductions: bool | None = None
    # the one field here where an explicit null means something: back to the
    # instance default. Omitted = unchanged (model_fields_set tells them apart)
    recheck_interval_minutes: int | None = None
    hunt: bool | None = None
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
    # how the price was read: 'llm' (the model looked at the page) or one of
    # 'jsonld' | 'meta' | 'microdata' | 'locator' (code replayed the listing's
    # stored locator). null on rows written before the column existed.
    method: str | None
    # false for a reading the agent's plausibility bands rejected — shown in
    # the checks log, but excluded from every aggregate until a later read
    # agrees with it (services/aggregates.py)
    confirmed: bool
    checked_at: str
