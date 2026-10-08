"""Shared response envelopes + shared literals — mirror the "Shared" block of types.ts.

Conventions enforced project-wide:
  - prices are decimal STRINGS ("549.99"), never floats  -> typed `str | None`
  - timestamps are ISO-8601 UTC strings                  -> `str`
"""

from typing import Literal

from pydantic import BaseModel

# frontend/src/lib/time.ts
TimeRange = Literal["7d", "30d", "90d", "1y", "all"]


def page_param(value: int | None, default: int) -> int:
    """A page, per_page or limit as the mock's intParam reads one: `default`
    when missing or below 1. Postgres refuses a negative OFFSET or LIMIT
    rather than answering with an empty page."""
    return value if value is not None and value >= 1 else default


class PageMeta(BaseModel):
    """Pagination facts for a Paginated response: the page served and the total row count."""

    page: int
    per_page: int
    total: int


class Paginated[T](BaseModel):
    """Paginated list envelope: {"data": [...], "meta": PageMeta}."""

    data: list[T]
    meta: PageMeta


class DataList[T](BaseModel):
    """Non-paginated list envelope: {"data": [...]} (e.g. /api/categories)."""

    data: list[T]
