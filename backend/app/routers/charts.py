"""Charts and dashboard aggregates — /api/items/{id}/price-*,
/api/categories/{id}/price-change and /api/dashboard/*. Auth required.

All bucketing / delta / sparkline math lives in services/aggregates.py.
prefix is /api because the routes span three trees.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import current_user
from app.core.errors import err
from app.database import get_db
from app.models import Categories
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
from app.services.items import watch_or_404

router = APIRouter(prefix="/api", tags=["charts"])


@router.get("/items/{item_id}/price-history", response_model=PriceHistoryResponse)
async def get_price_history(
    item_id: int,
    range: TimeRange,
    points: int = 300,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """One price series per live listing of the caller's item; 404 when unwatched."""
    # Ownership check first — no point building a series for an item the caller
    # can't see.
    watch = await watch_or_404(db, user.id, item_id)

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
    """Average and best price over time, pooled across the caller's listings of
    an item; 404 when unwatched."""
    watch = await watch_or_404(db, user.id, item_id)

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
    """Best-price movement over the range for each of the caller's items in a category.

    404 for an unknown category; a category the caller watches nothing in is a
    valid empty list, not an error."""
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
    """The dashboard tiles for the caller over the range."""
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
    """The caller's recent price drops, one row per listing, newest first."""
    # One row per listing (its most recent drop), newest first — not one row per
    # drop event. services.aggregates.price_drops explains why.
    return DataList(data=await price_drops(db, user.id, range, limit))
