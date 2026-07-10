"""Charts & dashboard aggregates — (Phase 1). Auth required.

All bucketing / delta / sparkline math lives in services/aggregates.py.
prefix is /api because routes span /api/items, /api/categories, /api/dashboard.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import current_user
from app.database import get_db
from app.schemas.charts import (
    CategoryPriceChangeResponse,
    DashboardStats,
    PriceDrop,
    PriceHistoryResponse,
    PriceSummaryResponse,
)
from app.schemas.common import DataList, TimeRange

router = APIRouter(prefix="/api", tags=["charts"])


@router.get("/items/{item_id}/price-history", response_model=PriceHistoryResponse)
async def get_price_history(item_id: int, range: TimeRange, points: int = 300,
                            user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    raise NotImplementedError


@router.get("/items/{item_id}/price-summary", response_model=PriceSummaryResponse)
async def get_price_summary(item_id: int, range: TimeRange, points: int = 300,
                            user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    raise NotImplementedError


@router.get("/categories/{category_id}/price-change", response_model=CategoryPriceChangeResponse)
async def get_category_price_change(category_id: int, range: TimeRange,
                                    user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    raise NotImplementedError


@router.get("/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats(range: TimeRange, user=Depends(current_user),
                              db: AsyncSession = Depends(get_db)):
    # each StatTile's delta is vs the previous equal-length period
    raise NotImplementedError


@router.get("/dashboard/price-drops", response_model=DataList[PriceDrop])
async def get_price_drops(range: TimeRange, limit: int = 10, user=Depends(current_user),
                          db: AsyncSession = Depends(get_db)):
    raise NotImplementedError
