"""Shared response envelopes + shared literals — mirror the "Shared" block of types.ts.

Conventions enforced project-wide:
  - prices are decimal STRINGS ("549.99"), never floats  -> typed `str | None`
  - timestamps are ISO-8601 UTC strings                  -> `str`
"""

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T")

# frontend/src/lib/time.ts
TimeRange = Literal["7d", "30d", "90d", "1y", "all"]


class PageMeta(BaseModel):
    page: int
    per_page: int
    total: int


class Paginated(BaseModel, Generic[T]):
    data: list[T]
    meta: PageMeta


class DataList(BaseModel, Generic[T]):
    """Non-paginated list envelope: {"data": [...]} (e.g. /api/categories)."""
    data: list[T]
