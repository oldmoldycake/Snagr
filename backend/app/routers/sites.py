"""Sites — /api/sites  (GET Phase 1, writes Phase 3). Auth required.

category_ids / listing_count / last_checked_at are computed (services/aggregates.py).
"""

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


@router.get("", response_model=DataList[Site])
async def list_sites(user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        stmt = select(Sites)
        site_rows = await db.execute(stmt)
        site_rows = site_rows.scalars().all()
        
        sites = []
        for s in site_rows:
            id          = s.id
            name        = s.name
            created_at  = s.created_at
            base_url    = s.base_url
            
            #Select the total listings on the site
            stmt = select(func.count()
                ).select_from(Listings
                ).where(Listings.active == True
                ).where(Listings.site_id == id)
            listing_rows = await db.execute(stmt)
            count = listing_rows.scalar()
            assert count is not None, 0

            #Fet the category ids for the site 
            stmt = select(SiteCategories.category_id
            ).where(SiteCategories.site_id == id)
            cat_ids = await db.execute(stmt)
            cat_ids = list(cat_ids.scalars().all())

            stmt = select(func.max(PriceChecks.checked_at)
            ).join(Listings, Listings.id == PriceChecks.listing_id
            ).where(Listings.site_id == id)
            last = await db.execute(stmt)
            last = last.scalar()
            last_checked_at = last.isoformat() if last else None

            sites.append(
                Site(
                    id = id,
                    name = name,
                    created_at = created_at.isoformat(),
                    listing_count=count,
                    base_url=base_url,
                    last_checked_at = last_checked_at,
                    category_ids=cat_ids
                )
            )

        return DataList(data=sites)
    except SQLAlchemyError:
        raise err(503, "db_unavailable", "Could not reach the database")


@router.post("", response_model=Site, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(csrf_guard)])
async def create_site(body: SiteCreateRequest, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    name = body.name
    base_url = body.base_url

    if not name:
                  raise err(422, "validation_error", "Name is required",
                  fields={"name": "Name is requeired"})
    if not base_url:
        raise err(422, "validation_error", "Name is required",
                  fields={"base_url": "Base URL is required"})

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
            last_checked_at=None
        )
    except SQLAlchemyError:
        raise err(503, "validation_error", "Could not reach the database")
 



@router.patch("/{site_id}", response_model=Site, dependencies=[Depends(csrf_guard)])
async def update_site(site_id: int, body: SiteUpdateRequest, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
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
            last_checked_at=None
        )
    except SQLAlchemyError:
        raise err(503, "validation_error", "Could not reach the database")

@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(csrf_guard)])
async def delete_site(site_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        site = await db.get(Sites, site_id)

        if site is None:
            raise err(404, "not_found", f"Site {site_id} does not exist")

        await db.delete(site)
        await db.commit()
        return None

    except SQLAlchemyError:
        raise err(503, "validation_error", "Could not reach the database")
