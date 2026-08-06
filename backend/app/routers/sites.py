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


def _site_out(
    s: Sites,
    counts: dict[int, int],
    category_ids: dict[int, list[int]],
    last_checked: dict[int, datetime],
) -> Site:
    """The contract's Site shape — the backend twin of the mock's toSite()."""
    return Site(
        id=s.id,
        name=s.name,
        base_url=s.base_url,
        created_at=s.created_at.isoformat(),
        listing_count=counts.get(s.id, 0),
        category_ids=category_ids.get(s.id, []),
        last_checked_at=(t.isoformat() if (t := last_checked.get(s.id)) else None),
    )


@router.get("", response_model=DataList[Site])
async def list_sites(user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        site_rows = (await db.scalars(select(Sites).order_by(Sites.id))).all()
        counts = await _listing_counts(db)
        category_ids = await _category_ids(db)
        last_checked = await _last_checked(db)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e

    sites = [_site_out(s, counts, category_ids, last_checked) for s in site_rows]
    return DataList(data=sites)


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
        # give _site_out the right zeros without querying
        return _site_out(site, {}, {}, {})
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

        counts = await _listing_counts(db)
        category_ids = await _category_ids(db)
        last_checked = await _last_checked(db)
        return _site_out(site, counts, category_ids, last_checked)
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
