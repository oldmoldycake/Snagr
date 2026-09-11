"""Item tools — the user's watches, their listings, and raw price checks."""

from fastmcp import FastMCP

from app.mcp.refs import Ref, resolve_category, resolve_site
from app.mcp.server import READ_ONLY, caller_session
from app.schemas.common import Paginated, TimeRange
from app.schemas.items import (
    ItemDetail,
    ItemListParams,
    ItemStatusFilter,
    ItemSummary,
    ListingRow,
    PriceCheck,
)
from app.services import items as items_service


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def list_items(
        category: Ref | None = None,
        site: Ref | None = None,
        status: ItemStatusFilter = "all",
        search: str | None = None,
        range: TimeRange = "30d",
        page: int = 1,
        per_page: int = 25,
    ) -> Paginated[ItemSummary]:
        """The items this user watches, each with its target price, current best
        price and site, average price, active listing count, whether the target
        is met, and the percent change plus a sparkline over `range`.

        Args:
          category: filter by category id or slug
          site: only items with an active listing on this site (id or name)
          status: all | snagged (best price at/below target) | above_target
            (has listings, none at target) | no_listings
          search: case-insensitive substring of the item name
          range: window for pct_change_range and spark — 7d | 30d | 90d | 1y | all
          page, per_page: pagination; meta.total is the full filtered count
        """
        async with caller_session() as (db, user):
            filters = ItemListParams(
                category_id=(await resolve_category(db, category)).id if category else None,
                site_id=(await resolve_site(db, site)).id if site else None,
                status=status,
                search=search,
                range=range,
                page=page,
                per_page=per_page,
            )
            return await items_service.list_items(db, user.id, filters)

    @mcp.tool(annotations=READ_ONLY)
    async def get_item(item: int) -> ItemDetail:
        """One watched item in full: everything list_items shows plus every
        listing the agent tracks for it — URL, title, latest price, stock and
        status, the criteria match score with its one-line rationale, and the
        photo-authenticity read when vision is on. `item` is the item id."""
        async with caller_session() as (db, user):
            return await items_service.get_item_detail(db, user.id, item)

    @mcp.tool(annotations=READ_ONLY)
    async def list_listings(
        item: int | None = None,
        site: Ref | None = None,
        active: bool | None = True,
        page: int = 1,
        per_page: int = 25,
    ) -> Paginated[ListingRow]:
        """Listings across every item this user watches, newest first — the way
        to answer "what's the cheapest thing on eBay right now" without walking
        each item. Each row carries the listing plus its item_id and item_name.

        Args:
          item: only this item's listings (item id)
          site: only listings on this site (id or name)
          active: true (default) = tracked listings only; false = sold/ended
            only; null = everything
        """
        async with caller_session() as (db, user):
            return await items_service.list_listings(
                db,
                user.id,
                item_id=item,
                site_id=(await resolve_site(db, site)).id if site else None,
                active=active,
                page=page,
                per_page=per_page,
            )

    @mcp.tool(annotations=READ_ONLY)
    async def list_price_checks(item: int, limit: int = 50) -> list[PriceCheck]:
        """The raw observations behind an item's prices: each time the agent
        looked at one of its listings — price, currency, in stock, and the
        status (ok | sold | ended | error) — newest first. Unknown or unwatched
        items give an empty list."""
        async with caller_session() as (db, user):
            return await items_service.list_price_checks(db, user.id, item, limit)
