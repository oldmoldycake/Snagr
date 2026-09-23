"""Async SQLAlchemy setup: engine/session factory, ORM models for the price
tracker schema, and the query helpers the hunter uses to plan its work.

The models are a column-compatible subset of backend/app/models.py, which owns
the canonical schema and every migration (D1): new columns go through an
Alembic revision there, and Base.metadata.create_all() must never be run from
here against the live DB."""

import logging
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal, get_args

from dotenv import load_dotenv
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    RowMapping,
    Text,
    UniqueConstraint,
    func,
    or_,
    select,
    text,
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
    # false = an admin deactivated the account; its watches are not hunted on
    # their own (jobs._huntable_pairs)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Sites(Base):
    """A marketplace/storefront the agent can search, keyed by base_url.

    The pause columns are the circuit breaker (agent/breaker.py): consecutive
    read errors, and the pause they trip. While a site is paused its jobs are
    not claimed and no LLM reads it."""

    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    consecutive_errors: Mapped[int] = mapped_column(default=0, server_default=text("0"))
    paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_reason: Mapped[str | None] = mapped_column(Text)
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
    # Where this listing's price lives on its page, learned by code at the
    # moment the LLM confirms a price and replayed on every later recheck
    # (agent/locators.py). kind is jsonld|meta|microdata|css. locator_failures
    # counts reads that came back empty since the last verify — past
    # LOCATOR_MAX_FAILURES the locator is cleared and the next LLM read learns
    # a fresh one. static_ok means the same locator reads the same price out
    # of the raw HTML, so rechecks need no browser at all.
    price_locator: Mapped[str | None] = mapped_column(Text)
    locator_kind: Mapped[str | None] = mapped_column(Text)
    locator_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locator_failures: Mapped[int] = mapped_column(default=0, server_default="0")
    static_ok: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    # the hunt job that saved this listing (jobs.id); NULL for rows older than jobs
    # use_alter because jobs.listing_id points back here: the two tables
    # reference each other, so one constraint has to be added after both exist
    discovered_by_job_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("jobs.id", ondelete="SET NULL", use_alter=True, name="fk_listings_job"),
    )
    # sold | ended | auction | replaced | untracked; null while active
    inactive_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("watch_id", "site_id", "url", name="uq_watch_site_url"),)


# The reasons the hunter ends a listing with, stored as listings.inactive_reason.
# 'replaced' and 'untracked' are the other two the column's CHECK allows,
# written by swap hunts and by the user.
DisableReason = Literal["sold", "ended", "auction"]
DISABLE_REASONS: tuple[str, ...] = get_args(DisableReason)


class PriceChecks(Base):
    """Point-in-time price/availability observation for a listing. A
    "sold"/"ended" status does not itself deactivate the listing — the agent is
    instructed to follow the check with disable_listing (tools.py)."""

    __tablename__ = "price_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listings.id"))
    price: Mapped[float | None] = mapped_column(Numeric(precision=10, scale=2))
    currency: Mapped[str] = mapped_column(Text, default="USD")
    in_stock: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str | None] = mapped_column(Text)
    # How the price was read: llm (the model looked at the page) or one of
    # jsonld|meta|microdata|locator (code replayed the listing's locator).
    # confirmed is false for a reading the plausibility bands rejected: kept
    # so the checks log shows what was seen, but never notified on and never
    # counted in an aggregate until a later read agrees with it (§4.3).
    method: Mapped[str | None] = mapped_column(Text)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
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
    # null = RECHECK_INTERVAL_MINUTES; jobs.py floors it when queueing a check
    recheck_interval_minutes: Mapped[int | None] = mapped_column()
    # false = hunted only on a user's "hunt now"; the sweep and every hunt
    # successor skip it (jobs.py)
    hunt: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("user_id", "item_id", name="uq_item_user"),)


class WatchSites(Base):
    """Per-watch site subset — the API's `site_ids`, mirrored from
    backend/app/models.py (the backend owns the schema, D1). No rows for a
    watch means "search all of the category's sites"."""

    __tablename__ = "watch_sites"

    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id"), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), primary_key=True)


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


class VisionScans(Base):
    """Column-compatible SUBSET of backend/app/models.py's VisionScans (the
    backend owns the schema, D1): just the columns save_listing's auto-reject
    backstop reads. The embedding-bearing vision tables are deliberately not
    mirrored — the agent never touches embeddings, which keeps this mirror
    free of the pgvector dependency."""

    __tablename__ = "vision_scans"

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id"))
    listing_url: Mapped[str] = mapped_column(Text)
    auto_reject: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (UniqueConstraint("watch_id", "listing_url", name="uq_vision_scan"),)


class Jobs(Base):
    """One unit of work — mirrors backend/app/models.py (the backend owns the
    schema, D1). The daemon claims these one at a time (agent/jobs.py):
    `hunt` searches a (watch, site) pair with the model, `recheck` re-reads one
    listing's price without one, `ground` refreshes an item's market stats.

    The partial unique index on open jobs lives in migration 015, not here:
    this mirror is read and written, never used to build a schema."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)  # hunt | recheck | ground
    # NULL = nobody asked; the hunter queued this itself
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    watch_id: Mapped[int | None] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"))
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    listing_id: Mapped[int | None] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(
        Text, server_default=text("'pending'")
    )  # pending|running|done|failed|cancelled
    priority: Mapped[int] = mapped_column(server_default=text("0"))
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    locked_by: Mapped[str | None] = mapped_column(Text)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    # user|created|slot_freed|sweep|paused|backoff
    reason: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)  # {"backoff_minutes": 30} on a hunt chain
    stats: Mapped[dict | None] = mapped_column(JSONB)
    last_seq: Mapped[int] = mapped_column(server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobEvents(Base):
    """Ordered progress log for a job — mirrors backend/app/models.py. Written
    by hunts and grounding only; a recheck's whole output is its price check.
    seq is allocated by bumping jobs.last_seq under a row lock (append_event)."""

    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("jobs.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column()
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    level: Mapped[str] = mapped_column(Text)  # info|success|warn|error
    event_type: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (UniqueConstraint("job_id", "seq", name="uq_job_seq"),)


class NotificationOutbox(Base):
    """Durable notification queue — column-compatible SUBSET of
    backend/app/models.py's NotificationOutbox (the backend owns the schema,
    D1): just the columns the agent writes. status and created_at are server
    defaults; the backend's dispatcher owns the rest of the lifecycle."""

    __tablename__ = "notification_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    event: Mapped[str] = mapped_column(Text)  # target.hit | listing.new
    payload: Mapped[dict] = mapped_column(JSONB)


async def get_hunt_unit(watch_id: int, site_id: int) -> RowMapping | None:
    """
    The one (watch, site) pair a hunt job is about, carrying that watch's own
    criteria/selection_mode/max_listings/allow_reproductions.

    None means the pair is no longer one this watch searches — the site was
    unlinked from the category, or dropped from the watch's own subset
    (watch_sites, the API's site_ids), or either row is gone. A hunt job
    outlives the decision that queued it, so the pair is re-validated here
    rather than trusted; the worker treats None as "nothing to do", not as a
    failure.

    Muted watches are hunted like any other: notify gates alerting only (the
    UI calls it "Notify me when the target price is hit"), so a muted watch
    keeps discovering listings and just stays quiet about them.

    Args:
      watch_id: The watch this hunt is for.
      site_id: The site to search.
    Returns:
      A row mapping with keys watch_id, user_id, criteria, expected_price,
      condition_hint, selection_mode, max_listings, allow_reproductions,
      item_id, item_name, category_id, site_id, site_name, base_url — or None.
      A failed query PROPAGATES: the job must fail and be retried, not be
      silently treated as an invalid pair.
    """
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
            .where(Watches.id == watch_id)
            .where(Sites.id == site_id)
        )
        # the category join says the site carries this kind of item; a watch's
        # pins narrow that to its own subset. Correlated on the outer Watches
        # row, so the watch is judged on its own pins.
        pinned = select(WatchSites.site_id).where(WatchSites.watch_id == Watches.id)
        stmt = stmt.where(or_(~pinned.exists(), Sites.id.in_(pinned)))

        return (await session.execute(stmt)).mappings().one_or_none()


async def get_recheck_unit(listing_id: int) -> RowMapping | None:
    """
    The one listing a recheck job is about, with its watch, site and item
    context and whatever locator it has learned.

    None means the listing is gone or no longer tracked — the user untracked
    it, or a previous check found it sold — and there is nothing to re-read.
    The queue's own rules make that rare (untracking cancels the pending
    check), but a job claimed a moment before still has to cope.

    Args:
      listing_id: The listing to re-read.
    Returns:
      A row mapping with keys listing_id, listing_url, watch_id, user_id,
      condition_hint, site_id, site_name, site_base_url, item_id, item_name,
      price_locator, locator_kind, locator_failures and static_ok — everything
      a deterministic recheck needs to read the page without a second query
      (agent/recheck.py) — or None. A failed query PROPAGATES.
    """
    async with AsyncSessionLocal() as session:
        stmt = (
            select(
                Listings.id.label("listing_id"),
                Listings.url.label("listing_url"),
                Listings.price_locator.label("price_locator"),
                Listings.locator_kind.label("locator_kind"),
                Listings.locator_failures.label("locator_failures"),
                Listings.static_ok.label("static_ok"),
                Watches.id.label("watch_id"),
                Watches.user_id.label("user_id"),
                Watches.condition_hint.label("condition_hint"),
                Sites.id.label("site_id"),
                Sites.name.label("site_name"),
                Sites.base_url.label("site_base_url"),
                Items.id.label("item_id"),
                Items.name.label("item_name"),
            )
            .join(Sites, Sites.id == Listings.site_id)
            .join(Watches, Watches.id == Listings.watch_id)
            .join(Items, Items.id == Listings.item_id)
            .where(Listings.id == listing_id)
            .where(Listings.active)
        )

        return (await session.execute(stmt)).mappings().one_or_none()


async def get_ground_unit(item_id: int) -> RowMapping | None:
    """
    The item a ground job is about — its name and category, which is all
    grounding needs to start.

    None means the item is gone. An unwatched item is still grounded if a job
    says so: nobody is asking about it, but the job was queued when somebody
    was, and refusing here would leave the row pending forever.

    Args:
      item_id: The item to refresh market stats for.
    Returns:
      A row mapping with keys item_id, item_name, category_id, or None. A
      failed query PROPAGATES.
    """
    async with AsyncSessionLocal() as session:
        stmt = select(
            Items.id.label("item_id"),
            Items.name.label("item_name"),
            Items.category_id.label("category_id"),
        ).where(Items.id == item_id)

        return (await session.execute(stmt)).mappings().one_or_none()


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


async def get_known_listing_urls(watch_id: int, site_id: int) -> Sequence[str]:
    """
    Return every listing URL already saved for this (watch, site) pair,
    active or not — the set a scan must not save again. Inactive rows count:
    a listing that sold, ended, or the user untracked is not a discovery,
    and re-saving it would silently reattach price checks to a row the UI
    no longer shows.

    Args:
      watch_id: The internal id of the watch to look up listings for.
      site_id: The internal id of the site to look up listings for.
    Returns:
      A sequence of URLs. Returns an empty sequence if the query fails, so a
      DB hiccup skips the skip-list instead of crashing the run.
    """

    log.info(f"Fetching known listing urls for watch {watch_id} on site {site_id}")
    async with AsyncSessionLocal() as session:
        try:
            stmt = (
                select(Listings.url)
                .where(Listings.watch_id == watch_id)
                .where(Listings.site_id == site_id)
                .order_by(Listings.id)
            )

            results = await session.execute(stmt)
            return results.scalars().all()
        except Exception as e:
            log.error(f"Error fetching known listing urls for watch {watch_id}: {e}")
            return []


async def get_active_listing_count(watch_id: int) -> int:
    """
    Return how many active listings a watch holds across every site — the
    slots already in use against its max_listings cap.

    Unlike its neighbours this raises on a failed query instead of returning
    a default, because there is no safe one: 0 would let the scan over-fill
    the watch (the bug the cap exists to prevent) and "full" would silently
    stop discovery. The orchestrator reads it outside its per-unit guard, so
    a failure fails the run loudly.

    Args:
      watch_id: The internal id of the watch to count listings for.
    Returns:
      The number of listings rows for the watch with active = true.
    """

    log.info(f"Counting active listings for watch {watch_id}")
    async with AsyncSessionLocal() as session:
        stmt = (
            select(func.count())
            .select_from(Listings)
            .where(Listings.watch_id == watch_id)
            .where(Listings.active)
        )
        return (await session.execute(stmt)).scalar_one()


async def get_price_context(listing_id: int) -> dict:
    """
    The two reference prices validate_observation judges a new reading
    against, plus the item's market stats.

    last_price is the listing's last CONFIRMED price and is what the
    plausibility bands are measured against. unconfirmed_price is the most
    recent reading only if it was NOT believed, and exists solely so the next
    reading can corroborate it — it is deliberately never the band reference,
    or one bad reading would become the yardstick that makes the next
    identical bad reading look normal.

    Args:
      listing_id: The listing about to be re-read.
    Returns:
      A dict with keys last_price, unconfirmed_price and market. Every value
      may be None; a failed query answers all-None, which only widens what is
      believed rather than narrowing it.
    """
    async with AsyncSessionLocal() as session:
        try:
            last_price = await session.scalar(
                select(PriceChecks.price)
                .where(PriceChecks.listing_id == listing_id)
                .where(PriceChecks.price > 0)
                .where(PriceChecks.confirmed)
                .order_by(PriceChecks.checked_at.desc())
                .limit(1)
            )
            latest = (
                await session.execute(
                    select(PriceChecks.price, PriceChecks.confirmed)
                    .where(PriceChecks.listing_id == listing_id)
                    .where(PriceChecks.price > 0)
                    .order_by(PriceChecks.checked_at.desc())
                    .limit(1)
                )
            ).first()
            item_id = await session.scalar(
                select(Listings.item_id).where(Listings.id == listing_id)
            )
            market = await session.get(MarketPrices, item_id) if item_id else None
        except Exception as e:
            log.error(f"Error fetching price context for listing {listing_id}: {e}")
            return {"last_price": None, "unconfirmed_price": None, "market": None}

    return {
        "last_price": last_price,
        "unconfirmed_price": (
            latest.price if latest is not None and not latest.confirmed else None
        ),
        "market": (
            {"status": market.status, "tiers": market.tiers, "currency": market.currency}
            if market
            else None
        ),
    }


async def save_locator(listing_id: int, kind: str, locator: str, static_ok: bool = False) -> bool:
    """
    Store a verified locator on a listing, clearing its failure count.

    Only ever called after the locator has been replayed in the browser and
    read back the exact price that was confirmed (agent/locators.py) — an
    unverified locator is never written, because a wrong one silently records
    the wrong number forever.

    Args:
      listing_id: The listing the locator belongs to.
      kind: One of jsonld | meta | microdata | css.
      locator: The JSON path, meta key or CSS selector.
      static_ok: Whether the learn-time probe found the same price in the raw
        HTML, which is what lets later rechecks skip the browser.
    Returns:
      True on success, False if the write failed — a lost locator costs one
      LLM read next time, never an observation.
    """
    log.info(f"Learned {kind} locator for listing {listing_id}: {locator} (static_ok={static_ok})")
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                update(Listings)
                .where(Listings.id == listing_id)
                .values(
                    price_locator=locator,
                    locator_kind=kind,
                    locator_verified_at=datetime.now(UTC),
                    locator_failures=0,
                    static_ok=static_ok,
                )
            )
            await session.commit()
            return True
        except Exception as e:
            log.error(f"Error saving locator for listing {listing_id}: {e}")
            return False


async def note_locator_failure(listing_id: int, max_failures: int) -> bool:
    """
    Count one locator read that came back empty, and clear the locator once
    it has missed too often.

    A site restyle breaks every locator derived from its old markup at once.
    Clearing after LOCATOR_MAX_FAILURES is what hands the listing back to the
    LLM so a fresh locator can be learned, instead of burning a browser load
    per recheck forever on a selector that will never match again.

    Args:
      listing_id: The listing whose locator missed.
      max_failures: LOCATOR_MAX_FAILURES — the count at which it is dropped.
    Returns:
      True if the locator was cleared by this failure.
    """
    async with AsyncSessionLocal() as session:
        try:
            failures = await session.scalar(
                update(Listings)
                .where(Listings.id == listing_id)
                .values(locator_failures=Listings.locator_failures + 1)
                .returning(Listings.locator_failures)
            )
            cleared = failures is not None and failures >= max_failures
            if cleared:
                log.info(f"Clearing locator for listing {listing_id} after {failures} misses")
                await session.execute(
                    update(Listings)
                    .where(Listings.id == listing_id)
                    .values(
                        price_locator=None,
                        locator_kind=None,
                        locator_verified_at=None,
                        locator_failures=0,
                        static_ok=False,
                    )
                )
            await session.commit()
            return cleared
        except Exception as e:
            log.error(f"Error counting locator failure for listing {listing_id}: {e}")
            return False


async def has_verified_locator(listing_id: int) -> bool:
    """
    Whether this listing already knows where its price lives.

    Read before the orchestrator's post-unit learn, which costs a navigation:
    the in-unit learn inside save_price_check usually got there first, and
    re-deriving the same locator would pay for it twice.

    Args:
      listing_id: The listing to ask about.
    Returns:
      True when a verified locator is stored.
    """
    async with AsyncSessionLocal() as session:
        try:
            return (
                await session.scalar(
                    select(Listings.locator_verified_at).where(Listings.id == listing_id)
                )
            ) is not None
        except Exception as e:
            log.error(f"Error reading locator state for listing {listing_id}: {e}")
            return False


async def clear_static_ok(listing_id: int) -> bool:
    """
    Stop rechecking this listing without a browser.

    Written when the static rung missed but the browser then read the same
    locator fine: for this listing the raw page and the rendered page differ,
    so the GET is wasted work. The next LLM learn re-probes and may set it
    again (decision 14).

    Args:
      listing_id: The listing to send back to the browser.
    Returns:
      True on success.
    """
    log.info(f"Listing {listing_id} needs the browser after all; clearing static_ok")
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                update(Listings).where(Listings.id == listing_id).values(static_ok=False)
            )
            await session.commit()
            return True
        except Exception as e:
            log.error(f"Error clearing static_ok for listing {listing_id}: {e}")
            return False


async def deactivate_listing(listing_id: int, reason: DisableReason) -> bool:
    """
    Mark a listing inactive because a deterministic recheck saw it end.

    The same write disable_listing makes for the LLM, reached from the code
    path instead: a listing whose page says it sold or ended stops being
    tracked either way.

    Args:
      listing_id: The listing to stop tracking.
      reason: Why — "sold", "ended" or "auction", stored as the listing's
        inactive_reason.
    Returns:
      True on success.
    Raises:
      ValueError: for any other reason. Only code calls this, so a wrong
        reason is a bug — and past this point the CHECK's refusal would be
        swallowed below, leaving the listing tracked with nobody told.
    """
    if reason not in DISABLE_REASONS:
        raise ValueError(f"reason must be one of {', '.join(DISABLE_REASONS)}, got {reason!r}")
    log.info(f"Listing {listing_id} marked inactive ({reason})")
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                update(Listings)
                .where(Listings.id == listing_id)
                .values(active=False, inactive_reason=reason)
            )
            await session.commit()
            return True
        except Exception as e:
            log.error(f"Error disabling listing {listing_id}: {e}")
            return False


async def enqueue_notification(user_id: int, event: str, payload: dict) -> bool:
    """
    Record one notification-worthy event for the backend's dispatcher to
    deliver. Migration 010's trigger announces the committed insert, so
    writing the row is the whole job — the agent never contacts a push
    service.

    Args:
      user_id: The owner the notification is for.
      event: The event name, e.g. "target.hit" or "listing.new".
      payload: Display facts frozen at enqueue (entity ids, names,
        decimal-string prices) — the dispatcher renders every channel from
        these.
    Returns:
      True on success, False if the write failed — the price check or
      listing that triggered the event is never lost to a failed enqueue.
    """

    log.info(f"Queueing {event} notification for user {user_id}")
    async with AsyncSessionLocal() as session:
        try:
            session.add(NotificationOutbox(user_id=user_id, event=event, payload=payload))
            await session.commit()
            return True
        except Exception as e:
            log.error(f"Error queueing {event} notification for user {user_id}: {e}")
            return False


async def enqueue_new_listing(
    watch_id: int,
    item_id: int,
    site_id: int,
    listing_id: int,
    url: str,
    title: str,
    match_score: int,
    match_summary: str,
) -> bool:
    """
    Queue a "new listing" notification for a listing save_listing just
    created — unless the watch is muted. notify gates alerting only, never
    discovery (get_watched_item_list scans muted watches too), so this is
    where a muted watch's find stays quiet. No price in the payload — the
    first price check happens after the listing is saved.

    Args:
      watch_id: The watch the listing was found for.
      item_id: The item the listing is of.
      site_id: The site it was found on.
      listing_id: The id of the freshly inserted listings row.
      url: The listing's URL.
      title: The listing's title as shown on the site.
      match_score: The model's 0-100 criteria fit from save_listing.
      match_summary: The one-line justification for that score.
    Returns:
      True on success, False if the watch is muted or anything failed — a
      failed enqueue never changes what save_listing returns to the model.
    """

    async with AsyncSessionLocal() as session:
        try:
            result = await session.execute(
                select(
                    Watches.user_id.label("user_id"),
                    Watches.notify.label("notify"),
                    Items.name.label("item_name"),
                )
                .join(Items, Items.id == Watches.item_id)
                .where(Watches.id == watch_id)
            )
            row = result.mappings().one_or_none()
            site = await session.get(Sites, site_id)
        except Exception as e:
            log.error(f"Error reading notification context for watch {watch_id}: {e}")
            return False
    if row is None or site is None:
        log.error(f"No notification context for watch {watch_id} / site {site_id}")
        return False
    if not row["notify"]:
        log.info(f"Watch {watch_id} is muted; not announcing listing {listing_id}")
        return False

    payload = {
        "watch_id": watch_id,
        "item_id": item_id,
        "listing_id": listing_id,
        "site_id": site_id,
        "item_name": row["item_name"],
        "site_name": site.name,
        "listing_url": url,
        "title": title,
        "match_score": match_score,
        "match_summary": match_summary,
    }
    return await enqueue_notification(row["user_id"], "listing.new", payload)


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
