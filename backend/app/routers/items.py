"""Items, listings & watches — (GET Phase 1, writes Phase 3). Auth required.

An API "item" = items row + the caller's watch + watch_sites. The reads and
the serializers live in services/items.py (shared with the MCP tools); the
writes are still inline here. prefix is /api because this router owns both
/api/items/* and /api/listings/*.
"""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import csrf_guard, current_user
from app.core.errors import err
from app.database import get_db
from app.models import (
    Categories,
    Items,
    ListingChecks,
    Listings,
    PriceChecks,
    Sites,
    Watches,
    WatchSites,
)
from app.schemas.common import DataList, Paginated
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
from app.services import items as items_service
from app.services.items import build_item_summary, listing_out, load_listings
from app.services.vision import authenticity_for_listings

router = APIRouter(prefix="/api", tags=["items"])


@router.get("/items", response_model=Paginated[ItemSummary])
async def list_items(
    filters: Annotated[ItemListParams, Query()],
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await items_service.list_items(db, user.id, filters)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.post(
    "/items",
    response_model=ItemSummary,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(csrf_guard)],
)
async def create_item(
    body: ItemCreateRequest, user=Depends(current_user), db: AsyncSession = Depends(get_db)
):
    # find-or-create items row + create watch + watch_sites; 404 category;
    # 422 (selection_mode / max_listings 1-10 / site_ids subset)

    try:
        stmt = (
            select(Items)
            .where(Items.name == body.name)
            .where(Items.category_id == body.category_id)
        )

        item = (await db.execute(stmt)).scalar_one_or_none()

        if item is None:
            item = Items(name=body.name, category_id=body.category_id)

            db.add(item)
            await db.flush()
            await db.refresh(item)

        watch = Watches(
            user_id=user.id,
            item_id=item.id,
            target_price=Decimal(body.target_price) if body.target_price is not None else None,
            criteria=body.criteria,
            max_listings=body.max_listings,
            selection_mode=body.selection_mode,
            allow_reproductions=body.allow_reproductions,
        )

        db.add(watch)
        await db.flush()
        await db.refresh(watch)

        for site_id in body.site_ids or []:
            watch_sites = WatchSites(watch_id=watch.id, site_id=site_id)
            db.add(watch_sites)
            await db.flush()
            await db.refresh(watch_sites)

        await db.commit()

        category = await db.get(Categories, item.category_id)

        return await build_item_summary(watch, item, category, db)

    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.get("/items/{item_id}", response_model=ItemDetail)
async def get_item(item_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await items_service.get_item_detail(db, user.id, item_id)


@router.patch("/items/{item_id}", response_model=ItemDetail, dependencies=[Depends(csrf_guard)])
async def update_item(
    item_id: int,
    body: ItemUpdateRequest,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        stmt = (
            select(Items, Watches, Categories)
            .join(Watches, Items.id == Watches.item_id)
            .join(Categories, Categories.id == Items.category_id)
            .where(Items.id == item_id)
            .where(Watches.user_id == user.id)
        )

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
        return ItemDetail(**summary.model_dump(), listings=await load_listings(db, watch))
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach database") from e


@router.delete(
    "/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(csrf_guard)]
)
async def delete_item(item_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        watch = (
            await db.execute(
                select(Watches).where(Watches.item_id == item_id, Watches.user_id == user.id)
            )
        ).scalar_one_or_none()

        if watch is None:
            raise err(404, "not_found", f"Item {item_id} does not exist")
        listing_ids = select(Listings.id).where(Listings.watch_id == watch.id)

        await db.execute(delete(ListingChecks).where(ListingChecks.watch_id == watch.id))
        await db.execute(delete(PriceChecks).where(PriceChecks.listing_id.in_(listing_ids)))
        await db.execute(delete(Listings).where(Listings.watch_id == watch.id))
        await db.execute(delete(WatchSites).where(WatchSites.watch_id == watch.id))
        await db.execute(delete(Watches).where(Watches.id == watch.id))

        await db.commit()
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.patch("/items/{item_id}/watch", response_model=Watch, dependencies=[Depends(csrf_guard)])
async def update_watch(
    item_id: int,
    body: WatchUpdateRequest,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        stmt = select(Watches).where(Watches.item_id == item_id).where(Watches.user_id == user.id)

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

    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.patch("/listings/{listing_id}", response_model=Listing, dependencies=[Depends(csrf_guard)])
async def update_listing(
    listing_id: int,
    body: ListingUpdateRequest,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        listing = (
            await db.execute(
                select(Listings)
                .join(Watches, Watches.id == Listings.watch_id)
                .where(Listings.id == listing_id, Watches.user_id == user.id)
            )
        ).scalar_one_or_none()

        if listing is None:
            raise err(404, "not_found", f"Listing {listing_id} does not exist")

        listing.active = body.active
        await db.commit()

        site_name = (
            await db.execute(select(Sites.name).where(Sites.id == listing.site_id))
        ).scalar_one_or_none()
        authenticity = await authenticity_for_listings(db, listing.watch_id, [listing.url])
        return await listing_out(db, listing, site_name, authenticity)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.get("/items/{item_id}/price-checks", response_model=DataList[PriceCheck])
async def list_price_checks(
    item_id: int, limit: int = 50, user=Depends(current_user), db: AsyncSession = Depends(get_db)
):
    try:
        return DataList(data=await items_service.list_price_checks(db, user.id, item_id, limit))
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e
