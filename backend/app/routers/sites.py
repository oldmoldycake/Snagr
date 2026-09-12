"""Sites — /api/sites  (GET Phase 1, writes Phase 3). Auth required.

category_ids / listing_count / last_checked_at are computed at query time
(services/catalog.py, shared with the MCP tools), never stored.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import csrf_guard, current_user
from app.core.errors import err
from app.database import get_db
from app.schemas.catalog import Site, SiteCreateRequest, SiteUpdateRequest
from app.schemas.common import DataList
from app.services import catalog as catalog_service

router = APIRouter(prefix="/api/sites", tags=["sites"])


@router.get("", response_model=DataList[Site])
async def list_sites(user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        return DataList(data=await catalog_service.list_sites(db))
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.post(
    "", response_model=Site, status_code=status.HTTP_201_CREATED, dependencies=[Depends(csrf_guard)]
)
async def create_site(
    body: SiteCreateRequest, user=Depends(current_user), db: AsyncSession = Depends(get_db)
):
    try:
        return await catalog_service.create_site(db, body.name, body.base_url)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.patch("/{site_id}", response_model=Site, dependencies=[Depends(csrf_guard)])
async def update_site(
    site_id: int,
    body: SiteUpdateRequest,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await catalog_service.update_site(db, site_id, body.name, body.base_url)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.delete(
    "/{site_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(csrf_guard)]
)
async def delete_site(site_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        await catalog_service.delete_site(db, site_id)
        return None
    except SQLAlchemyError as e:
        raise err(503, "validation_error", "Could not reach the database") from e
