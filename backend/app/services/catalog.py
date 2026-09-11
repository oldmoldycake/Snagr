"""Category + site serialization — shared by routers/categories.py,
routers/sites.py and the MCP catalog tools.

item_count / snagged_count / site_ids / category_ids / listing_count /
last_checked_at are computed at query time (house pattern #2), never stored.
"""

from datetime import datetime

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Categories, Items, Listings, PriceChecks, SiteCategories, Sites, Watches
from app.schemas.catalog import Category, Site

# --- categories -------------------------------------------------------------


async def build_category(db: AsyncSession, cat: Categories) -> Category:
    """One categories row -> the contract's Category shape (three queries)."""
    site_ids = list(
        (
            await db.execute(
                select(SiteCategories.site_id).where(SiteCategories.category_id == cat.id)
            )
        )
        .scalars()
        .all()
    )

    item_count = await db.scalar(
        select(func.count()).select_from(Items).where(Items.category_id == cat.id)
    )

    snagged_count = await db.scalar(
        select(func.count(distinct(Listings.item_id)))
        .select_from(PriceChecks)
        .join(Listings, Listings.id == PriceChecks.listing_id)
        .join(Watches, Watches.id == Listings.watch_id)
        .join(Items, Items.id == Listings.item_id)
        .where(Items.category_id == cat.id)
        .where(PriceChecks.price < Watches.target_price)
    )

    return Category(
        id=cat.id,
        name=cat.name,
        slug=cat.slug,
        site_ids=site_ids,
        item_count=item_count or 0,
        snagged_count=snagged_count or 0,
    )


async def list_categories(db: AsyncSession) -> list[Category]:
    """Every category with its counts (the catalog is shared, not per user)."""
    rows = (await db.execute(select(Categories))).scalars().all()
    return [await build_category(db, cat) for cat in rows]


# --- sites ------------------------------------------------------------------


async def listing_counts(db: AsyncSession) -> dict[int, int]:
    """site_id -> number of active listings."""
    rows = await db.execute(
        select(Listings.site_id, func.count()).where(Listings.active).group_by(Listings.site_id)
    )
    return dict(rows.all())


async def site_category_ids(db: AsyncSession) -> dict[int, list[int]]:
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


async def last_checked(db: AsyncSession) -> dict[int, datetime]:
    """site_id -> most recent price check. Spans inactive listings too —
    the mock's toSite() only filters on active for listing_count, not here."""
    rows = await db.execute(
        select(Listings.site_id, func.max(PriceChecks.checked_at))
        .join(PriceChecks, PriceChecks.listing_id == Listings.id)
        .group_by(Listings.site_id)
    )
    return dict(rows.all())


def site_out(
    s: Sites,
    counts: dict[int, int],
    category_ids: dict[int, list[int]],
    checked: dict[int, datetime],
) -> Site:
    """The contract's Site shape — the backend twin of the mock's toSite()."""
    return Site(
        id=s.id,
        name=s.name,
        base_url=s.base_url,
        created_at=s.created_at.isoformat(),
        listing_count=counts.get(s.id, 0),
        category_ids=category_ids.get(s.id, []),
        last_checked_at=(t.isoformat() if (t := checked.get(s.id)) else None),
    )


async def list_sites(db: AsyncSession) -> list[Site]:
    """Every site with its counts — four queries total, not N+1."""
    site_rows = (await db.scalars(select(Sites).order_by(Sites.id))).all()
    counts = await listing_counts(db)
    category_ids = await site_category_ids(db)
    checked = await last_checked(db)
    return [site_out(s, counts, category_ids, checked) for s in site_rows]
