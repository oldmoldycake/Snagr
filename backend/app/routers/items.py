"""Items, listings & watches — (GET Phase 1, writes Phase 3). Auth required.

An API "item" = items row + the caller's watch + watch_sites (services/items.py).
prefix is /api because this router owns both /api/items/* and /api/listings/*.
"""

from functools import singledispatch
from os import name
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import except_, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
 
from app.core.deps import csrf_guard, current_user
from app.core.errors import err
from app.database import get_db
from app.models import PriceChecks, Watches, Items, WatchSites, Listings, Sites, Categories
from app.schemas.items import ItemCreateRequest
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
                             db: AsyncSession) -> ItemSummary:
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
        # ---- computed rollups: PLACEHOLDERS (Pass 2 -> services/aggregates.item_rollups) ----
        best_price=None,
        best_listing_id=None,
        best_site_name=None,
        avg_price=None,
        active_listing_count=0,
        target_met=False,
        pct_change_range=None,
        last_checked_at=None,
        spark=[],
        # -------------------------------------------------------------------------------------
        created_at=item.created_at.isoformat(),
        watch=Watch(id=watch.id, notify=watch.notify, target_price=target_price),
    )


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
        summaries = [await build_item_summary(w, i, c, db) for (w, i, c) in rows]

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
        item = Items(
            name            = body.name, 
            category_id     = body.category_id
        )
        
        db.add(item)
        await db.flush()
        await db.refresh(item)
        await db.commit()


        #TODO:
        #Where is user id located at?
        watch = Watches(
            item_id             = item.id,
            target_price        = body.target_price,
            criteria            = body.criteria,
            max_listings        = body.max_listings,
            allow_reproductions = body.allow_reproductions,
        )
        
        db.add(watch)
        await db.flush()
        await db.refresh(watch)
        await db.commit()


        assert body.site_ids is not None, []
        for site_id in body.site_ids:
            watch_sites = WatchSites(
                watch_id = watch.id,
                site_id = site_id
            )
            await db.flush()
            await db.refresh(watch_sites)
            await db.commit()

    except SQLAlchemyError:
        raise err(503, "db_unavailable", "Could not reach the database")


    raise NotImplementedError


@router.get("/items/{item_id}", response_model=ItemDetail)
async def get_item(item_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    # 404 not_found
    item = await db.get(Items, item_id)
    
    if item is None:
        raise err(404, "not_found", f"Item {item_id} not found")

    stmt = select(func.max(PriceChecks.checked_at)
        ).join(Listings, Listings.id == PriceChecks.listing_id
        ).where(Listings.site_id == id)
    last = await db.execute(stmt)
    last = last.scalar()
    last_checked_at = last.isoformat() if last else None

    return [
        Listing(

        )
    ]


@router.patch("/items/{item_id}", response_model=ItemDetail, dependencies=[Depends(csrf_guard)])
async def update_item(item_id: int, body: ItemUpdateRequest, user=Depends(current_user),
                      db: AsyncSession = Depends(get_db)):
    # 404; 422 (selection_mode / max_listings / site_ids subset)
    raise NotImplementedError


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(csrf_guard)])
async def delete_item(item_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    #rememebr to cascade items from taables liek watches, and price checks
    raise NotImplementedError


@router.patch("/items/{item_id}/watch", response_model=Watch, dependencies=[Depends(csrf_guard)])
async def update_watch(item_id: int, body: WatchUpdateRequest, user=Depends(current_user),
                       db: AsyncSession = Depends(get_db)):
    # 404 not_found
    raise NotImplementedError

@router.patch("/listings/{listing_id}", response_model=Listing, dependencies=[Depends(csrf_guard)])
async def update_listing(listing_id: int, body: ListingUpdateRequest, user=Depends(current_user),
                         db: AsyncSession = Depends(get_db)):
    # body: {active}; 404 not_found
    raise NotImplementedError


@router.get("/items/{item_id}/price-checks", response_model=DataList[PriceCheck])
async def list_price_checks(item_id: int, limit: int = 50, user=Depends(current_user),
                            db: AsyncSession = Depends(get_db)):

    try:
        stmt = select(PriceChecks.id.label("price_check_id"),
                      Listings.id.label("listing_id"), 
                      Sites.name.label("site_name"), 
                      PriceChecks.price.label("price"), 
                      PriceChecks.currency.label("currency"), 
                      PriceChecks.in_stock.label("in_stock"),
                      PriceChecks.status.label("status"), 
                      PriceChecks.checked_at.label("checked_at")
                      ).join(Listings, Listings.id == PriceChecks.listing_id
                      ).where(Listings.item_id == item_id
                      ).limit(limit)

        price_check_rows = await db.execute(stmt)
        price_check_rows = price_check_rows.scalars().all()
        
        price_check_list = []
        for price_check in price_check_rows:
            price_check_list.append(PriceCheck(
                id=price_check.price_check_id,
                listing_id=price_check.listing_id,
                site_name=price_check.site_name,
                price=price_check.price,
                currency=price_check.currency,
                in_stock=price_check.in_stock,
                status=price_check.status,
                checked_at=price_check.checked_at
            ))

        return DataList(data=price_check_list)
        
    except SQLAlchemyError:
        raise err(503, "db_unavailable", "Could not reach the database")
