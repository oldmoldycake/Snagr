"""Items, listings & watches — (GET Phase 1, writes Phase 3). Auth required.

An API "item" = items row + the caller's watch + watch_sites; the logic lives
in services/items.py (shared with the MCP tools) and this router is the HTTP
layer over it. prefix is /api because this router owns both /api/items/* and
/api/listings/*.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import csrf_guard, current_user
from app.core.errors import err
from app.database import get_db
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
    try:
        return await items_service.create_item(db, user.id, body)
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
        return await items_service.update_item(db, user.id, item_id, body)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach database") from e


@router.delete(
    "/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(csrf_guard)]
)
async def delete_item(item_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        await items_service.delete_item(db, user.id, item_id)
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
        return await items_service.update_watch(db, user.id, item_id, body)
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
        return await items_service.update_listing(db, user.id, listing_id, body.active)
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
