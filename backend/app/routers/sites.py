"""Sites — /api/sites. Auth required; every write is admin-only (403
forbidden otherwise): sites are shared, and the hunter searches a site's
base_url on every user's behalf.

category_ids / listing_count / last_checked_at are computed at query time
(services/catalog.py, shared with the MCP tools), never stored. paused_until
and paused_reason ARE stored — the hunter's circuit breaker writes them, and
the only thing this API can do with a pause is lift it.
"""

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import csrf_guard, current_user, require_admin
from app.core.errors import err
from app.database import get_db
from app.schemas.catalog import Site, SiteCreateRequest, SiteUpdateRequest
from app.schemas.common import DataList
from app.services import catalog as catalog_service

router = APIRouter(prefix="/api/sites", tags=["sites"])


@router.get("", response_model=DataList[Site])
async def list_sites(user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Every site, with computed counts and any breaker pause."""
    try:
        return DataList(data=await catalog_service.list_sites(db))
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.post(
    "", response_model=Site, status_code=status.HTTP_201_CREATED, dependencies=[Depends(csrf_guard)]
)
async def create_site(
    body: SiteCreateRequest, user=Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    """Add a site; 422 validation_error when the name or base URL is blank."""
    try:
        return await catalog_service.create_site(db, body.name, body.base_url)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.patch("/{site_id}", response_model=Site, dependencies=[Depends(csrf_guard)])
async def update_site(
    site_id: int,
    body: SiteUpdateRequest,
    request: Request,
    user=Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Rename a site, change its base URL, or lift a pause; 404 for an unknown site.

    paused_until accepts only null: the hunter's breaker sets pauses, a person
    can only lift one. Any other value is 422 validation_error."""
    # the hunter sets pauses; a person can only lift one, so null is the only
    # value this field takes — and "absent" has to be told apart from "null"
    clear_pause = "paused_until" in await request.json()
    if clear_pause and body.paused_until is not None:
        raise err(
            422,
            "validation_error",
            "only null is accepted; the hunter sets pauses",
            fields={"paused_until": "only null is accepted; the hunter sets pauses"},
        )
    try:
        return await catalog_service.update_site(
            db, site_id, body.name, body.base_url, clear_pause=clear_pause
        )
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.delete(
    "/{site_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(csrf_guard)]
)
async def delete_site(
    site_id: int, user=Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    """Delete a site; 404 for an unknown site. One that listings still reference
    fails the foreign key and answers 503 db_unavailable."""
    try:
        await catalog_service.delete_site(db, site_id)
        return None
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e
