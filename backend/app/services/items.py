"""The item <-> watch <-> watch_sites mapping — the one genuinely fiddly bit
of CRUD in the backend, so it gets its own module and keeps routers/items.py
thin.

An API "item" is three tables: the shared items row, the caller's watches row
(target, criteria, selection mode, slots…) and their watch_sites subset, so
everything here is scoped to one user's watches. The REST router and the MCP
tools are the two callers and must agree — which is why the serializers live
here rather than in either of them.

Reads live here: build_item_summary, load_listings / listing_out,
watch_or_404, list_items, get_item_detail, list_listings, list_price_checks.
The writes (create/update/delete, the watch toggle, the listing toggle) still
sit in routers/items.py and move here with the MCP write tools.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import err
from app.models import Categories, Items, Listings, PriceChecks, Sites, Watches, WatchSites
from app.schemas.common import PageMeta, Paginated
from app.schemas.items import (
    ItemDetail,
    ItemListParams,
    ItemSummary,
    Listing,
    ListingRow,
    PriceCheck,
    Watch,
)
from app.schemas.vision import AuthenticityRead
from app.services.aggregates import item_rollups
from app.services.vision import authenticity_for_listings

# --- serializers --------------------------------------------------------------


async def build_item_summary(
    watch: Watches, item: Items, category: Categories, db: AsyncSession, range: str = "30d"
) -> ItemSummary:
    """One (watch, item, category) row -> ItemSummary. Stored/joined fields
    come from the rows; the price rollups (best/avg/target/pct/spark) from
    services.aggregates.item_rollups over `range`."""
    # site_ids = the watch's chosen subset; no rows means "all category sites" (null)
    site_ids = (
        (await db.execute(select(WatchSites.site_id).where(WatchSites.watch_id == watch.id)))
        .scalars()
        .all()
    )

    # prices are decimal STRINGS, never floats/0; null for unknown
    target_price = str(watch.target_price) if watch.target_price is not None else None

    return ItemSummary(
        id=item.id,
        name=item.name,
        category_id=category.id,
        category_name=category.name,
        category_slug=category.slug,
        target_price=target_price,
        currency="USD",
        criteria=watch.criteria,
        selection_mode=watch.selection_mode,
        max_listings=watch.max_listings,
        allow_reproductions=watch.allow_reproductions,
        site_ids=list(site_ids) or None,
        **await item_rollups(db, watch.user_id, item, watch, range),
        created_at=item.created_at.isoformat(),
        watch=Watch(id=watch.id, notify=watch.notify, target_price=target_price),
    )


async def listing_latest_check(
    listing_id: int, db: AsyncSession
) -> tuple[str | None, bool | None, str | None, str | None]:
    """Latest price/status observations for one listing.

    Two different "latest" rows, matching the contract (see mocks/serializers.ts):
      - price/in_stock come from the newest check THAT HAS A PRICE
      - status/checked_at come from the newest check of ANY kind, so a sold/ended
        listing still reports its terminal status and when we saw it.

    Returns (price, in_stock, status, checked_at) — all None-safe, price as a
    decimal string and checked_at as ISO-8601.

    NOTE: 2 queries per listing (N+1). Folds into services/aggregates.py in Pass 2.
    """
    priced_stmt = (
        select(PriceChecks.price, PriceChecks.in_stock)
        .where(PriceChecks.price.isnot(None))
        .where(PriceChecks.listing_id == listing_id)
        .order_by(PriceChecks.checked_at.desc())
        .limit(1)
    )
    with_price_check = (await db.execute(priced_stmt)).first()

    latest_stmt = (
        select(PriceChecks.status, PriceChecks.checked_at)
        .where(PriceChecks.listing_id == listing_id)
        .order_by(PriceChecks.checked_at.desc())
        .limit(1)
    )
    general_latest = (await db.execute(latest_stmt)).first()

    price = str(with_price_check.price) if with_price_check is not None else None
    in_stock = with_price_check.in_stock if with_price_check is not None else None
    status = general_latest.status if general_latest is not None else None
    checked_at = general_latest.checked_at.isoformat() if general_latest is not None else None
    return price, in_stock, status, checked_at


async def listing_out(
    db: AsyncSession,
    listing: Listings,
    site_name: str,
    authenticity: dict[str, AuthenticityRead],
) -> Listing:
    """One listings row -> the contract's Listing shape. `authenticity` is the
    owning watch's batch from services.vision.authenticity_for_listings,
    keyed by listing URL (absent = never scanned)."""
    price, in_stock, latest_status, checked_at = await listing_latest_check(listing.id, db)
    return Listing(
        id=listing.id,
        site_id=listing.site_id,
        site_name=site_name,
        url=listing.url,
        title=listing.title,
        site_sku=listing.site_sku,
        active=listing.active,
        latest_price=price,
        in_stock=in_stock,
        latest_status=latest_status,
        match_score=listing.match_score,
        match_summary=listing.match_summary,
        authenticity=authenticity.get(listing.url),
        last_checked_at=checked_at,
        created_at=listing.created_at.isoformat(),
        discovered_by_run_id=None,
    )


async def load_listings(db: AsyncSession, watch: Watches) -> list[Listing]:
    """Every listing of one watch, oldest first — the ItemDetail.listings block."""
    listing_stmt = (
        select(Listings, Sites.name)
        .join(Sites, Sites.id == Listings.site_id)
        .where(Listings.watch_id == watch.id)
        .order_by(Listings.created_at)
    )
    listing_rows = (await db.execute(listing_stmt)).all()
    authenticity = await authenticity_for_listings(
        db, watch.id, [listing.url for listing, _ in listing_rows]
    )
    return [
        await listing_out(db, listing, site_name, authenticity)
        for listing, site_name in listing_rows
    ]


# --- reads --------------------------------------------------------------------


async def watch_or_404(db: AsyncSession, user_id: int, item_id: int) -> Watches:
    """The caller's watch for an item, or 404.

    An API "item" only exists for a user through their watch, so "no watch" and
    "no such item" are the same 404 to the caller — hence the item-shaped
    message. The chart endpoints need the watch anyway, for target_price.
    """
    stmt = select(Watches).where(Watches.user_id == user_id).where(Watches.item_id == item_id)
    watch = (await db.execute(stmt)).scalar_one_or_none()
    if watch is None:
        raise err(404, "not_found", f"Item {item_id} does not exist")
    return watch


async def list_items(
    db: AsyncSession, user_id: int, filters: ItemListParams
) -> Paginated[ItemSummary]:
    """The caller's watches as ItemSummary rows, filtered, searched and paged."""
    page = filters.page or 1
    per_page = filters.per_page or 50

    # the caller's watches, joined to the shared item + its category
    stmt = (
        select(Watches, Items, Categories)
        .join(Items, Items.id == Watches.item_id)
        .join(Categories, Categories.id == Items.category_id)
        .where(Watches.user_id == user_id)
    )
    if filters.category_id is not None:
        stmt = stmt.where(Items.category_id == filters.category_id)
    if filters.search:
        stmt = stmt.where(Items.name.ilike(f"%{filters.search}%"))
    if filters.site_id is not None:
        # only items with an active tracked listing on this site
        stmt = stmt.where(
            select(Listings.id)
            .where(Listings.watch_id == Watches.id)
            .where(Listings.site_id == filters.site_id)
            .where(Listings.active.is_(True))
            .exists()
        )

    rows = (await db.execute(stmt.order_by(Items.name))).all()
    summaries = [
        await build_item_summary(w, i, c, db, filters.range or "30d") for (w, i, c) in rows
    ]

    # status filter runs AFTER serialize — it reads the computed fields
    if filters.status == "snagged":
        summaries = [s for s in summaries if s.target_met]
    elif filters.status == "above_target":
        summaries = [s for s in summaries if not s.target_met and s.active_listing_count > 0]
    elif filters.status == "no_listings":
        summaries = [s for s in summaries if s.active_listing_count == 0]

    total = len(summaries)
    start = (page - 1) * per_page
    summaries = summaries[start : start + per_page]

    return Paginated(
        data=summaries,
        meta=PageMeta(page=page, per_page=per_page, total=total),
    )


async def get_item_detail(db: AsyncSession, user_id: int, item_id: int) -> ItemDetail:
    """ItemSummary plus every listing of the caller's watch; 404 when unwatched."""
    stmt = (
        select(Watches, Items, Categories)
        .join(Items, Items.id == Watches.item_id)
        .join(Categories, Categories.id == Items.category_id)
        .where(Watches.item_id == item_id, Watches.user_id == user_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise err(404, "not_found", f"Item {item_id} does not exist")

    watch, item, category = row
    summary = await build_item_summary(watch, item, category, db)
    return ItemDetail(**summary.model_dump(), listings=await load_listings(db, watch))


async def list_listings(
    db: AsyncSession,
    user_id: int,
    item_id: int | None = None,
    site_id: int | None = None,
    active: bool | None = True,
    page: int = 1,
    per_page: int = 25,
) -> Paginated[ListingRow]:
    """Every listing across the caller's watches, newest first — the one read
    REST has no route for (the UI only shows listings inside an item).
    `active=None` includes sold/ended listings."""
    stmt = (
        select(Listings, Sites.name.label("site_name"), Items.name.label("item_name"))
        .join(Sites, Sites.id == Listings.site_id)
        .join(Items, Items.id == Listings.item_id)
        .join(Watches, Watches.id == Listings.watch_id)
        .where(Watches.user_id == user_id)
    )
    if item_id is not None:
        stmt = stmt.where(Listings.item_id == item_id)
    if site_id is not None:
        stmt = stmt.where(Listings.site_id == site_id)
    if active is not None:
        stmt = stmt.where(Listings.active.is_(active))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(Listings.created_at.desc(), Listings.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).all()

    # authenticity scans are keyed per watch, so batch the lookups per watch
    urls_by_watch: dict[int, list[str]] = {}
    for listing, _, _ in rows:
        urls_by_watch.setdefault(listing.watch_id, []).append(listing.url)
    authenticity = {
        watch_id: await authenticity_for_listings(db, watch_id, urls)
        for watch_id, urls in urls_by_watch.items()
    }

    data = []
    for listing, site_name, item_name in rows:
        base = await listing_out(db, listing, site_name, authenticity[listing.watch_id])
        data.append(ListingRow(**base.model_dump(), item_id=listing.item_id, item_name=item_name))
    return Paginated(data=data, meta=PageMeta(page=page, per_page=per_page, total=total))


async def list_price_checks(
    db: AsyncSession, user_id: int, item_id: int, limit: int
) -> list[PriceCheck]:
    """Recent raw price checks across the caller's listings of one item,
    newest first. An unwatched item is simply an empty list."""
    # join through Watches so a caller only ever sees their OWN listings' checks
    stmt = (
        select(
            PriceChecks.id.label("price_check_id"),
            Listings.id.label("listing_id"),
            Sites.name.label("site_name"),
            PriceChecks.price.label("price"),
            PriceChecks.currency.label("currency"),
            PriceChecks.in_stock.label("in_stock"),
            PriceChecks.status.label("status"),
            PriceChecks.checked_at.label("checked_at"),
        )
        .join(Listings, Listings.id == PriceChecks.listing_id)
        .join(Sites, Sites.id == Listings.site_id)
        .join(Watches, Watches.id == Listings.watch_id)
        .where(Listings.item_id == item_id)
        .where(Watches.user_id == user_id)
        .order_by(PriceChecks.checked_at.desc())
        .limit(limit)
    )

    # .all(), NOT .scalars().all() — this is a multi-column select
    return [
        PriceCheck(
            id=row.price_check_id,
            listing_id=row.listing_id,
            site_name=row.site_name,
            price=str(row.price) if row.price is not None else None,
            currency=row.currency,
            in_stock=row.in_stock,
            status=row.status,
            checked_at=row.checked_at.isoformat(),
        )
        for row in (await db.execute(stmt)).all()
    ]
