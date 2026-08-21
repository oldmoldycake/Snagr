"""Async SQLAlchemy setup: engine/session factory, ORM models for the price
tracker schema, and the query helpers the agent uses to plan its runs."""

import logging
import os
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    RowMapping,
    Text,
    UniqueConstraint,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

load_dotenv()

log = logging.getLogger(__name__)


DATABASE_URL = os.getenv("DATABASE_URL")
assert DATABASE_URL is not None, "DATABASE_URL environment varable is not set"
engine = create_async_engine(DATABASE_URL)

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=True)


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""

    pass


class User(Base):
    """Registered user; owns watches."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Sites(Base):
    """A marketplace/storefront the agent can search, keyed by base_url."""

    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Categories(Base):
    """Item category (e.g. video games, cards); links items to the sites
    that sell that kind of item via SiteCategories."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    condition_tiers: Mapped[list | None] = mapped_column(JSONB)
    price_sources: Mapped[list | None] = mapped_column(JSONB)
    pinned_sources: Mapped[list | None] = mapped_column(JSONB)


class SiteCategories(Base):
    """Join table: which categories each site carries — determines which
    sites get searched for a given item."""

    __tablename__ = "site_categories"

    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), primary_key=True)


class Items(Base):
    """Pure shared catalog entry — per-user config lives on Watches."""

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    search_aliases: Mapped[list | None] = mapped_column(JSONB)
    guide_pages: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Listings(Base):
    """Watch-scoped: match_score/match_summary are judged against the owning
    watch's criteria, so listings can't be shared across watches."""

    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    site_sku: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    match_score: Mapped[int | None] = mapped_column()
    match_summary: Mapped[str | None] = mapped_column(Text)
    signals: Mapped[dict | None] = mapped_column(JSONB)
    verdict: Mapped[str | None] = mapped_column(Text)  # auto_ok | needs_review
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("watch_id", "site_id", "url", name="uq_watch_site_url"),)


class PriceChecks(Base):
    """Point-in-time price/availability observation for a listing; a
    "sold"/"ended" status also deactivates the listing."""

    __tablename__ = "price_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"))
    price: Mapped[float | None] = mapped_column(Numeric(precision=10, scale=2))
    currency: Mapped[str] = mapped_column(Text, default="USD")
    in_stock: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MarketPrices(Base):
    """Search-sourced per-tier market stats for an item, written by the
    grounding pass."""

    __tablename__ = "market_prices"

    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)
    currency: Mapped[str] = mapped_column(Text, default="USD")
    tiers: Mapped[dict | None] = mapped_column(JSONB)
    observations: Mapped[list | None] = mapped_column(JSONB)
    confidence: Mapped[str | None] = mapped_column(Text)  # high | medium | low
    confidence_reasons: Mapped[list | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, default="insufficient")  # ok | insufficient
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Watches(Base):
    """One user's relationship to a shared item: their criteria, target price,
    and notification preferences."""

    __tablename__ = "watches"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    target_price: Mapped[float | None] = mapped_column(Numeric(precision=10, scale=2))
    expected_price: Mapped[float | None] = mapped_column(Numeric(precision=10, scale=2))
    condition_hint: Mapped[str | None] = mapped_column(Text)
    notify: Mapped[bool] = mapped_column(Boolean, default=True)
    criteria: Mapped[str | None] = mapped_column(Text)
    selection_mode: Mapped[str] = mapped_column(Text, default="cheapest")
    max_listings: Mapped[int] = mapped_column(default=3)
    allow_reproductions: Mapped[bool] = mapped_column(Boolean, default=False)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "item_id", name="uq_item_user"),)


class ListingChecks(Base):
    """Log of every listing the agent evaluated but did NOT save (poor fit,
    authenticity concerns, duplicate, etc.) so re-runs don't have to
    re-discover the same rejection from scratch and so rejections are
    auditable."""

    __tablename__ = "listing_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentRuns(Base):
    """One row per agent run — mirrors backend/app/models.py (the backend owns
    the schema, D1). Created status='queued' by the API; this agent claims and
    drives it. The nightly sweep inserts its own row so it shows in history too."""

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL = system run (schedule fire, nightly sweep, deleted owner) — visible to all
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    scope: Mapped[str] = mapped_column(Text)  # global | category | site | item
    scope_id: Mapped[int | None] = mapped_column()
    scope_label: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        Text, default="queued"
    )  # queued|running|succeeded|failed|cancelled
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stats: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    last_seq: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RunEvents(Base):
    """Ordered progress log for a run — mirrors backend/app/models.py. The API's
    /api/runs/{id}/events backfill reads these; seq is allocated by bumping
    agent_runs.last_seq under a row lock (see append_run_event)."""

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    seq: Mapped[int] = mapped_column()
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    level: Mapped[str] = mapped_column(Text)  # info|success|warn|error
    event_type: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_run_seq"),)


class RunSchedules(Base):
    """User-defined scheduled runs — mirrors backend/app/models.py (the
    backend owns the schema, D1). Recurring rows (interval_minutes set) roll
    next_due_at forward anchored when fired; one-shots (interval_minutes
    NULL) flip enabled off and keep the row."""

    __tablename__ = "run_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL = system schedule; claim_due_schedule copies this onto the run it fires
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    scope: Mapped[str] = mapped_column(Text)  # global | category | site | item
    scope_id: Mapped[int | None] = mapped_column()
    scope_label: Mapped[str] = mapped_column(Text)
    next_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    interval_minutes: Mapped[int | None] = mapped_column()  # NULL = one-shot
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


async def get_watched_item_list(
    scope: str = "global", scope_id: int | None = None
) -> Sequence[RowMapping]:
    """
    Return the (watch, site) pairs to search: one row per site for every
    watch with notify enabled, carrying that watch's own
    criteria/selection_mode/max_listings/allow_reproductions.

    Args:
      scope: A run's scope — "global" (everything), "category", "site", or
        "item"; the scoped values narrow the pairs to that target.
      scope_id: The scoped target's id; ignored for "global".
    Returns:
      A sequence of row mappings with keys watch_id, user_id, criteria,
      expected_price, condition_hint, selection_mode, max_listings,
      allow_reproductions, item_id, item_name, category_id, site_id,
      site_name, base_url. Returns an empty sequence if the query fails, so a
      DB hiccup skips this run's searches instead of crashing it.
    """
    try:
        async with AsyncSessionLocal() as session:
            stmt = (
                select(
                    Watches.id.label("watch_id"),
                    Watches.user_id.label("user_id"),
                    Watches.criteria.label("criteria"),
                    Watches.expected_price.label("expected_price"),
                    Watches.condition_hint.label("condition_hint"),
                    Watches.selection_mode.label("selection_mode"),
                    Watches.max_listings.label("max_listings"),
                    Watches.allow_reproductions.label("allow_reproductions"),
                    Items.id.label("item_id"),
                    Items.name.label("item_name"),
                    Items.category_id.label("category_id"),
                    Sites.id.label("site_id"),
                    Sites.name.label("site_name"),
                    Sites.base_url.label("base_url"),
                )
                .join(Items, Items.id == Watches.item_id)
                .join(SiteCategories, SiteCategories.category_id == Items.category_id)
                .join(Sites, Sites.id == SiteCategories.site_id)
                .where(Watches.notify)
            )
            if scope == "category":
                stmt = stmt.where(Items.category_id == scope_id)
            elif scope == "site":
                stmt = stmt.where(Sites.id == scope_id)
            elif scope == "item":
                stmt = stmt.where(Items.id == scope_id)

            results = await session.execute(stmt)
            return results.mappings().all()
    except Exception as e:
        log.error(f"Error fetching watched item list: {e}")
        return []


async def get_listed_items(
    scope: str = "global", scope_id: int | None = None
) -> Sequence[RowMapping]:
    """
    Return every active listing with its watch and item context — the set of
    already-tracked listings that need re-checking.

    Args:
      scope: A run's scope — "global" (everything), "category", "site", or
        "item"; the scoped values narrow the listings to that target.
      scope_id: The scoped target's id; ignored for "global".
    Returns:
      A sequence of row mappings with keys listing_id, listing_url, watch_id,
      user_id, site_id, site_name, item_id, item_name. Returns an empty
      sequence if the query fails, so a DB hiccup skips this run's rechecks
      instead of crashing it.
    """
    try:
        async with AsyncSessionLocal() as session:
            stmt = (
                select(
                    Listings.id.label("listing_id"),
                    Listings.url.label("listing_url"),
                    Watches.id.label("watch_id"),
                    Watches.user_id.label("user_id"),
                    Sites.id.label("site_id"),
                    Sites.name.label("site_name"),
                    Items.id.label("item_id"),
                    Items.name.label("item_name"),
                )
                .join(Sites, Sites.id == Listings.site_id)
                .join(Watches, Watches.id == Listings.watch_id)
                .join(Items, Items.id == Listings.item_id)
                .where(Listings.active)
            )
            if scope == "category":
                stmt = stmt.where(Items.category_id == scope_id)
            elif scope == "site":
                stmt = stmt.where(Listings.site_id == scope_id)
            elif scope == "item":
                stmt = stmt.where(Listings.item_id == scope_id)

            results = await session.execute(stmt)
            return results.mappings().all()
    except Exception as e:
        log.error(f"Error fetching listed items: {e}")
        return []


async def get_checked_urls(watch_id: int, site_id: int) -> Sequence[RowMapping]:
    """
    Return every listing_checks row already logged for this (watch, site)
    pair — listings previously evaluated and rejected, so a re-run can skip
    re-judging them.

    Args:
      watch_id: The internal id of the watch to look up rejections for.
      site_id: The internal id of the site to look up rejections for.
    Returns:
      A sequence of row mappings with keys url, reason, notes. Returns an
      empty sequence if the query fails, so a DB hiccup skips the skip-list
      instead of crashing the run.
    """

    log.info(f"Fetching checked urls for watch {watch_id} on site {site_id}")
    async with AsyncSessionLocal() as session:
        try:
            stmt = (
                select(
                    ListingChecks.url.label("url"),
                    ListingChecks.reason.label("reason"),
                    ListingChecks.notes.label("notes"),
                )
                .where(ListingChecks.watch_id == watch_id)
                .where(ListingChecks.site_id == site_id)
            )

            results = await session.execute(stmt)
            return results.mappings().all()
        except Exception as e:
            log.error(f"Error fetching checked urls for watch {watch_id} on site {site_id}: {e}")
            return []


async def get_category_tiers(category_id: int) -> RowMapping | None:
    """
    Return a category's name and its stored condition-tier vocabulary.

    Args:
      category_id: The internal id of the category to look up.
    Returns:
      A row mapping with keys name, condition_tiers — condition_tiers is None
      until the vocabulary has been generated for this category. Returns None
      if the category does not exist or the query fails, so grounding falls
      back to ungrouped prices instead of crashing the run.
    """

    log.info(f"Fetching condition tiers for category {category_id}")
    async with AsyncSessionLocal() as session:
        try:
            stmt = (
                select(
                    Categories.name.label("name"),
                    Categories.condition_tiers.label("condition_tiers"),
                )
                .where(Categories.id == category_id)
                .limit(1)
            )

            results = await session.execute(stmt)
            return results.mappings().one_or_none()
        except Exception as e:
            log.error(f"Error fetching condition tiers for category {category_id}: {e}")
            return None


async def set_condition_tiers(category_id: int, tiers: list[str]) -> bool:
    """
    Store a category's generated condition-tier vocabulary.

    Only call this when get_category_tiers reported condition_tiers as None:
    the vocabulary is meant to be written once and reused, because renaming a
    tier splits that tier's observations across two spellings and shrinks the
    sample counts grounding confidence is derived from.

    Args:
      category_id: The internal id of the category to write tiers for.
      tiers: The tier names, e.g. ["sealed", "graded", "cib", "loose"].
    Returns:
      True on success, False if the write failed — this run still uses the
      tiers it generated, and the next run regenerates them.
    """

    log.info(f"Saving condition tiers for category {category_id}: {tiers}")
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                update(Categories).where(Categories.id == category_id).values(condition_tiers=tiers)
            )
            await session.commit()
            return True
        except Exception as e:
            log.error(f"Error saving condition tiers for category {category_id}: {e}")
            return False


async def get_category_item_names(category_id: int, limit: int = 10) -> Sequence[str]:
    """
    Return a sample of item names in a category, as context for generating its
    condition-tier vocabulary — a category named "misc" says nothing on its
    own, but the items filed under it do.

    Args:
      category_id: The internal id of the category to sample items from.
      limit: How many names to return at most.
    Returns:
      A sequence of item names, empty if the category has no items or the
      query fails.
    """

    log.info(f"Fetching item names for category {category_id}")
    async with AsyncSessionLocal() as session:
        try:
            stmt = select(Items.name).where(Items.category_id == category_id).limit(limit)

            results = await session.execute(stmt)
            return results.scalars().all()
        except Exception as e:
            log.error(f"Error fetching item names for category {category_id}: {e}")
            return []


async def get_price_sources(category_id: int) -> RowMapping | None:
    """
    Return a category's price-source registry and its user-pinned domains.

    Args:
      category_id: The internal id of the category to look up.
    Returns:
      A row mapping with keys price_sources, pinned_sources. price_sources is
      None until source discovery has run for this category; pinned_sources is
      None unless a user hand-pinned domains — it is user-owned, so the system
      reads it here and never writes it. Returns None if the category does not
      exist or the query fails, so grounding falls back to the broad snippet
      search instead of crashing the run.
    """

    log.info(f"Fetching price sources for category {category_id}")
    async with AsyncSessionLocal() as session:
        try:
            stmt = (
                select(
                    Categories.price_sources.label("price_sources"),
                    Categories.pinned_sources.label("pinned_sources"),
                )
                .where(Categories.id == category_id)
                .limit(1)
            )

            results = await session.execute(stmt)
            return results.mappings().one_or_none()
        except Exception as e:
            log.error(f"Error fetching price sources for category {category_id}: {e}")
            return None


async def set_price_sources(category_id: int, sources: list[dict]) -> bool:
    """
    Store the system-managed price-source registry for a category.

    Writes price_sources only — pinned_sources is user-owned and the system
    never touches it. Called after a grounding pass has updated the registry
    (hit/miss counts, promotions, demotions, newly discovered candidates), so
    the stored registry always reflects the evidence gathered so far.

    Args:
      category_id: The internal id of the category to write the registry for.
      sources: The full registry, e.g.
        [{"domain": ..., "kind": ..., "status": ..., "hits": ...,
          "consecutive_misses": ..., "notes": ...}].
    Returns:
      True on success, False if the write failed — this run still uses the
      registry it built, and the next run re-learns the lost updates.
    """

    log.info(f"Saving price sources for category {category_id}: {len(sources)} entries")
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                update(Categories).where(Categories.id == category_id).values(price_sources=sources)
            )
            await session.commit()
            return True
        except Exception as e:
            log.error(f"Error saving price sources for category {category_id}: {e}")
            return False


async def get_item_grounding(item_id: int) -> RowMapping | None:
    """
    Return the grounding state stored on an item: its canonical search
    aliases and its resolved guide-page URLs.

    Args:
      item_id: The internal id of the item to look up.
    Returns:
      A row mapping with keys name, search_aliases, guide_pages —
      search_aliases is None until alias generation has run for this item;
      guide_pages is None until a site-scoped search has resolved a page.
      Returns None if the item does not exist or the query fails, so grounding
      proceeds from the item name alone instead of crashing the run.
    """

    log.info(f"Fetching grounding state for item {item_id}")
    async with AsyncSessionLocal() as session:
        try:
            stmt = (
                select(
                    Items.name.label("name"),
                    Items.search_aliases.label("search_aliases"),
                    Items.guide_pages.label("guide_pages"),
                )
                .where(Items.id == item_id)
                .limit(1)
            )

            results = await session.execute(stmt)
            return results.mappings().one_or_none()
        except Exception as e:
            log.error(f"Error fetching grounding state for item {item_id}: {e}")
            return None


async def set_guide_pages(item_id: int, pages: dict) -> bool:
    """
    Store an item's resolved guide-page URLs ({domain: url}).

    Cached after a successful site-scoped search so later groundings go
    straight to the page; the caller drops entries whose page went dead, so
    the next run searches again instead of refetching a corpse.

    Args:
      item_id: The internal id of the item the pages belong to.
      pages: Resolved page URL per source domain, e.g.
        {"pricecharting.com": "https://www.pricecharting.com/game/..."}.
    Returns:
      True on success, False if the write failed — this run already used the
      URLs it resolved, and the next run resolves them again.
    """

    log.info(f"Saving guide pages for item {item_id}: {sorted(pages)}")
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                update(Items).where(Items.id == item_id).values(guide_pages=pages)
            )
            await session.commit()
            return True
        except Exception as e:
            log.error(f"Error saving guide pages for item {item_id}: {e}")
            return False


async def get_grounding_candidates() -> Sequence[RowMapping]:
    """
    Return every watched item joined to its market-price staleness state, one
    row per item — the pool ground_stale selects this run's grounding work
    from. Any watch counts, notify on or off: notify only gates alerting, and
    market stats also serve the UI and non-notify listings. Unwatched catalog
    items are the only exclusion — nobody is asking about them.

    Returns:
      A sequence of row mappings with keys item_id, item_name, category_id,
      as_of, last_attempt_at — the market_prices columns are None for items
      never grounded. Returns an empty sequence if the query fails, so a DB
      hiccup skips grounding this run instead of crashing it.
    """

    log.info("Fetching grounding candidates")
    async with AsyncSessionLocal() as session:
        try:
            stmt = (
                select(
                    Items.id.label("item_id"),
                    Items.name.label("item_name"),
                    Items.category_id.label("category_id"),
                    MarketPrices.as_of.label("as_of"),
                    MarketPrices.last_attempt_at.label("last_attempt_at"),
                )
                .join(Watches, Watches.item_id == Items.id)
                .outerjoin(MarketPrices, MarketPrices.item_id == Items.id)
                .distinct()
            )

            results = await session.execute(stmt)
            return results.mappings().all()
        except Exception as e:
            log.error(f"Error fetching grounding candidates: {e}")
            return []


async def get_market_price(item_id: int) -> RowMapping | None:
    """
    Return an item's stored market stats, for prompt context.

    Args:
      item_id: The internal id of the item to look up.
    Returns:
      A row mapping with keys currency, tiers, confidence, status, as_of —
      exactly what market_price_block consumes. The observations audit trail
      stays in the DB: it is for explaining stats after the fact, not for
      shipping into a prompt. Returns None if the item has never been
      grounded or the query fails, so the prompt says "no market data"
      instead of crashing the run.
    """

    log.info(f"Fetching market price for item {item_id}")
    async with AsyncSessionLocal() as session:
        try:
            stmt = (
                select(
                    MarketPrices.currency.label("currency"),
                    MarketPrices.tiers.label("tiers"),
                    MarketPrices.confidence.label("confidence"),
                    MarketPrices.status.label("status"),
                    MarketPrices.as_of.label("as_of"),
                )
                .where(MarketPrices.item_id == item_id)
                .limit(1)
            )

            results = await session.execute(stmt)
            return results.mappings().one_or_none()
        except Exception as e:
            log.error(f"Error fetching market price for item {item_id}: {e}")
            return None


async def upsert_market_price(
    item_id: int,
    *,
    currency: str,
    tiers: dict,
    observations: list,
    confidence: str | None,
    confidence_reasons: list,
    status: str,
) -> bool:
    """
    Write one grounding result to market_prices (one row per item).

    An "insufficient" result never evicts stored "ok" stats: the existing row
    only gets last_attempt_at touched, so the good data keeps being served
    while the failed attempt still drives backoff. as_of moves only on an "ok"
    grounding — it is the staleness mark later runs gate their TTL on.

    Args:
      item_id: The internal id of the item these stats are for.
      currency: The one currency every stat was built from, e.g. "USD".
      tiers: Reportable per-tier stats, prices as decimal strings.
      observations: Every verified observation — the audit trail every stat
        must be explainable from.
      confidence: "high" | "medium" | "low".
      confidence_reasons: The demotions that produced that confidence.
      status: "ok" | "insufficient".
    Returns:
      True on success, False if the write failed — grounding carries on and
      the next attempt rewrites the same row.
    """

    log.info(f"Upserting market price for item {item_id}: status={status}")
    async with AsyncSessionLocal() as session:
        try:
            now = datetime.now(UTC)
            row = await session.get(MarketPrices, item_id)

            if row and row.status == "ok" and status != "ok":
                row.last_attempt_at = now
            elif row:
                row.currency = currency
                row.tiers = tiers
                row.observations = observations
                row.confidence = confidence
                row.confidence_reasons = confidence_reasons
                row.status = status
                row.last_attempt_at = now
                if status == "ok":
                    row.as_of = now
            else:
                session.add(
                    MarketPrices(
                        item_id=item_id,
                        currency=currency,
                        tiers=tiers,
                        observations=observations,
                        confidence=confidence,
                        confidence_reasons=confidence_reasons,
                        status=status,
                        as_of=now if status == "ok" else None,
                        last_attempt_at=now,
                    )
                )

            await session.commit()
            return True
        except Exception as e:
            log.error(f"Error upserting market price for item {item_id}: {e}")
            return False


async def claim_queued_run() -> dict | None:
    """
    Claim the oldest queued agent_runs row: flip it to running, stamp
    started_at, and return it as a plain dict with keys id, scope, scope_id,
    scope_label (captured before commit — sessions here expire on commit).
    SKIP LOCKED makes concurrent consumer ticks safe: at most one claims a
    given row. Returns None when the queue is empty.

    Unlike the read helpers above, a failure here PROPAGATES: a swallowed
    claim failure would strand a queued run invisibly, whereas the read
    helpers' empty default merely skips optional work.
    """
    log.info("Claiming a queued run")
    async with AsyncSessionLocal() as session:
        stmt = (
            select(AgentRuns)
            .where(AgentRuns.status == "queued")
            .order_by(AgentRuns.created_at, AgentRuns.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        run = (await session.execute(stmt)).scalar_one_or_none()
        if run is None:
            return None

        run.status = "running"
        run.started_at = datetime.now(UTC)
        claimed = {
            "id": run.id,
            "scope": run.scope,
            "scope_id": run.scope_id,
            "scope_label": run.scope_label,
        }
        await session.commit()
        log.info(f"Claimed run {claimed['id']} ({claimed['scope_label']})")
        return claimed


def roll_forward(due_at: datetime, interval_minutes: int, now: datetime) -> datetime:
    """First due_at + k*interval (k >= 1) strictly after now. Anchored: steps
    from the original due time, so "daily at 02:00" stays at 02:00 after
    downtime, and missed periods collapse into the one fire that just happened."""
    step = timedelta(minutes=interval_minutes)
    return due_at + max((now - due_at) // step + 1, 1) * step


async def claim_due_schedule() -> dict | None:
    """
    Fire the most-overdue due schedule, if the instance is free: insert a
    running agent_runs row carrying the schedule's scope, stamp
    last_fired_at, and roll next_due_at forward (recurring) or flip enabled
    off (one-shot) — all in one transaction, so a crash can't fire twice or
    roll without firing. Returns the same dict claim_queued_run does, plus
    "scheduled": True, or None when nothing is due or a run is already
    queued/running (a busy skip rolls back, leaving the schedule due for the
    next free tick — a one-shot drop fires late-but-once).

    The API can enqueue a run between this transaction's active-run check
    and its commit; the queued row then just waits behind the scheduled run,
    exactly like clicking Run during the nightly sweep. Failures PROPAGATE
    like claim_queued_run's — a swallowed failure would silently stop every
    schedule.
    """
    async with AsyncSessionLocal() as session:
        now = datetime.now(UTC)
        stmt = (
            select(RunSchedules)
            .where(RunSchedules.enabled)
            .where(RunSchedules.next_due_at <= now)
            .order_by(RunSchedules.next_due_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        schedule = (await session.execute(stmt)).scalar_one_or_none()
        if schedule is None:
            return None

        active = (
            await session.execute(
                select(AgentRuns.id).where(AgentRuns.status.in_(("queued", "running"))).limit(1)
            )
        ).scalar_one_or_none()
        if active is not None:
            log.info(f"Schedule {schedule.id} due but run {active} is active; skipping this tick")
            return None

        run = AgentRuns(
            user_id=schedule.user_id,
            scope=schedule.scope,
            scope_id=schedule.scope_id,
            scope_label=schedule.scope_label,
            status="running",
            started_at=now,
        )
        session.add(run)
        await session.flush()

        schedule.last_fired_at = now
        if schedule.interval_minutes is not None:
            schedule.next_due_at = roll_forward(
                schedule.next_due_at, schedule.interval_minutes, now
            )
        else:
            schedule.enabled = False

        claimed = {
            "id": run.id,
            "scope": run.scope,
            "scope_id": run.scope_id,
            "scope_label": run.scope_label,
            "scheduled": True,
        }
        await session.commit()
        log.info(f"Fired schedule for run {claimed['id']} ({claimed['scope_label']})")
        return claimed


async def create_global_run() -> dict:
    """
    Insert the row a scheduled sweep records itself under: a global-scope run
    born running (nothing enqueued it, so it never has a queued phase).
    Returns the same dict shape claim_queued_run does. Failures propagate —
    an unrecorded sweep would be invisible in run history.
    """
    log.info("Recording a global sweep run")
    async with AsyncSessionLocal() as session:
        run = AgentRuns(
            scope="global",
            scope_id=None,
            scope_label="Everything",
            status="running",
            started_at=datetime.now(UTC),
        )
        session.add(run)
        await session.flush()
        created = {"id": run.id, "scope": "global", "scope_id": None, "scope_label": "Everything"}
        await session.commit()
        return created


async def get_run_status(run_id: int) -> str | None:
    """
    Return a run's current status — the cooperative-cancellation poll read
    between units of work. Returns None if the run is missing or the query
    fails; None means "keep going", because a DB hiccup mid-run must not
    kill the run (only an explicit 'cancelled' aborts it).
    """
    async with AsyncSessionLocal() as session:
        try:
            stmt = select(AgentRuns.status).where(AgentRuns.id == run_id)
            return (await session.execute(stmt)).scalar_one_or_none()
        except Exception as e:
            log.error(f"Error fetching status for run {run_id}: {e}")
            return None


async def append_run_event(
    run_id: int, level: str, event_type: str, message: str, payload: dict | None = None
) -> int | None:
    """
    Append one progress event to a run's log and return its seq.

    seq comes from bumping agent_runs.last_seq under SELECT ... FOR UPDATE —
    the same discipline the API's cancel_run uses — so concurrent writers
    never collide on uq_run_seq; deriving seq from MAX(seq)+1 unlocked would.
    Returns None if the run is missing or the write fails: progress events
    are best-effort and must never take the run down.
    """
    async with AsyncSessionLocal() as session:
        try:
            run = await session.get(AgentRuns, run_id, with_for_update=True)
            if run is None:
                log.error(f"Cannot append event to unknown run {run_id}")
                return None

            run.last_seq += 1
            seq = run.last_seq
            session.add(
                RunEvents(
                    run_id=run_id,
                    seq=seq,
                    ts=datetime.now(UTC),
                    level=level,
                    event_type=event_type,
                    message=message,
                    payload=payload,
                )
            )
            await session.commit()
            return seq
        except Exception as e:
            log.error(f"Error appending event to run {run_id}: {e}")
            return None


async def finish_run(
    run_id: int, status: str, stats: dict | None = None, error: str | None = None
) -> bool:
    """
    Write a run's terminal state ("succeeded" or "failed") plus its terminal
    run_finished event, in one locked transaction.

    If the row is already 'cancelled', the API wrote the terminal state while
    this run was finishing — leave it untouched and return False (the row
    lock makes the check atomic against cancel_run). Returns False on any
    failure too, logged loudly: the row is then stuck 'running' until a
    future cleanup (no reaper exists yet).
    """
    log.info(f"Finishing run {run_id} as {status}")
    async with AsyncSessionLocal() as session:
        try:
            run = await session.get(AgentRuns, run_id, with_for_update=True)
            if run is None:
                log.error(f"Cannot finish unknown run {run_id}")
                return False
            if run.status == "cancelled":
                log.info(f"Run {run_id} was cancelled; keeping the API's terminal state")
                return False

            now = datetime.now(UTC)
            run.status = status
            run.finished_at = now
            run.stats = stats
            run.error = error
            run.last_seq += 1
            if status == "succeeded":
                level = "success"
                message = (
                    f"Run complete — {stats['listings_checked']} checked, "
                    f"{stats['prices_found']} prices, {stats['new_listings']} new listings, "
                    f"{stats['errors']} errors"
                )
            else:
                level = "error"
                message = f"Run failed: {error}"
            session.add(
                RunEvents(
                    run_id=run_id,
                    seq=run.last_seq,
                    ts=now,
                    level=level,
                    event_type="run_finished",
                    message=message,
                    payload=None,
                )
            )
            await session.commit()
            return True
        except Exception as e:
            log.error(f"Error finishing run {run_id}: {e}")
            return False
