"""Price-intelligence tools — the same series and tiles the dashboard shows."""

from fastmcp import FastMCP

from app.mcp.refs import Ref, resolve_category
from app.mcp.server import READ_ONLY, caller_session
from app.schemas.charts import (
    CategoryPriceChangeResponse,
    DashboardStats,
    PriceDrop,
    PriceHistoryResponse,
    PriceSummaryResponse,
)
from app.schemas.common import TimeRange
from app.services.aggregates import (
    category_price_change,
    dashboard_stats,
    price_drops,
    price_history,
    price_summary,
)
from app.services.items import watch_or_404


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def get_price_history(
        item: int, range: TimeRange = "30d", points: int = 300
    ) -> PriceHistoryResponse:
        """One price series per listing of a watched item over `range`, plus
        the target price — what the item's price chart draws. `points` caps
        the samples per series (max 500)."""
        async with caller_session() as (db, user):
            watch = await watch_or_404(db, user.id, item)
            return PriceHistoryResponse(
                item_id=item,
                target_price=str(watch.target_price) if watch.target_price is not None else None,
                currency="USD",
                range=range,
                series=await price_history(db, user.id, item, range, points),
            )

    @mcp.tool(annotations=READ_ONLY)
    async def get_price_summary(
        item: int, range: TimeRange = "30d", points: int = 300
    ) -> PriceSummaryResponse:
        """The average and best price of a watched item over time, bucketed
        across `range` — the shape to answer "is this trending down?"."""
        async with caller_session() as (db, user):
            watch = await watch_or_404(db, user.id, item)
            return PriceSummaryResponse(
                item_id=item,
                target_price=str(watch.target_price) if watch.target_price is not None else None,
                currency="USD",
                range=range,
                points=await price_summary(db, user.id, item, range, points),
            )

    @mcp.tool(annotations=READ_ONLY)
    async def get_dashboard_stats(range: TimeRange = "30d") -> DashboardStats:
        """The dashboard tiles for this user over `range`: tracked items, active
        listings, items at target, and price drops — each with its delta
        against the range start (drops compare with the previous window)."""
        async with caller_session() as (db, user):
            return await dashboard_stats(db, user.id, range)

    @mcp.tool(annotations=READ_ONLY)
    async def get_price_drops(range: TimeRange = "30d", limit: int = 10) -> list[PriceDrop]:
        """The biggest recent price drops across everything this user watches —
        one row per listing (its most recent drop), newest first, with the
        before/after prices and the item and site names. The quickest answer
        to "anything worth looking at this week?"."""
        async with caller_session() as (db, user):
            return await price_drops(db, user.id, range, limit)

    @mcp.tool(annotations=READ_ONLY)
    async def get_category_price_change(
        category: Ref, range: TimeRange = "30d"
    ) -> CategoryPriceChangeResponse:
        """Per-item best-price percent change over `range` for every item this
        user watches in a category (id or slug). A category you watch nothing
        in is an empty list, not an error."""
        async with caller_session() as (db, user):
            resolved = await resolve_category(db, category)
            return CategoryPriceChangeResponse(
                category_id=resolved.id,
                range=range,
                items=await category_price_change(db, user.id, resolved.id, range),
            )
