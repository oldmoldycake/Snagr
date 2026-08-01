"""Categories — /api/categories  (GET Phase 1, writes Phase 3). Auth required.

item_count / snagged_count / site_ids are computed (services/aggregates.py).
"""

import re

from fastapi import APIRouter, Depends, status
from sqlalchemy import delete, distinct, func, select
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
    SiteCategories,
    Sites,
    Watches,
    WatchSites,
)
from app.schemas.catalog import (
    Category,
    CategoryCreateRequest,
    CategoryUpdateRequest,
    SetCategorySitesRequest,
)
from app.schemas.common import DataList

router = APIRouter(prefix="/api/categories", tags=["categories"])


async def cat_build(id: int, name: str, slug: str, db: AsyncSession) -> Category:

    stmt = select(SiteCategories.site_id).where(SiteCategories.category_id == id)

    sites_rows = await db.execute(stmt)
    sites_rows = list(sites_rows.scalars().all())

    # FETCH DAT ITEM COUNT BROTHA
    stmt = select(func.count()).select_from(Items).where(Items.category_id == id)

    item_rows = await db.execute(stmt)
    item_count = item_rows.scalar()
    assert item_count is not None, 0

    stmt = (
        select(func.count(distinct(Listings.item_id)))
        .select_from(PriceChecks)
        .join(Listings, Listings.id == PriceChecks.listing_id)
        .join(Watches, Watches.id == Listings.watch_id)
        .join(Items, Items.id == Listings.item_id)
        .where(Items.category_id == id)
        .where(PriceChecks.price < Watches.target_price)
    )
    snag_rows = await db.execute(stmt)
    snag_count = snag_rows.scalar()
    assert snag_count is not None, 0

    return Category(
        id=id,
        name=name,
        slug=slug,
        site_ids=sites_rows,
        item_count=item_count,
        snagged_count=snag_count,
    )


@router.get("", response_model=DataList[Category])
async def list_categories(user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        # Categoiers == Obtained (or somethibng is WRONG)
        # SWAG == TRUE
        stmt = select(Categories)
        cat_rows = await db.execute(stmt)
        cat_rows = cat_rows.scalars().all()

        cats = []
        for cat in cat_rows:
            id = cat.id
            name = cat.name
            slug = cat.slug

            cats.append(await cat_build(id=id, name=name, slug=slug, db=db))
        return DataList(data=cats)

    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.post(
    "",
    response_model=Category,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(csrf_guard)],
)
async def create_category(
    body: CategoryCreateRequest, user=Depends(current_user), db: AsyncSession = Depends(get_db)
):
    if not body.name:
        raise err(
            422, "validation_error", "name is required", fields={"name": "Category already exsits"}
        )

    if await db.scalar(select(Categories).where(func.lower(Categories.name) == body.name.lower())):
        raise err(
            422,
            "validation_error",
            "Category already exsits",
            fields={"name": "Category already exsits"},
        )

    try:
        slug = re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-")
        cat = Categories(name=body.name, slug=slug)
        db.add(cat)
        await db.flush()
        await db.refresh(cat)
        await db.commit()

        return Category(
            id=cat.id, name=cat.name, slug=cat.slug, site_ids=[], item_count=0, snagged_count=0
        )
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.patch("/{category_id}", response_model=Category, dependencies=[Depends(csrf_guard)])
async def update_category(
    category_id: int,
    body: CategoryUpdateRequest,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        cat = await db.get(Categories, category_id)
        if cat is None:
            raise err(404, "not_found", f"Category {category_id} does not exsist")

        if body.name is not None:
            cat.name = body.name

        await db.commit()

        return await cat_build(id=cat.id, name=cat.name, slug=cat.slug, db=db)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.delete(
    "/{category_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(csrf_guard)]
)
async def delete_category(
    category_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)
):
    # TODO
    # need to cascade deletedd
    try:
        cat = await db.get(Categories, category_id)

        if cat is None:
            raise err(404, "not_found", f"Category {category_id} does not exsist")

        item_ids = select(Items.id).where(Items.category_id == category_id)
        watch_ids = select(Watches.id).where(Watches.item_id.in_(item_ids))
        listing_ids = select(Listings.id).where(Listings.item_id.in_(item_ids))

        await db.execute(delete(PriceChecks).where(PriceChecks.listing_id.in_(listing_ids)))
        await db.execute(delete(Listings).where(Listings.id.in_(listing_ids)))
        await db.execute(delete(WatchSites).where(WatchSites.watch_id.in_(watch_ids)))
        await db.execute(delete(ListingChecks).where(ListingChecks.watch_id.in_(watch_ids)))
        await db.execute(delete(Watches).where(Watches.id.in_(watch_ids)))
        await db.execute(delete(SiteCategories).where(SiteCategories.category_id == cat.id))
        await db.execute(delete(Items).where(Items.category_id == cat.id))

        await db.delete(cat)
        await db.commit()
        return None
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.put("/{category_id}/sites", response_model=Category, dependencies=[Depends(csrf_guard)])
async def set_category_sites(
    category_id: int,
    body: SetCategorySitesRequest,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    cat = await db.get(Categories, category_id)
    if cat is None:
        raise err(404, "not_found", f"Category {category_id} does not exist")

    valid_ids = (
        (await db.execute(select(Sites.id).where(Sites.id.in_(body.site_ids)))).scalars().all()
    )

    await db.execute(delete(SiteCategories).where(SiteCategories.category_id == category_id))
    for site_id in valid_ids:
        db.add(SiteCategories(category_id=category_id, site_id=site_id))
    await db.commit()

    return await cat_build(id=cat.id, name=cat.name, slug=cat.slug, db=db)
