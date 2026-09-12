"""Category + site serialization — shared by routers/categories.py,
routers/sites.py and the MCP catalog tools.

item_count / snagged_count / site_ids / category_ids / listing_count /
last_checked_at are computed at query time (house pattern #2), never stored.
"""

import re
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import err
from app.models import (
    Categories,
    Items,
    ListingChecks,
    Listings,
    PriceChecks,
    SiteCategories,
    Sites,
    Watches,
    WatchSites,
)
from app.schemas.catalog import Category, Site
from app.services.aggregates import count_snagged_watches

# --- categories -------------------------------------------------------------


async def build_category(db: AsyncSession, cat: Categories, user_id: int) -> Category:
    """One categories row -> the contract's Category shape (three queries).

    item_count is instance-wide and snagged_count is the caller's, which reads
    like an inconsistency and isn't: `items` is a shared catalog, but a target
    price belongs to one watcher. Counting somebody else's snag here would put
    a ⌖ on a chip whose items all show as un-met underneath.
    """
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

    snagged_count = await count_snagged_watches(db, user_id, cat.id)

    return Category(
        id=cat.id,
        name=cat.name,
        slug=cat.slug,
        site_ids=site_ids,
        item_count=item_count or 0,
        snagged_count=snagged_count,
    )


async def list_categories(db: AsyncSession, user_id: int) -> list[Category]:
    """Every category, with counts read through the caller's watches."""
    rows = (await db.execute(select(Categories))).scalars().all()
    return [await build_category(db, cat, user_id) for cat in rows]


async def create_category(db: AsyncSession, name: str) -> Category:
    """A new category with a generated slug; the name is trimmed, then a blank
    one is 422 validation_error and a duplicate (case-insensitive) is 422
    duplicate — mock parity, including the `fields` the form renders. Commits."""
    name = name.strip()
    if not name:
        raise err(422, "validation_error", "Name is required", fields={"name": "Name is required"})

    if await db.scalar(select(Categories).where(func.lower(Categories.name) == name.lower())):
        raise err(
            422,
            "duplicate",
            "A category with this name already exists",
            fields={"name": "A category with this name already exists"},
        )

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    cat = Categories(name=name, slug=slug)
    db.add(cat)
    await db.flush()
    await db.refresh(cat)
    await db.commit()

    return Category(
        id=cat.id, name=cat.name, slug=cat.slug, site_ids=[], item_count=0, snagged_count=0
    )


async def update_category(
    db: AsyncSession, category_id: int, name: str | None, user_id: int
) -> Category:
    """Rename (the slug stays); 404 unknown. Commits."""
    cat = await db.get(Categories, category_id)
    if cat is None:
        raise err(404, "not_found", f"Category {category_id} does not exsist")

    if name is not None:
        cat.name = name

    await db.commit()
    return await build_category(db, cat, user_id)


async def delete_category(db: AsyncSession, category_id: int) -> None:
    """Delete a category and everything under it — its items, every user's
    watches on them, their listings and checks. 404 unknown. Commits."""
    cat = await db.get(Categories, category_id)
    if cat is None:
        raise err(404, "not_found", f"Category {category_id} does not exsist")

    item_ids = select(Items.id).where(Items.category_id == category_id)
    watch_ids = select(Watches.id).where(Watches.item_id.in_(item_ids))
    listing_ids = select(Listings.id).where(Listings.item_id.in_(item_ids))

    await db.execute(delete(PriceChecks).where(PriceChecks.listing_id.in_(listing_ids)))
    await db.execute(delete(Listings).where(Listings.id.in_(listing_ids)))
    await db.execute(delete(WatchSites).where(WatchSites.watch_id.in_(watch_ids)))
    await db.execute(delete(ListingChecks).where(ListingChecks.watch_id.in_(watch_ids)))
    await db.execute(delete(Watches).where(Watches.id.in_(watch_ids)))
    await db.execute(delete(SiteCategories).where(SiteCategories.category_id == cat.id))
    await db.execute(delete(Items).where(Items.category_id == cat.id))

    await db.delete(cat)
    await db.commit()


async def set_category_sites(
    db: AsyncSession, category_id: int, site_ids: list[int], user_id: int
) -> Category:
    """Replace the set of sites a category is searched on; unknown site ids
    are silently dropped. 404 unknown category. Commits."""
    cat = await db.get(Categories, category_id)
    if cat is None:
        raise err(404, "not_found", f"Category {category_id} does not exist")

    valid_ids = (await db.execute(select(Sites.id).where(Sites.id.in_(site_ids)))).scalars().all()

    await db.execute(delete(SiteCategories).where(SiteCategories.category_id == category_id))
    for site_id in valid_ids:
        db.add(SiteCategories(category_id=category_id, site_id=site_id))
    await db.commit()

    return await build_category(db, cat, user_id)


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


async def create_site(db: AsyncSession, name: str, base_url: str) -> Site:
    """A new site; both fields are trimmed and base_url loses one trailing
    slash (mock parity), then blanks are 422. Commits."""
    name = name.strip()
    base_url = base_url.strip().removesuffix("/")
    if not name or not base_url:
        raise err(422, "validation_error", "Name and base URL are required")

    site = Sites(name=name, base_url=base_url)
    db.add(site)
    await db.flush()
    await db.refresh(site)
    await db.commit()
    # a brand-new site has no listings/categories/checks — empty lookups
    # give site_out the right zeros without querying
    return site_out(site, {}, {}, {})


async def update_site(
    db: AsyncSession, site_id: int, name: str | None, base_url: str | None
) -> Site:
    """Edit a site; 404 unknown. Falsy fields are skipped (an empty string
    is "leave it"), values are trimmed, base_url loses one trailing slash —
    mock parity. Commits."""
    site = await db.get(Sites, site_id)
    if site is None:
        raise err(404, "not_found", f"Site {site_id} does not exist")

    if name:
        site.name = name.strip()
    if base_url:
        site.base_url = base_url.strip().removesuffix("/")
    await db.commit()

    counts = await listing_counts(db)
    category_ids = await site_category_ids(db)
    checked = await last_checked(db)
    return site_out(site, counts, category_ids, checked)


async def delete_site(db: AsyncSession, site_id: int) -> None:
    """Delete a site; 404 unknown. A site with listings still referencing it
    fails the FK and surfaces as the caller's database error. Commits."""
    site = await db.get(Sites, site_id)
    if site is None:
        raise err(404, "not_found", f"Site {site_id} does not exist")

    await db.delete(site)
    await db.commit()
