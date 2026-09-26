"""Categories — /api/categories. Auth required; every write is admin-only
(403 forbidden otherwise): categories are shared by every user, and deleting
one takes every user's items, watches and price history in it with it.

item_count / snagged_count / site_ids are computed at query time
(services/catalog.py, shared with the MCP tools).
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import csrf_guard, current_user, require_admin
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
    """Every category, with counts read through the caller's watches."""
    try:
        return DataList(data=await catalog_service.list_categories(db, user.id))
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.post(
    "",
    response_model=Category,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(csrf_guard)],
)
async def create_category(
    body: CategoryCreateRequest, user=Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    """Create a category; 422 validation_error for a blank name, 422 duplicate
    for one that already exists (case-insensitive)."""
    try:
        return await catalog_service.create_category(db, body.name)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.patch("/{category_id}", response_model=Category, dependencies=[Depends(csrf_guard)])
async def update_category(
    category_id: int,
    body: CategoryUpdateRequest,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Rename a category (the slug stays); 404 for an unknown category."""
    try:
        return await catalog_service.update_category(db, category_id, body.name, user.id)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.delete(
    "/{category_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(csrf_guard)]
)
async def delete_category(
    category_id: int, user=Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    """Delete a category and everything under it — its items and every user's
    watches, listings and price checks on them. 404 for an unknown category."""
    try:
        await catalog_service.delete_category(db, category_id)
        return None
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.put("/{category_id}/sites", response_model=Category, dependencies=[Depends(csrf_guard)])
async def set_category_sites(
    category_id: int,
    body: SetCategorySitesRequest,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Replace the sites a category is searched on; unknown site ids are dropped.
    404 for an unknown category."""
    return await catalog_service.set_category_sites(db, category_id, body.site_ids, user.id)
