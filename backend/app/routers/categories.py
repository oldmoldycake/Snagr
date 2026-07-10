"""Categories — /api/categories  (GET Phase 1, writes Phase 3). Auth required.

item_count / snagged_count / site_ids are computed (services/aggregates.py).
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import csrf_guard, current_user
from app.database import get_db
from app.schemas.catalog import (
    Category,
    CategoryCreateRequest,
    CategoryUpdateRequest,
    SetCategorySitesRequest,
)
from app.schemas.common import DataList

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("", response_model=DataList[Category])
async def list_categories(user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    raise NotImplementedError


@router.post("", response_model=Category, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(csrf_guard)])
async def create_category(body: CategoryCreateRequest, user=Depends(current_user),
                          db: AsyncSession = Depends(get_db)):
    # 422 validation_error (name required) / 422 duplicate (name exists)
    raise NotImplementedError


@router.patch("/{category_id}", response_model=Category, dependencies=[Depends(csrf_guard)])
async def update_category(category_id: int, body: CategoryUpdateRequest,
                          user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    # 404 not_found
    raise NotImplementedError


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(csrf_guard)])
async def delete_category(category_id: int, user=Depends(current_user),
                          db: AsyncSession = Depends(get_db)):
    raise NotImplementedError


@router.put("/{category_id}/sites", response_model=Category, dependencies=[Depends(csrf_guard)])
async def set_category_sites(category_id: int, body: SetCategorySitesRequest,
                             user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    raise NotImplementedError
