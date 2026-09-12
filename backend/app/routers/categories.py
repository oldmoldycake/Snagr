"""Categories — /api/categories  (GET Phase 1, writes Phase 3). Auth required.

item_count / snagged_count / site_ids are computed at query time
(services/catalog.py, shared with the MCP tools).
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import csrf_guard, current_user
from app.core.errors import err
from app.database import get_db
from app.schemas.catalog import (
    Category,
    CategoryCreateRequest,
    CategoryUpdateRequest,
    SetCategorySitesRequest,
)
from app.schemas.common import DataList
from app.services import catalog as catalog_service

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("", response_model=DataList[Category])
async def list_categories(user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        return DataList(data=await catalog_service.list_categories(db))
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
    try:
        return await catalog_service.create_category(db, body.name)
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
        return await catalog_service.update_category(db, category_id, body.name)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.delete(
    "/{category_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(csrf_guard)]
)
async def delete_category(
    category_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)
):
    try:
        await catalog_service.delete_category(db, category_id)
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
    return await catalog_service.set_category_sites(db, category_id, body.site_ids)
