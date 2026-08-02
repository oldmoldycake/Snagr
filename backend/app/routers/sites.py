"""Sites — /api/sites  (GET Phase 1, writes Phase 3). Auth required.

category_ids / listing_count / last_checked_at are computed at query time
(helpers below), never stored.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import csrf_guard, current_user
from app.core.errors import err
from app.database import get_db
from app.models import Listings, PriceChecks, SiteCategories, Sites
from app.schemas.catalog import Site, SiteCreateRequest, SiteUpdateRequest
from app.schemas.common import DataList

router = APIRouter(prefix="/api/sites", tags=["sites"])


async def _listing_counts(db: AsyncSession) -> dict[int, int]:
    """site_id -> number of active listings."""
    rows = await db.execute(
        select(Listings.site_id, func.count()).where(Listings.active).group_by(Listings.site_id)
    )
    return dict(rows.all())


async def _category_ids(db: AsyncSession) -> dict[int, list[int]]:
    """site_id -> ids of the categories the site carries (ascending, like the mock)."""
    rows = await db.execute(
        select(SiteCategories.site_id, SiteCategories.category_id).order_by(
            SiteCategories.category_id
        )
    )
    out: dict[int, list[int]] = {}
    for site_id, category_id in rows.all():
        out.setdefault(site_id, []).append(category_id)
    return out


async def _last_checked(db: AsyncSession) -> dict[int, datetime]:
    """site_id -> most recent price check. Spans inactive listings too —
    the mock's toSite() only filters on active for listing_count, not here."""
    rows = await db.execute(
        select(Listings.site_id, func.max(PriceChecks.checked_at))
        .join(PriceChecks, PriceChecks.listing_id == Listings.id)
        .group_by(Listings.site_id)
    )
    return dict(rows.all())


@router.get("", response_model=DataList[Site])
async def list_sites(user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        site_rows = (await db.scalars(select(Sites).order_by(Sites.id))).all()
        counts = await _listing_counts(db)
        category_ids = await _category_ids(db)
        last_checked = await _last_checked(db)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e

    sites = [
        Site(
            id=s.id,
            name=s.name,
            base_url=s.base_url,
            created_at=s.created_at.isoformat(),
            listing_count=counts.get(s.id, 0),
            category_ids=category_ids.get(s.id, []),
            last_checked_at=(t.isoformat() if (t := last_checked.get(s.id)) else None),
        )
        for s in site_rows
    ]
    return DataList(data=sites)


@router.post(
    "", response_model=Site, status_code=status.HTTP_201_CREATED, dependencies=[Depends(csrf_guard)]
)
async def create_site(
    body: SiteCreateRequest, user=Depends(current_user), db: AsyncSession = Depends(get_db)
):
    name = body.name
    base_url = body.base_url

    if not name:
        raise err(422, "validation_error", "Name is required", fields={"name": "Name is requeired"})
    if not base_url:
        raise err(
            422, "validation_error", "Name is required", fields={"base_url": "Base URL is required"}
        )

    try:
        site = Sites(name=name, base_url=base_url)
        db.add(site)
        await db.flush()
        await db.refresh(site)
        await db.commit()

        return Site(
            id=site.id,
            name=site.name,
            base_url=site.base_url,
            created_at=site.created_at.isoformat(),
            category_ids=[],
            listing_count=0,
            last_checked_at=None,
        )
    except SQLAlchemyError as e:
        raise err(503, "validation_error", "Could not reach the database") from e


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
            raise err(404, "not_found", f"Site {site_id} does not exsist")

        if body.name is not None:
            site.name = body.name

        if body.base_url is not None:
            site.base_url = body.base_url

        await db.commit()

        return Site(
            id=site.id,
            name=site.name,
            base_url=site.base_url,
            created_at=site.created_at.isoformat(),
            category_ids=[],
            listing_count=0,
            last_checked_at=None,
        )
    except SQLAlchemyError as e:
        raise err(503, "validation_error", "Could not reach the database") from e


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
