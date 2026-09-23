"""The item <-> watch <-> watch_sites mapping — the one genuinely fiddly bit
of CRUD in the backend, so it gets its own module and keeps routers/items.py
thin.

An API "item" is three tables: the shared items row, the caller's watches row
(target, criteria, selection mode, slots…) and their watch_sites subset, so
everything here is scoped to one user's watches. The REST router and the MCP
tools are the two callers and must agree — which is why the serializers live
here rather than in either of them.

Reads: build_item_summary, load_listings / listing_out, watch_or_404,
list_items, get_item_detail, list_listings, list_price_checks.
Writes: create_item, update_item, delete_item, update_watch, update_listing.
"""

from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import err
from app.models import (
    Categories,
    Items,
    ListingChecks,
    Listings,
    PriceChecks,
    Sites,
    Watches,
    WatchSites,
)
from app.schemas.common import PageMeta, Paginated
from app.schemas.items import (
    ItemCreateRequest,
    ItemDetail,
    ItemListParams,
    ItemSummary,
    ItemUpdateRequest,
    Listing,
    ListingRow,
    PriceCheck,
    Watch,
    WatchUpdateRequest,
)
from app.schemas.vision import AuthenticityRead
from app.services import jobs as jobs_service
from app.services.aggregates import item_rollups
from app.services.vision import authenticity_for_listings

# A day: past it a price stops being tracked in any sense the item page means.
MAX_RECHECK_INTERVAL_MINUTES = 1440

# --- serializers --------------------------------------------------------------


async def build_item_summary(
    watch: Watches, item: Items, category: Categories, db: AsyncSession, range: str = "30d"
) -> ItemSummary:
    """One (watch, item, category) row -> ItemSummary. Stored/joined fields
    come from the rows; the price rollups (best/avg/target/pct/spark) from
    services.aggregates.item_rollups over `range`."""
    # site_ids = the watch's chosen subset; no rows means "all category sites" (null)
    site_ids = (
        (await db.execute(select(WatchSites.site_id).where(WatchSites.watch_id == watch.id)))
        .scalars()
        .all()
    )

    # prices are decimal STRINGS, never floats/0; null for unknown
    target_price = str(watch.target_price) if watch.target_price is not None else None

    return ItemSummary(
        id=item.id,
        name=item.name,
        category_id=category.id,
        category_name=category.name,
        category_slug=category.slug,
        target_price=target_price,
        currency="USD",
        criteria=watch.criteria,
        selection_mode=watch.selection_mode,
        max_listings=watch.max_listings,
        allow_reproductions=watch.allow_reproductions,
        recheck_interval_minutes=watch.recheck_interval_minutes,
        hunt=watch.hunt,
        site_ids=list(site_ids) or None,
        **await item_rollups(db, watch.user_id, item, watch, range),
        created_at=item.created_at.isoformat(),
        watch=Watch(id=watch.id, notify=watch.notify, target_price=target_price),
    )


async def listing_latest_check(
    listing_id: int, db: AsyncSession
) -> tuple[str | None, bool | None, str | None, str | None]:
    """Latest price/status observations for one listing.

    Two different "latest" rows, matching the contract (see mocks/serializers.ts):
      - price/in_stock come from the newest check THAT HAS A PRICE
      - status/checked_at come from the newest check of ANY kind, so a sold/ended
        listing still reports its terminal status and when we saw it.

    Returns (price, in_stock, status, checked_at) — all None-safe, price as a
    decimal string and checked_at as ISO-8601.

    NOTE: 2 queries per listing (N+1) — acceptable at household listing counts;
    batch it through services/aggregates.py if that stops being true.
    """
    # the listing's current price: believed readings only, like every other
    # price on the site. last_checked_at below is deliberately NOT filtered —
    # a disbelieved reading is still a check that happened.
    priced_stmt = (
        select(PriceChecks.price, PriceChecks.in_stock)
        .where(PriceChecks.price.isnot(None))
        .where(PriceChecks.confirmed)
        .where(PriceChecks.listing_id == listing_id)
        .order_by(PriceChecks.checked_at.desc())
        .limit(1)
    )
    with_price_check = (await db.execute(priced_stmt)).first()

    latest_stmt = (
        select(PriceChecks.status, PriceChecks.checked_at)
        .where(PriceChecks.listing_id == listing_id)
        .order_by(PriceChecks.checked_at.desc())
        .limit(1)
    )
    general_latest = (await db.execute(latest_stmt)).first()

    price = str(with_price_check.price) if with_price_check is not None else None
    in_stock = with_price_check.in_stock if with_price_check is not None else None
    status = general_latest.status if general_latest is not None else None
    checked_at = general_latest.checked_at.isoformat() if general_latest is not None else None
    return price, in_stock, status, checked_at


async def listing_out(
    db: AsyncSession,
    listing: Listings,
    site_name: str,
    authenticity: dict[str, AuthenticityRead],
) -> Listing:
    """One listings row -> the contract's Listing shape. `authenticity` is the
    owning watch's batch from services.vision.authenticity_for_listings,
    keyed by listing URL (absent = never scanned)."""
    price, in_stock, latest_status, checked_at = await listing_latest_check(listing.id, db)
    return Listing(
        id=listing.id,
        site_id=listing.site_id,
        site_name=site_name,
        url=listing.url,
        title=listing.title,
        site_sku=listing.site_sku,
        active=listing.active,
        latest_price=price,
        in_stock=in_stock,
        latest_status=latest_status,
        match_score=listing.match_score,
        match_summary=listing.match_summary,
        authenticity=authenticity.get(listing.url),
        last_checked_at=checked_at,
        created_at=listing.created_at.isoformat(),
        discovered_by_job_id=listing.discovered_by_job_id,
    )


async def load_listings(db: AsyncSession, watch: Watches) -> list[Listing]:
    """Every listing of one watch, oldest first — the ItemDetail.listings block."""
    listing_stmt = (
        select(Listings, Sites.name)
        .join(Sites, Sites.id == Listings.site_id)
        .where(Listings.watch_id == watch.id)
        .order_by(Listings.created_at)
    )
    listing_rows = (await db.execute(listing_stmt)).all()
    authenticity = await authenticity_for_listings(
        db, watch.id, [listing.url for listing, _ in listing_rows]
    )
    return [
        await listing_out(db, listing, site_name, authenticity)
        for listing, site_name in listing_rows
    ]


# --- reads --------------------------------------------------------------------


async def watch_or_404(db: AsyncSession, user_id: int, item_id: int) -> Watches:
    """The caller's watch for an item, or 404.

    An API "item" only exists for a user through their watch, so "no watch" and
    "no such item" are the same 404 to the caller — hence the item-shaped
    message. The chart endpoints need the watch anyway, for target_price.
    """
    stmt = select(Watches).where(Watches.user_id == user_id).where(Watches.item_id == item_id)
    watch = (await db.execute(stmt)).scalar_one_or_none()
    if watch is None:
        raise err(404, "not_found", f"Item {item_id} does not exist")
    return watch


async def list_items(
    db: AsyncSession, user_id: int, filters: ItemListParams
) -> Paginated[ItemSummary]:
    """The caller's watches as ItemSummary rows, filtered, searched and paged."""
    page = filters.page or 1
    per_page = filters.per_page or 50

    stmt = (
        select(Watches, Items, Categories)
        .join(Items, Items.id == Watches.item_id)
        .join(Categories, Categories.id == Items.category_id)
        .where(Watches.user_id == user_id)
    )
    if filters.category_id is not None:
        stmt = stmt.where(Items.category_id == filters.category_id)
    if filters.search:
        stmt = stmt.where(Items.name.ilike(f"%{filters.search}%"))
    if filters.site_id is not None:
        # only items with an active tracked listing on this site
        stmt = stmt.where(
            select(Listings.id)
            .where(Listings.watch_id == Watches.id)
            .where(Listings.site_id == filters.site_id)
            .where(Listings.active.is_(True))
            .exists()
        )

    rows = (await db.execute(stmt.order_by(Items.name))).all()
    summaries = [
        await build_item_summary(w, i, c, db, filters.range or "30d") for (w, i, c) in rows
    ]

    # status filter runs AFTER serialize — it reads the computed fields
    if filters.status == "snagged":
        summaries = [s for s in summaries if s.target_met]
    elif filters.status == "above_target":
        summaries = [s for s in summaries if not s.target_met and s.active_listing_count > 0]
    elif filters.status == "no_listings":
        summaries = [s for s in summaries if s.active_listing_count == 0]

    total = len(summaries)
    start = (page - 1) * per_page
    summaries = summaries[start : start + per_page]

    return Paginated(
        data=summaries,
        meta=PageMeta(page=page, per_page=per_page, total=total),
    )


async def get_item_detail(db: AsyncSession, user_id: int, item_id: int) -> ItemDetail:
    """ItemSummary plus every listing of the caller's watch; 404 when unwatched."""
    stmt = (
        select(Watches, Items, Categories)
        .join(Items, Items.id == Watches.item_id)
        .join(Categories, Categories.id == Items.category_id)
        .where(Watches.item_id == item_id, Watches.user_id == user_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise err(404, "not_found", f"Item {item_id} does not exist")

    watch, item, category = row
    return await build_item_detail(db, watch, item, category)


async def build_item_detail(
    db: AsyncSession, watch: Watches, item: Items, category: Categories
) -> ItemDetail:
    """ItemSummary plus the listings and the two facts objects the item page's
    mono line reads — both computed from the watch's jobs, never stored."""
    summary = await build_item_summary(watch, item, category, db)
    return ItemDetail(
        # the summary's `hunt` boolean becomes the facts object's `enabled`
        **summary.model_dump(exclude={"hunt"}),
        listings=await load_listings(db, watch),
        hunt=await jobs_service.hunt_facts(db, watch),
        recheck=await jobs_service.recheck_facts(db, watch),
    )


async def list_listings(
    db: AsyncSession,
    user_id: int,
    item_id: int | None = None,
    site_id: int | None = None,
    active: bool | None = True,
    page: int = 1,
    per_page: int = 25,
) -> Paginated[ListingRow]:
    """Every listing across the caller's watches, newest first — the one read
    REST has no route for (the UI only shows listings inside an item).
    `active=None` includes sold/ended listings."""
    stmt = (
        select(Listings, Sites.name.label("site_name"), Items.name.label("item_name"))
        .join(Sites, Sites.id == Listings.site_id)
        .join(Items, Items.id == Listings.item_id)
        .join(Watches, Watches.id == Listings.watch_id)
        .where(Watches.user_id == user_id)
    )
    if item_id is not None:
        stmt = stmt.where(Listings.item_id == item_id)
    if site_id is not None:
        stmt = stmt.where(Listings.site_id == site_id)
    if active is not None:
        stmt = stmt.where(Listings.active.is_(active))

    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(Listings.created_at.desc(), Listings.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).all()

    # authenticity scans are keyed per watch, so batch the lookups per watch
    urls_by_watch: dict[int, list[str]] = {}
    for listing, _, _ in rows:
        urls_by_watch.setdefault(listing.watch_id, []).append(listing.url)
    authenticity = {
        watch_id: await authenticity_for_listings(db, watch_id, urls)
        for watch_id, urls in urls_by_watch.items()
    }

    data = []
    for listing, site_name, item_name in rows:
        base = await listing_out(db, listing, site_name, authenticity[listing.watch_id])
        data.append(ListingRow(**base.model_dump(), item_id=listing.item_id, item_name=item_name))
    return Paginated(data=data, meta=PageMeta(page=page, per_page=per_page, total=total))


async def list_price_checks(
    db: AsyncSession, user_id: int, item_id: int, limit: int
) -> list[PriceCheck]:
    """Recent raw price checks across the caller's listings of one item,
    newest first. An unwatched item is simply an empty list.

    Unconfirmed readings are INCLUDED here, unlike everywhere else: this is
    the log of what was actually seen, and hiding an observation is its own
    failure. Each row carries `confirmed` so the UI can show it as the
    disbelieved reading it is."""
    # join through Watches so a caller only ever sees their OWN listings' checks
    stmt = (
        select(
            PriceChecks.id.label("price_check_id"),
            Listings.id.label("listing_id"),
            Sites.name.label("site_name"),
            PriceChecks.price.label("price"),
            PriceChecks.currency.label("currency"),
            PriceChecks.in_stock.label("in_stock"),
            PriceChecks.status.label("status"),
            PriceChecks.method.label("method"),
            PriceChecks.confirmed.label("confirmed"),
            PriceChecks.checked_at.label("checked_at"),
        )
        .join(Listings, Listings.id == PriceChecks.listing_id)
        .join(Sites, Sites.id == Listings.site_id)
        .join(Watches, Watches.id == Listings.watch_id)
        .where(Listings.item_id == item_id)
        .where(Watches.user_id == user_id)
        .order_by(PriceChecks.checked_at.desc())
        .limit(limit)
    )

    # .all(), NOT .scalars().all() — this is a multi-column select
    return [
        PriceCheck(
            id=row.price_check_id,
            listing_id=row.listing_id,
            site_name=row.site_name,
            price=str(row.price) if row.price is not None else None,
            currency=row.currency,
            in_stock=row.in_stock,
            status=row.status,
            method=row.method,
            confirmed=row.confirmed,
            checked_at=row.checked_at.isoformat(),
        )
        for row in (await db.execute(stmt)).all()
    ]


# --- writes -------------------------------------------------------------------


def _check_interval(minutes: int | None) -> None:
    """422 unless null (the instance default) or between the floor and a day.
    The floor is the agent's RECHECK_INTERVAL_FLOOR_MINUTES, set in both env
    files; the agent floors again when it schedules, so this is the polite
    half."""
    floor = settings.RECHECK_INTERVAL_FLOOR_MINUTES
    if minutes is not None and not floor <= minutes <= MAX_RECHECK_INTERVAL_MINUTES:
        bounds = f"between {floor} and {MAX_RECHECK_INTERVAL_MINUTES} minutes"
        raise err(
            422,
            "validation_error",
            f"Check interval must be {bounds}",
            fields={"recheck_interval_minutes": f"Must be {bounds}"},
        )


async def create_item(db: AsyncSession, user_id: int, body: ItemCreateRequest) -> ItemSummary:
    """Find-or-create the shared items row, create the caller's watch, insert
    the watch_sites subset. Commits.

    The contract's 404 for an unknown category and the 422s (selection_mode,
    max_listings 1-10, site_ids ⊆ the category's sites) are not enforced yet —
    an unknown category surfaces as the FK violation's 503. The
    recheck_interval_minutes range (the floor to 1440) is enforced.
    """
    _check_interval(body.recheck_interval_minutes)
    stmt = select(Items).where(Items.name == body.name).where(Items.category_id == body.category_id)
    item = (await db.execute(stmt)).scalar_one_or_none()

    if item is None:
        item = Items(name=body.name, category_id=body.category_id)
        db.add(item)
        await db.flush()
        await db.refresh(item)

    watch = Watches(
        user_id=user_id,
        item_id=item.id,
        target_price=Decimal(body.target_price) if body.target_price is not None else None,
        criteria=body.criteria,
        max_listings=body.max_listings,
        selection_mode=body.selection_mode,
        allow_reproductions=body.allow_reproductions,
        recheck_interval_minutes=body.recheck_interval_minutes,
        hunt=body.hunt,
    )
    db.add(watch)
    await db.flush()
    await db.refresh(watch)

    for site_id in body.site_ids or []:
        watch_sites = WatchSites(watch_id=watch.id, site_id=site_id)
        db.add(watch_sites)
        await db.flush()
        await db.refresh(watch_sites)

    # The hunter starts on this watch in the same transaction that creates it:
    # a hunt per site it will search, plus the market-price grounding the hunt
    # prompts read from. Same transaction because a watch with no hunts is a
    # watch nothing will ever look for — the two facts belong together. Unless
    # hunting is off, for the watch ("only when you press Hunt now") or for
    # the instance (the agent's sweep picks it up when the switch is back on).
    if watch.hunt and settings.HUNT_ENABLED:
        await jobs_service.enqueue_hunts_for_watch(db, watch, user_id=user_id, reason="created")
    await jobs_service.enqueue_ground(db, item.id, user_id=user_id)

    await db.commit()

    category = await db.get(Categories, item.category_id)
    return await build_item_summary(watch, item, category, db)


async def update_item(
    db: AsyncSession, user_id: int, item_id: int, body: ItemUpdateRequest
) -> ItemDetail:
    """Write item fields to items and watch fields to the caller's watch;
    404 when unwatched. Only fields that are not null change (a JSON null
    can't clear anything) — except recheck_interval_minutes, where a sent
    null means "back to the instance default"; site_ids is accepted but not
    applied yet. Commits."""
    _check_interval(body.recheck_interval_minutes)
    stmt = (
        select(Items, Watches, Categories)
        .join(Watches, Items.id == Watches.item_id)
        .join(Categories, Categories.id == Items.category_id)
        .where(Items.id == item_id)
        .where(Watches.user_id == user_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise err(404, "not_found", f"Item {item_id} does not exist")

    item, watch, category = row
    room_before, hunting_before = watch.max_listings, watch.hunt
    if body.name is not None:
        item.name = body.name
    if body.target_price is not None:
        watch.target_price = Decimal(body.target_price)
    if body.criteria is not None:
        watch.criteria = body.criteria
    if body.selection_mode is not None:
        watch.selection_mode = body.selection_mode
    if body.max_listings is not None:
        watch.max_listings = body.max_listings
    if body.allow_reproductions is not None:
        watch.allow_reproductions = body.allow_reproductions
    if "recheck_interval_minutes" in body.model_fields_set:
        watch.recheck_interval_minutes = body.recheck_interval_minutes
        await jobs_service.pull_rechecks_forward(db, watch)
    if body.hunt is not None:
        if watch.hunt and not body.hunt:
            await jobs_service.cancel_waiting_hunts(db, watch)
        watch.hunt = body.hunt
    # more room, or hunting back on, is a reason to look now rather than at
    # the agent's next hourly sweep
    if watch.hunt and (not hunting_before or watch.max_listings > room_before):
        await jobs_service.wake_hunts(db, watch, reason="sweep")

    await db.commit()
    return await build_item_detail(db, watch, item, category)


async def delete_item(db: AsyncSession, user_id: int, item_id: int) -> None:
    """Remove the caller's watch and everything hanging off it (listings,
    checks, site subset); the shared items row stays for other watchers.
    404 when unwatched. Commits."""
    watch = (
        await db.execute(
            select(Watches).where(Watches.item_id == item_id, Watches.user_id == user_id)
        )
    ).scalar_one_or_none()
    if watch is None:
        raise err(404, "not_found", f"Item {item_id} does not exist")
    listing_ids = select(Listings.id).where(Listings.watch_id == watch.id)

    await db.execute(delete(ListingChecks).where(ListingChecks.watch_id == watch.id))
    await db.execute(delete(PriceChecks).where(PriceChecks.listing_id.in_(listing_ids)))
    await db.execute(delete(Listings).where(Listings.watch_id == watch.id))
    await db.execute(delete(WatchSites).where(WatchSites.watch_id == watch.id))
    await db.execute(delete(Watches).where(Watches.id == watch.id))

    await db.commit()


async def update_watch(
    db: AsyncSession, user_id: int, item_id: int, body: WatchUpdateRequest
) -> Watch:
    """The notify toggle and the per-user target override; 404 when unwatched. Commits."""
    stmt = select(Watches).where(Watches.item_id == item_id).where(Watches.user_id == user_id)
    # scalar_one_or_none() -> the Watches ENTITY (tracked), not a Row
    watch = (await db.execute(stmt)).scalar_one_or_none()
    if watch is None:
        raise err(404, "not_found", f"Watch for item {item_id} does not exist")

    if body.notify is not None:
        watch.notify = body.notify
    if body.target_price is not None:
        watch.target_price = Decimal(body.target_price)

    await db.commit()
    return Watch(
        id=watch.id,
        notify=watch.notify,
        target_price=str(watch.target_price) if watch.target_price is not None else None,
    )


async def update_listing(db: AsyncSession, user_id: int, listing_id: int, active: bool) -> Listing:
    """Stop tracking (or resume) one of the caller's listings; 404 for
    another user's listing, like a missing one. Commits."""
    listing = (
        await db.execute(
            select(Listings)
            .join(Watches, Watches.id == Listings.watch_id)
            .where(Listings.id == listing_id, Watches.user_id == user_id)
        )
    ).scalar_one_or_none()
    if listing is None:
        raise err(404, "not_found", f"Listing {listing_id} does not exist")

    listing.active = active
    # the user's own switch; a listing tracked again has no reason to be off
    listing.inactive_reason = None if active else "untracked"
    # tracking and the queue move together: an untracked listing is not
    # re-read, and tracking one again puts it back in the rotation — and the
    # slot it held wakes the watch's hunts
    if active:
        await jobs_service.enqueue_recheck(db, listing)
    else:
        await jobs_service.cancel_recheck(db, listing.id)
        await jobs_service.wake_hunts(db, await db.get(Watches, listing.watch_id))
    await db.commit()

    site_name = (
        await db.execute(select(Sites.name).where(Sites.id == listing.site_id))
    ).scalar_one_or_none()
    authenticity = await authenticity_for_listings(db, listing.watch_id, [listing.url])
    return await listing_out(db, listing, site_name, authenticity)
