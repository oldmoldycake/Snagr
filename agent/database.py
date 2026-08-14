"""Async SQLAlchemy setup: engine/session factory, ORM models for the price
tracker schema, and the query helpers the agent uses to plan its runs."""

import logging
import os
from collections.abc import Sequence
from datetime import UTC, datetime

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


class JobRuns(Base):
    """One row per scraper job execution, for run history and error counts."""

    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sites_checked: Mapped[int] = mapped_column(default=0)
    errors: Mapped[int] = mapped_column(default=0)


async def get_watched_item_list() -> Sequence[RowMapping]:
    """
    Return the (watch, site) pairs to search: one row per site for every
    watch with notify enabled, carrying that watch's own
    criteria/selection_mode/max_listings/allow_reproductions.

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

            results = await session.execute(stmt)
            return results.mappings().all()
    except Exception as e:
        log.error(f"Error fetching watched item list: {e}")
        return []


async def get_listed_items() -> Sequence[RowMapping]:
    """
    Return every active listing with its watch and item context — the set of
    already-tracked listings that need re-checking.

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
