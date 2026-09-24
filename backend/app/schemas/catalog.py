"""Category + Site schemas — mirror the "Categories" and "Sites" blocks of types.ts.

item_count / snagged_count / listing_count / last_checked_at / site_ids /
category_ids are COMPUTED at query time (services/catalog.py), not columns.
"""

from pydantic import BaseModel

# --- categories -------------------------------------------------------------


class Category(BaseModel):
    """A category with its linked sites and item counts — the /api/categories routes."""

    id: int
    name: str
    slug: str
    site_ids: list[int]
    item_count: int
    snagged_count: int


class CategoryCreateRequest(BaseModel):
    """POST /api/categories body."""

    name: str


class CategoryUpdateRequest(BaseModel):
    """PATCH /api/categories/{id} body."""

    name: str | None = None


class SetCategorySitesRequest(BaseModel):
    """PUT /api/categories/{id}/sites body."""

    site_ids: list[int]


# --- sites ------------------------------------------------------------------


class Site(BaseModel):
    """A retail site the hunter searches — the /api/sites routes."""

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
    """POST /api/sites body."""

    name: str
    base_url: str


class SiteUpdateRequest(BaseModel):
    """PATCH /api/sites/{id} body; omitted fields are left unchanged."""

    name: str | None = None
    base_url: str | None = None
    # null is the ONLY accepted value: the hunter sets pauses, a person can
    # only lift one. Typed loosely so any other value is a 422 in the envelope
    # rather than FastAPI's default detail shape.
    paused_until: str | None = None
