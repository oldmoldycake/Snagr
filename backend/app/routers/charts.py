"""Charts & dashboard aggregates — (Phase 1). Auth required.

All bucketing / delta / sparkline math lives in services/aggregates.py.
prefix is /api because routes span /api/items, /api/categories, /api/dashboard.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import current_user
from app.core.errors import err
from app.database import get_db
from app.models import Categories, Watches
from app.schemas.charts import (
    CategoryPriceChangeResponse,
    DashboardStats,
    PriceDrop,
    PriceHistoryResponse,
    PriceSummaryResponse,
)
from app.schemas.common import DataList, TimeRange
from app.services.aggregates import (
    category_price_change,
    dashboard_stats,
    price_drops,
    price_history,
    price_summary,
)

router = APIRouter(prefix="/api", tags=["charts"])


async def _watch_or_404(db: AsyncSession, user_id: int, item_id: int) -> Watches:
    """The caller's watch for an item, or 404.

    An API "item" only exists for a user through their watch, so "no watch" and
    "no such item" are the same 404 to the caller — hence the item-shaped
    message. Both chart endpoints need the watch anyway, for target_price.
    """
    stmt = select(Watches).where(Watches.user_id == user_id).where(Watches.item_id == item_id)
    watch = (await db.execute(stmt)).scalar_one_or_none()
    if watch is None:
        raise err(404, "not_found", f"Item {item_id} does not exist")
    return watch


@router.get("/items/{item_id}/price-history", response_model=PriceHistoryResponse)
async def get_price_history(
    item_id: int,
    range: TimeRange,
    points: int = 300,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    # Ownership check first — no point building a series for an item the caller
    # can't see.
    watch = await _watch_or_404(db, user.id, item_id)

    return PriceHistoryResponse(
        item_id=item_id,
        target_price=str(watch.target_price) if watch.target_price is not None else None,
        currency="USD",
        range=range,
        series=await price_history(db, user.id, item_id, range, points),
    )


@router.get("/items/{item_id}/price-summary", response_model=PriceSummaryResponse)
async def get_price_summary(
    item_id: int,
    range: TimeRange,
    points: int = 300,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    watch = await _watch_or_404(db, user.id, item_id)

    return PriceSummaryResponse(
        item_id=item_id,
        target_price=str(watch.target_price) if watch.target_price is not None else None,
        currency="USD",
        range=range,
        points=await price_summary(db, user.id, item_id, range, points),
    )


@router.get("/categories/{category_id}/price-change", response_model=CategoryPriceChangeResponse)
async def get_category_price_change(
    category_id: int,
    range: TimeRange,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    # 404 on an unknown category; a category the caller simply watches nothing
    # in is a valid empty list, not an error.
    if await db.get(Categories, category_id) is None:
        raise err(404, "not_found", f"Category {category_id} does not exist")

    return CategoryPriceChangeResponse(
        category_id=category_id,
        range=range,
        items=await category_price_change(db, user.id, category_id, range),
    )


@router.get("/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    range: TimeRange, user=Depends(current_user), db: AsyncSession = Depends(get_db)
):
    # Each tile's `delta` means something slightly different — the growth tiles
    # compare against range start, price_drops against the previous equal-length
    # window. services.aggregates.dashboard_stats documents which is which.
    return await dashboard_stats(db, user.id, range)


@router.get("/dashboard/price-drops", response_model=DataList[PriceDrop])
async def get_price_drops(
    range: TimeRange,
    limit: int = 10,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    # One row per listing (its most recent drop), newest first — not one row per
    # drop event. services.aggregates.price_drops explains why.
    return DataList(data=await price_drops(db, user.id, range, limit))
