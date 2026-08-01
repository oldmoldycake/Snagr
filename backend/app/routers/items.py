"""Items, listings & watches — (GET Phase 1, writes Phase 3). Auth required.

An API "item" = items row + the caller's watch + watch_sites (services/items.py).
prefix is /api because this router owns both /api/items/* and /api/listings/*.
"""

from typing import Annotated
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import Select, select, delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import csrf_guard, current_user
from app.core.errors import err
from app.database import get_db
from app.models import ListingChecks, PriceChecks, Watches, Items, WatchSites, Listings, Sites, Categories
from app.services.aggregates import item_rollups
from app.schemas.common import DataList, Paginated, PageMeta
from app.schemas.items import (
    ItemCreateRequest,
    ItemDetail,
    ItemListParams,
    ItemSummary,
    ItemUpdateRequest,
    Listing,
    ListingUpdateRequest,
    PriceCheck,
    Watch,
    WatchUpdateRequest,
)

router = APIRouter(prefix="/api", tags=["items"])


async def build_item_summary(watch: Watches, item: Items, category: Categories,
                             db: AsyncSession, range: str = "30d") -> ItemSummary:
    """One (watch, item, category) row -> ItemSummary.

    Stored/joined fields are real; the price rollups are PLACEHOLDERS until
    services/aggregates.py::item_rollups() exists — swap the block below for a
    call into it (Pass 2).
    """
    # site_ids = the watch's chosen subset; no rows means "all category sites" (null)
    site_ids = (await db.execute(
        select(WatchSites.site_id).where(WatchSites.watch_id == watch.id)
    )).scalars().all()

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
        # computed rollups (best/avg/target/pct/spark) — services/aggregates.item_rollups
        **await item_rollups(db, watch.user_id, item, watch, range),
        created_at=item.created_at.isoformat(),
        watch=Watch(id=watch.id, notify=watch.notify, target_price=target_price),
    )

async def listing_latest_check(listing_id: int, db: AsyncSession
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
    priced_stmt = (select(PriceChecks.price, PriceChecks.in_stock)
                   .where(PriceChecks.price.isnot(None))
                   .where(PriceChecks.listing_id == listing_id)
                   .order_by(PriceChecks.checked_at.desc())
                   .limit(1))
    with_price_check = (await db.execute(priced_stmt)).first()

    latest_stmt = (select(PriceChecks.status, PriceChecks.checked_at)
                   .where(PriceChecks.listing_id == listing_id)
                   .order_by(PriceChecks.checked_at.desc())
                   .limit(1))
    general_latest = (await db.execute(latest_stmt)).first()

    price      = str(with_price_check.price) if with_price_check is not None else None
    in_stock   = with_price_check.in_stock if with_price_check is not None else None
    status     = general_latest.status if general_latest is not None else None
    checked_at = general_latest.checked_at.isoformat() if general_latest is not None else None
    return price, in_stock, status, checked_at


@router.get("/items", response_model=Paginated[ItemSummary])
async def list_items(filters: Annotated[ItemListParams, Query()],
                     user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    # scope to the caller's watches; apply filters/search/sort/pagination
    try:
        page = filters.page or 1
        per_page = filters.per_page or 50

        # the caller's watches, joined to the shared item + its category
        stmt = (
            select(Watches, Items, Categories)
            .join(Items, Items.id == Watches.item_id)
            .join(Categories, Categories.id == Items.category_id)
            .where(Watches.user_id == user.id)
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
        summaries = [await build_item_summary(w, i, c, db, filters.range or "30d") for (w, i, c) in rows]

        # status filter runs AFTER serialize — it reads the computed fields
        if filters.status == "snagged":
            summaries = [s for s in summaries if s.target_met]
        elif filters.status == "above_target":
            summaries = [s for s in summaries if not s.target_met and s.active_listing_count > 0]
        elif filters.status == "no_listings":
            summaries = [s for s in summaries if s.active_listing_count == 0]

        total = len(summaries)
        start = (page - 1) * per_page
        summaries = summaries[start:start + per_page]

        return Paginated(
            data=summaries,
            meta=PageMeta(page=page, per_page=per_page, total=total),
        )
    except SQLAlchemyError:
        raise err(503, "db_unavailable", "Could not reach the database")


@router.post("/items", response_model=ItemSummary, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(csrf_guard)])
async def create_item(body: ItemCreateRequest, user=Depends(current_user),
                      db: AsyncSession = Depends(get_db)):
    # find-or-create items row + create watch + watch_sites; 404 category;
    # 422 (selection_mode / max_listings 1-10 / site_ids subset)
    
    try:
        stmt = select(Items
            ).where(Items.name == body.name
            ).where(Items.category_id == body.category_id)

        item = (await db.execute(stmt)).scalar_one_or_none()

        if item is None:
            item = Items(
                name            = body.name, 
                category_id     = body.category_id
            )

            db.add(item)
            await db.flush()
            await db.refresh(item)
        

        watch = Watches(
            user_id             = user.id,
            item_id             = item.id,
            target_price        = Decimal(body.target_price) if body.target_price is not None else None,
            criteria            = body.criteria,
            max_listings        = body.max_listings,
            selection_mode      = body.selection_mode,
            allow_reproductions = body.allow_reproductions,
        )

        db.add(watch)
        await db.flush()
        await db.refresh(watch)


        for site_id in (body.site_ids or []):
            watch_sites = WatchSites(
                watch_id = watch.id,
                site_id = site_id
            )
            db.add(watch_sites)
            await db.flush()
            await db.refresh(watch_sites)
        

        await db.commit()

        category = await db.get(Categories, item.category_id)

        return await build_item_summary(watch, item, category, db)
        
    except SQLAlchemyError:
        raise err(503, "db_unavailable", "Could not reach the database")


@router.get("/items/{item_id}", response_model=ItemDetail)
async def get_item(item_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Watches, Items, Categories
                 ).join(Items, Items.id == Watches.item_id
                 ).join(Categories, Categories.id == Items.category_id
                 ).where(Watches.item_id == item_id, Watches.user_id == user.id)
    row = (await db.execute(stmt)).first()
        
    if row is None:
        raise err(404, "not_found", f"Item {item_id} does not exist")
    
    watch, item, category = row

    summary = await build_item_summary(watch, item, category, db)

    listing_stmt = select(Listings, Sites.name
                ).join(Sites, Sites.id == Listings.site_id
                ).where(Listings.watch_id == watch.id
                ).order_by(Listings.created_at)

    listing_rows = (await db.execute(listing_stmt)).all()
    listings = []
    for listing, site_name in listing_rows:
        price, in_stock, latest_status, checked_at = await listing_latest_check(listing.id, db)

        listings.append(
            Listing(
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
                last_checked_at=checked_at,
                created_at=listing.created_at.isoformat(),
                discovered_by_run_id=None
            )
        )

    return ItemDetail(**summary.model_dump(), listings=listings)


@router.patch("/items/{item_id}", response_model=ItemDetail, dependencies=[Depends(csrf_guard)])
async def update_item(item_id: int, body: ItemUpdateRequest, user=Depends(current_user),
                      db: AsyncSession = Depends(get_db)):
    try:
        stmt = select(Items,Watches, Categories
                ).join(Watches, Items.id == Watches.item_id
                ).join(Categories, Categories.id == Items.category_id
                ).where(Items.id == item_id
                ).where(Watches.user_id == user.id)


        item_list_row = await db.execute(stmt)
        item_list_row = item_list_row.first()

        if item_list_row is None:
            raise err(404, "not_found", f"Item {item_id} does not exist")

        item, watch, cat = item_list_row
        if body.name is not None:
            item.name = body.name
        if body.target_price is not None:
           watch.target_price = Decimal(body.target_price)
        if body.criteria is not None:
            watch.criteria = body.criteria
        if body.selection_mode is not None:
            watch.selection_mode = body.selection_mode
        if body.max_listings is not None:
            watch.max_listings = body.max_listings
        if body.allow_reproductions is not None:
            watch.allow_reproductions = body.allow_reproductions

        await db.commit()
        summary = await build_item_summary(watch, item, cat, db)
        
        listing_stmt = select(Listings, Sites.name
                        ).join(Sites, Sites.id == Listings.site_id
                        ).where(Listings.watch_id == watch.id
                        ).order_by(Listings.created_at)
        
        listing_rows = (await db.execute(listing_stmt)).all()
        
        listings = []
        for listing, site_name in listing_rows:
            price, in_stock, latest_status, checked_at = await listing_latest_check(listing.id, db)

            listings.append(
                Listing(
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
                    last_checked_at=checked_at,
                    created_at=listing.created_at.isoformat(),
                    discovered_by_run_id=None
                )
            )
                
        return ItemDetail(**summary.model_dump(), listings=listings)
    except SQLAlchemyError:
        raise err(503, "db_unavailable", "Could not reach database")


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(csrf_guard)])
async def delete_item(item_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        watch = (await db.execute(
            select(Watches).where(Watches.item_id == item_id, Watches.user_id == user.id)
        )).scalar_one_or_none()

        if watch is None:
            raise err(404, "not_found", f"Item {item_id} does not exist")
        listing_ids = select(Listings.id).where(Listings.watch_id == watch.id)

        await db.execute(delete(ListingChecks).where(ListingChecks.watch_id == watch.id))
        await db.execute(delete(PriceChecks).where(PriceChecks.listing_id.in_(listing_ids)))
        await db.execute(delete(Listings).where(Listings.watch_id == watch.id))
        await db.execute(delete(WatchSites).where(WatchSites.watch_id == watch.id))
        await db.execute(delete(Watches).where(Watches.id == watch.id))

        await db.commit()
    except SQLAlchemyError:
        raise err(503, "db_unavailable", f"Could not reach the database")


@router.patch("/items/{item_id}/watch", response_model=Watch, dependencies=[Depends(csrf_guard)])
async def update_watch(item_id: int, body: WatchUpdateRequest, user=Depends(current_user),
                       db: AsyncSession = Depends(get_db)):
    try:
        stmt = (select(Watches)
                .where(Watches.item_id == item_id)
                .where(Watches.user_id == user.id))

        # scalar_one_or_none() -> the Watches ENTITY (tracked), not a Row
        watch = (await db.execute(stmt)).scalar_one_or_none()

        if watch is None:
            raise err(404, "not_found", f"Watch for item {item_id} does not exist")

        if body.notify is not None:
            watch.notify = body.notify
        if body.target_price is not None:
            watch.target_price = Decimal(body.target_price)

        await db.commit()

        return Watch(
            id=watch.id,
            notify=watch.notify,
            target_price=str(watch.target_price) if watch.target_price is not None else None,
        )

    except SQLAlchemyError:
        raise err(503, "db_unavailable", "Could not reach the database")
   


@router.patch("/listings/{listing_id}", response_model=Listing, dependencies=[Depends(csrf_guard)])
async def update_listing(listing_id: int, body: ListingUpdateRequest, user=Depends(current_user),
                         db: AsyncSession = Depends(get_db)):
    try:
        listing = (await db.execute(
            select(Listings)
            .join(Watches, Watches.id == Listings.watch_id)
            .where(Listings.id == listing_id, Watches.user_id == user.id)
        )).scalar_one_or_none()
        
        if listing is None:
            raise err(404, "not_found", f"Listing {listing_id} does not exist")

        listing.active = body.active
        await db.commit()

        price, in_stock, latest_status, checked_at = await listing_latest_check(listing_id, db)
        site_name = (await db.execute(
            select(Sites.name).where(Sites.id == listing.site_id)
        )).scalar_one_or_none()
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
            last_checked_at=checked_at,
            created_at=listing.created_at.isoformat(),
            discovered_by_run_id=None
            
        )
    except SQLAlchemyError:
        raise err(503, "db_unavailable", f"Could not reach the database")
@router.get("/items/{item_id}/price-checks", response_model=DataList[PriceCheck])
async def list_price_checks(item_id: int, limit: int = 50, user=Depends(current_user),
                            db: AsyncSession = Depends(get_db)):

    try:
        # join through Watches so a caller only ever sees their OWN listings' checks
        stmt = (select(PriceChecks.id.label("price_check_id"),
                       Listings.id.label("listing_id"),
                       Sites.name.label("site_name"),
                       PriceChecks.price.label("price"),
                       PriceChecks.currency.label("currency"),
                       PriceChecks.in_stock.label("in_stock"),
                       PriceChecks.status.label("status"),
                       PriceChecks.checked_at.label("checked_at"))
                .join(Listings, Listings.id == PriceChecks.listing_id)
                .join(Sites, Sites.id == Listings.site_id)
                .join(Watches, Watches.id == Listings.watch_id)
                .where(Listings.item_id == item_id)
                .where(Watches.user_id == user.id)
                .order_by(PriceChecks.checked_at.desc())
                .limit(limit))

        # .all(), NOT .scalars().all() — this is a multi-column select
        price_check_rows = (await db.execute(stmt)).all()

        price_check_list = []
        for price_check in price_check_rows:
            price_check_list.append(PriceCheck(
                id=price_check.price_check_id,
                listing_id=price_check.listing_id,
                site_name=price_check.site_name,
                price=str(price_check.price) if price_check.price is not None else None,
                currency=price_check.currency,
                in_stock=price_check.in_stock,
                status=price_check.status,
                checked_at=price_check.checked_at.isoformat(),
            ))

        return DataList(data=price_check_list)
        
    except SQLAlchemyError:
        raise err(503, "db_unavailable", "Could not reach the database")
