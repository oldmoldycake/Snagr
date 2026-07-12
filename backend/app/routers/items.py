"""Items, listings & watches — (GET Phase 1, writes Phase 3). Auth required.

An API "item" = items row + the caller's watch + watch_sites (services/items.py).
prefix is /api because this router owns both /api/items/* and /api/listings/*.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import csrf_guard, current_user
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

router = APIRouter(prefix="/api", tags=["items"])


@router.get("/items", response_model=Paginated[ItemSummary])
async def list_items(filters: Annotated[ItemListParams, Query()],
                     user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    # scope to the caller's watches; apply filters/search/sort/pagination
    raise NotImplementedError


@router.post("/items", response_model=ItemSummary, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(csrf_guard)])
async def create_item(body: ItemCreateRequest, user=Depends(current_user),
                      db: AsyncSession = Depends(get_db)):
    # find-or-create items row + create watch + watch_sites; 404 category;
    # 422 (selection_mode / max_listings 1-10 / site_ids subset)
    raise NotImplementedError


@router.get("/items/{item_id}", response_model=ItemDetail)
async def get_item(item_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    # 404 not_found
    raise NotImplementedError


@router.patch("/items/{item_id}", response_model=ItemDetail, dependencies=[Depends(csrf_guard)])
async def update_item(item_id: int, body: ItemUpdateRequest, user=Depends(current_user),
                      db: AsyncSession = Depends(get_db)):
    # 404; 422 (selection_mode / max_listings / site_ids subset)
    raise NotImplementedError


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(csrf_guard)])
async def delete_item(item_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
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
    raise NotImplementedError
