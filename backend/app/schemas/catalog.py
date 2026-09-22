"""Category + Site schemas — mirror the "Categories" and "Sites" blocks of types.ts.

item_count / snagged_count / listing_count / last_checked_at / site_ids /
category_ids are COMPUTED at query time (services/catalog.py), not columns.
"""

from pydantic import BaseModel

# --- categories -------------------------------------------------------------


class Category(BaseModel):
    id: int
    name: str
    slug: str
    site_ids: list[int]
    item_count: int
    snagged_count: int


class CategoryCreateRequest(BaseModel):
    name: str


class CategoryUpdateRequest(BaseModel):
    name: str | None = None


class SetCategorySitesRequest(BaseModel):
    """PUT /api/categories/{id}/sites body."""

    site_ids: list[int]


# --- sites ------------------------------------------------------------------


class Site(BaseModel):
    id: int
    name: str
    base_url: str
    category_ids: list[int]
    listing_count: int
    last_checked_at: str | None
    # set by the hunter's circuit breaker; null = the site is not paused
    paused_until: str | None
    paused_reason: str | None
    created_at: str


class SiteCreateRequest(BaseModel):
    name: str
    base_url: str


class SiteUpdateRequest(BaseModel):
    name: str | None = None
    base_url: str | None = None
    # null is the ONLY accepted value: the hunter sets pauses, a person can
    # only lift one. Typed loosely so any other value is a 422 in the envelope
    # rather than FastAPI's default detail shape.
    paused_until: str | None = None
