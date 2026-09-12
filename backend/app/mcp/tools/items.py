"""Item tools — the user's watches, their listings, and raw price checks."""

from fastmcp import FastMCP

from app.mcp.refs import Ref, resolve_category, resolve_site
from app.mcp.server import DESTRUCTIVE, READ_ONLY, WRITE, caller_session
from app.schemas.common import Paginated, TimeRange
from app.schemas.items import (
    ItemCreateRequest,
    ItemDetail,
    ItemListParams,
    ItemStatusFilter,
    ItemSummary,
    ItemUpdateRequest,
    Listing,
    ListingRow,
    PriceCheck,
    SelectionMode,
    WatchUpdateRequest,
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

    @mcp.tool(auth=WRITE)
    async def create_item(
        category: Ref,
        name: str,
        target_price: str | None = None,
        criteria: str | None = None,
        selection_mode: SelectionMode = "cheapest",
        max_listings: int = 5,
        allow_reproductions: bool = False,
        site_ids: list[Ref] | None = None,
    ) -> ItemSummary:
        """Start watching an item. If the shared catalog already has an item of
        that name in the category this joins it; otherwise the item is created.
        The agent picks it up on the next run.

        Args:
          category: id or slug
          name: the item as a buyer would search for it, e.g. "Pokemon Emerald"
          target_price: decimal string like "120.00" the user wants to pay at
            or below; null = just track prices, no target
          criteria: free text the agent judges every listing against, e.g.
            "authentic cartridge, working save battery, no reproductions"
          selection_mode: cheapest | best_match — how the tracked slots are filled
          max_listings: how many listings to track at once, 1–10
          allow_reproductions: true skips the counterfeit screening
          site_ids: subset of the category's sites to search (ids or names);
            omitted = all of them
        """
        async with caller_session() as (db, user):
            cat = await resolve_category(db, category)
            body = ItemCreateRequest(
                category_id=cat.id,
                name=name,
                target_price=target_price,
                criteria=criteria,
                selection_mode=selection_mode,
                max_listings=max_listings,
                allow_reproductions=allow_reproductions,
                site_ids=[(await resolve_site(db, ref)).id for ref in site_ids]
                if site_ids
                else None,
            )
            return await items_service.create_item(db, user.id, body)

    @mcp.tool(auth=WRITE)
    async def update_item(
        item: int,
        name: str | None = None,
        target_price: str | None = None,
        criteria: str | None = None,
        selection_mode: SelectionMode | None = None,
        max_listings: int | None = None,
        allow_reproductions: bool | None = None,
        notify: bool | None = None,
    ) -> ItemDetail:
        """Change a watched item's settings — the same fields as create_item —
        plus `notify`: whether hitting the target should push a notification.
        Only the arguments you pass change; the rest stay as they are."""
        async with caller_session() as (db, user):
            body = ItemUpdateRequest(
                name=name,
                target_price=target_price,
                criteria=criteria,
                selection_mode=selection_mode,
                max_listings=max_listings,
                allow_reproductions=allow_reproductions,
            )
            detail = await items_service.update_item(db, user.id, item, body)
            if notify is not None:
                await items_service.update_watch(
                    db, user.id, item, WatchUpdateRequest(notify=notify)
                )
                detail = await items_service.get_item_detail(db, user.id, item)
            return detail

    @mcp.tool(auth=WRITE, annotations=DESTRUCTIVE)
    async def delete_item(item: int) -> str:
        """Stop watching an item: removes this user's watch together with its
        listings and price history. Other users' watches on the same item are
        untouched. No undo — confirm with the user first."""
        async with caller_session() as (db, user):
            await items_service.delete_item(db, user.id, item)
            return f"Stopped watching item {item}"

    @mcp.tool(auth=WRITE)
    async def update_listing(listing_id: int, active: bool) -> Listing:
        """Stop tracking a listing (active=false: it is no longer re-checked
        and drops out of the best-price math) or resume it (active=true)."""
        async with caller_session() as (db, user):
            return await items_service.update_listing(db, user.id, listing_id, active)
