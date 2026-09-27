"""Category + site serialization — shared by routers/categories.py,
routers/sites.py and the MCP catalog tools.

item_count / snagged_count / site_ids / category_ids / listing_count /
last_checked_at are computed at query time (house pattern #2), never stored.
"""

import re
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError, err
from app.models import (
    Categories,
    Items,
    Jobs,
    ListingChecks,
    Listings,
    MarketPrices,
    PriceChecks,
    SiteCategories,
    Sites,
    Watches,
    WatchSites,
)
from app.schemas.catalog import Category, Site
from app.services.aggregates import count_snagged_watches

# --- names ------------------------------------------------------------------


async def checked_name(
    db: AsyncSession,
    model: type[Categories] | type[Sites],
    name: str,
    exclude_id: int | None = None,
) -> str:
    """The name trimmed, or 422: validation_error when blank, duplicate when
    another row of `model` has it already, ignoring case. Create and rename
    both come through here, so a rename can't do what a create may not. The
    check reads before the write, so a concurrent request can still take the
    name in between; flush_name answers that with the same 422.

    Site names ignoring case matter beyond tidiness: the MCP tools address a
    site by name, and two sites answering to one leave every agent with an
    ambiguous reference."""
    name = name.strip()
    if not name:
        raise err(422, "validation_error", "Name is required", fields={"name": "Name is required"})

    clash = select(model.id).where(func.lower(model.name) == name.lower())
    if exclude_id is not None:
        clash = clash.where(model.id != exclude_id)
    if await db.scalar(clash) is not None:
        raise _duplicate_name(model)
    return name


def _duplicate_name(model: type[Categories] | type[Sites]) -> ApiError:
    """The 422 for a name another row of `model` already has."""
    noun = "category" if model is Categories else "site"
    message = f"A {noun} with this name already exists"
    return err(422, "duplicate", message, fields={"name": message})


# the unique indexes that hold a name: categories.name's own constraint and
# the lower(name) ones. categories_slug_key is not here — a slug clash is not
# the caller's name being taken.
_NAME_CONSTRAINTS = {"categories_name_key", "uq_categories_name", "uq_sites_name"}


async def flush_name(db: AsyncSession, model: type[Categories] | type[Sites]) -> None:
    """Flush the pending write, turning a name the unique index refuses into
    checked_name's 422 duplicate: two concurrent requests can both pass that
    read before either writes, and the later one otherwise surfaces as a raw
    IntegrityError (a 409)."""
    try:
        await db.flush()
    except IntegrityError as exc:
        if _constraint_name(exc) in _NAME_CONSTRAINTS:
            raise _duplicate_name(model) from exc
        raise


def _constraint_name(exc: IntegrityError) -> str | None:
    """The index or constraint a write violated. asyncpg's own error, which
    names it, is the DBAPI error's cause."""
    return getattr(exc.orig.__cause__, "constraint_name", None)


# --- categories -------------------------------------------------------------

# a create reads for a free slug, then loses it to a concurrent create only if
# that one's name slugs the same and commits in between; a few rereads settle
# it, and a run of losses past that is something to look at, not to hide
_SLUG_ATTEMPTS = 5


async def unique_slug(db: AsyncSession, name: str) -> str:
    """A slug for a new category: the name's letters and digits joined by
    hyphens, "category" when it has none (an emoji or "++" name would
    otherwise get "" and a /categories/ link that goes nowhere), and -2, -3…
    appended when another category holds it — "C" and "C++" both make "c"."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "category"
    taken = set(
        (
            await db.scalars(
                select(Categories.slug).where(
                    or_(Categories.slug == base, Categories.slug.like(f"{base}-%"))
                )
            )
        ).all()
    )
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug


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
    """A new category with a generated, unique slug; the name is trimmed, then
    a blank one is 422 validation_error and a duplicate (case-insensitive) is
    422 duplicate — mock parity, including the `fields` the form renders.
    Commits."""
    name = await checked_name(db, Categories, name)
    for attempt in range(_SLUG_ATTEMPTS):
        cat = Categories(name=name, slug=await unique_slug(db, name))
        try:
            # a savepoint, so a lost slug rolls back only this INSERT
            async with db.begin_nested():
                db.add(cat)
                await flush_name(db, Categories)
            break
        except IntegrityError as exc:
            # a concurrent create whose name slugs the same ("C++" beside "C")
            # took this slug after unique_slug read it: read again for the next
            if _constraint_name(exc) != "categories_slug_key" or attempt == _SLUG_ATTEMPTS - 1:
                raise
    await db.refresh(cat)
    await db.commit()

    return Category(
        id=cat.id, name=cat.name, slug=cat.slug, site_ids=[], item_count=0, snagged_count=0
    )


async def update_category(
    db: AsyncSession, category_id: int, name: str | None, user_id: int
) -> Category:
    """Rename (the slug stays, so links to the category keep working); 404
    unknown, then the name is held to create's rules — trimmed, 422
    validation_error blank, 422 duplicate taken by another category. Commits."""
    cat = await db.get(Categories, category_id)
    if cat is None:
        raise err(404, "not_found", f"Category {category_id} does not exist")

    if name is not None:
        cat.name = await checked_name(db, Categories, name, exclude_id=cat.id)

    await flush_name(db, Categories)
    await db.commit()
    return await build_category(db, cat, user_id)


async def delete_category(db: AsyncSession, category_id: int) -> None:
    """Delete a category and everything under it — its items and their market
    stats, every user's watches on them, their listings and checks. 404
    unknown. Commits."""
    cat = await db.get(Categories, category_id)
    if cat is None:
        raise err(404, "not_found", f"Category {category_id} does not exist")

    item_ids = select(Items.id).where(Items.category_id == category_id)
    watch_ids = select(Watches.id).where(Watches.item_id.in_(item_ids))
    listing_ids = select(Listings.id).where(Listings.item_id.in_(item_ids))

    await db.execute(delete(PriceChecks).where(PriceChecks.listing_id.in_(listing_ids)))
    await db.execute(delete(Listings).where(Listings.id.in_(listing_ids)))
    await db.execute(delete(WatchSites).where(WatchSites.watch_id.in_(watch_ids)))
    await db.execute(delete(ListingChecks).where(ListingChecks.watch_id.in_(watch_ids)))
    await db.execute(delete(Watches).where(Watches.id.in_(watch_ids)))
    await db.execute(delete(SiteCategories).where(SiteCategories.category_id == cat.id))
    await db.execute(delete(MarketPrices).where(MarketPrices.item_id.in_(item_ids)))
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

    # read every id and match here, not `WHERE id IN (...)`: an id past what
    # the column holds is unknown too, and asyncpg refuses to send it
    known = set((await db.execute(select(Sites.id))).scalars())
    valid_ids = known.intersection(site_ids)

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
        paused_until=s.paused_until.isoformat() if s.paused_until is not None else None,
        paused_reason=s.paused_reason,
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
    slash (mock parity), then blanks are 422 validation_error and a name
    another site has (case-insensitive) is 422 duplicate. Commits."""
    name = name.strip()
    base_url = base_url.strip().removesuffix("/")
    if not name or not base_url:
        raise err(422, "validation_error", "Name and base URL are required")
    name = await checked_name(db, Sites, name)

    site = Sites(name=name, base_url=base_url)
    db.add(site)
    await flush_name(db, Sites)
    await db.refresh(site)
    await db.commit()
    # a brand-new site has no listings/categories/checks — empty lookups
    # give site_out the right zeros without querying
    return site_out(site, {}, {}, {})


async def update_site(
    db: AsyncSession,
    site_id: int,
    name: str | None,
    base_url: str | None,
    clear_pause: bool = False,
) -> Site:
    """Edit a site; 404 unknown. Falsy fields are skipped (an empty string
    is "leave it"), values are trimmed, base_url loses one trailing slash —
    mock parity. What's left blank after trimming is 422 validation_error,
    and a name another site has (case-insensitive) is 422 duplicate. Commits.

    clear_pause is the manual lift of a circuit-breaker pause: it clears the
    error count too, because leaving it at the threshold would trip the
    breaker again on the very next failed read — a person lifting a pause is
    saying "try again properly", not "try once more". The site's waiting jobs
    are brought forward so they do not sit until a run_after that no longer
    means anything.
    """
    site = await db.get(Sites, site_id)
    if site is None:
        raise err(404, "not_found", f"Site {site_id} does not exist")

    if name:
        site.name = await checked_name(db, Sites, name, exclude_id=site.id)
    if base_url:
        base_url = base_url.strip().removesuffix("/")
        if not base_url:
            message = "Base URL is required"
            raise err(422, "validation_error", message, fields={"base_url": message})
        site.base_url = base_url
    # before clear_pause's UPDATE, whose autoflush would write the name outside it
    await flush_name(db, Sites)
    if clear_pause:
        site.paused_until = None
        site.paused_reason = None
        site.consecutive_errors = 0
        await db.execute(
            update(Jobs)
            .where(Jobs.site_id == site_id)
            .where(Jobs.status == "pending")
            .where(Jobs.reason == "paused")
            .values(run_after=datetime.now(UTC), reason="sweep")
        )
    await db.commit()

    counts = await listing_counts(db)
    category_ids = await site_category_ids(db)
    checked = await last_checked(db)
    return site_out(site, counts, category_ids, checked)


async def delete_site(db: AsyncSession, site_id: int) -> None:
    """Delete a site and everything that points at it — its category links,
    every watch's pin on it, its listings and their checks, the hunter's
    skip-log for it. Jobs on it go by their own ON DELETE CASCADE. 404
    unknown. Commits.

    A listing can't outlive its site (listings.site_id is a plain FK), so the
    site's listings are deleted with their price history, not deactivated —
    the same trade delete_category makes. A watch whose only pin was this
    site is left with none, which means it follows its category's sites
    (the rule update_item applies to an emptied subset).
    """
    site = await db.get(Sites, site_id)
    if site is None:
        raise err(404, "not_found", f"Site {site_id} does not exist")

    listing_ids = select(Listings.id).where(Listings.site_id == site_id)

    await db.execute(delete(PriceChecks).where(PriceChecks.listing_id.in_(listing_ids)))
    await db.execute(delete(Listings).where(Listings.site_id == site_id))
    await db.execute(delete(ListingChecks).where(ListingChecks.site_id == site_id))
    await db.execute(delete(WatchSites).where(WatchSites.site_id == site_id))
    await db.execute(delete(SiteCategories).where(SiteCategories.site_id == site_id))

    await db.delete(site)
    await db.commit()
