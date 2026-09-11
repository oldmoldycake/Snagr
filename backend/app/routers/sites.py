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
from app.models import Sites
from app.schemas.catalog import Site, SiteCreateRequest, SiteUpdateRequest
from app.schemas.common import DataList
from app.services import catalog as catalog_service
from app.services.catalog import site_out

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
    # mock parity: trim both fields, drop one trailing slash, then reject blanks
    name = body.name.strip()
    base_url = body.base_url.strip().removesuffix("/")
    if not name or not base_url:
        raise err(422, "validation_error", "Name and base URL are required")

    try:
        site = Sites(name=name, base_url=base_url)
        db.add(site)
        await db.flush()
        await db.refresh(site)
        await db.commit()
        # a brand-new site has no listings/categories/checks — empty lookups
        # give site_out the right zeros without querying
        return site_out(site, {}, {}, {})
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
        site = await db.get(Sites, site_id)
        if site is None:
            raise err(404, "not_found", f"Site {site_id} does not exist")

        # mock parity: falsy fields are skipped (an empty string is "leave it"),
        # values are trimmed, base_url loses one trailing slash
        if body.name:
            site.name = body.name.strip()
        if body.base_url:
            site.base_url = body.base_url.strip().removesuffix("/")
        await db.commit()

        counts = await catalog_service.listing_counts(db)
        category_ids = await catalog_service.site_category_ids(db)
        checked = await catalog_service.last_checked(db)
        return site_out(site, counts, category_ids, checked)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.delete(
    "/{site_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(csrf_guard)]
)
async def delete_site(site_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        site = await db.get(Sites, site_id)

        if site is None:
            raise err(404, "not_found", f"Site {site_id} does not exist")

        await db.delete(site)
        await db.commit()
        return None

    except SQLAlchemyError as e:
        raise err(503, "validation_error", "Could not reach the database") from e
