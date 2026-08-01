"""Async SQLAlchemy setup: engine/session factory, ORM models for the price
tracker schema, and the query helpers the agent uses to plan its runs."""

import logging
import os
from collections.abc import Sequence
from datetime import datetime

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
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

load_dotenv()

log = logging.getLogger(__name__)


DATABASE_URL = os.getenv("DATABASE_URL")
assert DATABASE_URL is not None, "DATABASE_URL environment varable is not set"
engine = create_async_engine(DATABASE_URL)

AsyncSessionLocal = async_sessionmaker(
    engine, 
    class_=AsyncSession,
    expire_on_commit=True
)
class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""
    pass


class User(Base):
    """Registered user; owns watches."""
    __tablename__ = "users"

    id:             Mapped[int]         = mapped_column(primary_key=True)
    email:          Mapped[str]         = mapped_column(Text, unique=True)
    email_verified: Mapped[bool]        = mapped_column(Boolean, default=False)
    created_at:     Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now())

class Sites(Base):
    """A marketplace/storefront the agent can search, keyed by base_url."""
    __tablename__ = "sites"
    
    id:             Mapped[int]         = mapped_column(primary_key=True)
    name:           Mapped[str]         = mapped_column(Text, nullable=False)
    base_url:       Mapped[str]         = mapped_column(Text, nullable=False)
    created_at:     Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now()) 

class Categories(Base):
    """Item category (e.g. video games, cards); links items to the sites
    that sell that kind of item via SiteCategories."""
    __tablename__ = "categories"

    id:             Mapped[int]         = mapped_column(primary_key=True)
    name:           Mapped[str]         = mapped_column(Text, nullable=False, unique=True)
    slug:           Mapped[str]         = mapped_column(Text, nullable=False, unique=True)

class SiteCategories(Base):
    """Join table: which categories each site carries — determines which
    sites get searched for a given item."""
    __tablename__ = "site_categories"

    site_id:        Mapped[int]         = mapped_column(ForeignKey("sites.id"), primary_key=True)
    category_id:  Mapped[int]         = mapped_column(ForeignKey("categories.id"), primary_key=True)    

class Items(Base):
    """Pure shared catalog entry — per-user config lives on Watches."""
    __tablename__ = "items"

    id:             Mapped[int]         = mapped_column(primary_key=True)
    category_id:    Mapped[int]         = mapped_column(ForeignKey("categories.id"), index=True)
    name:           Mapped[str]         = mapped_column(Text, nullable=False)
    created_at:     Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now())

class Listings(Base):
    """Watch-scoped: match_score/match_summary are judged against the owning
    watch's criteria, so listings can't be shared across watches."""
    __tablename__ = "listings"

    id:             Mapped[int]         = mapped_column(primary_key=True)
    watch_id:       Mapped[int]         = mapped_column(ForeignKey("watches.id"), index=True)
    item_id:        Mapped[int]         = mapped_column(ForeignKey("items.id"))
    site_id:        Mapped[int]         = mapped_column(ForeignKey("sites.id"))
    url:            Mapped[str]         = mapped_column(Text, nullable=False)
    title:          Mapped[str|None]    = mapped_column(Text)
    site_sku:       Mapped[str|None]    = mapped_column(Text)
    active:         Mapped[bool]        = mapped_column(Boolean, default=True)
    match_score:    Mapped[int|None]    = mapped_column()
    match_summary:  Mapped[str|None]    = mapped_column(Text)
    created_at:     Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("watch_id", "site_id", "url", name="uq_watch_site_url"),
    )

class PriceChecks(Base):
    """Point-in-time price/availability observation for a listing; a
    "sold"/"ended" status also deactivates the listing."""
    __tablename__ = "price_checks"

    id:             Mapped[int]         = mapped_column(primary_key=True)
    listing_id:     Mapped[int]         = mapped_column(ForeignKey("listings.id"))
    price:          Mapped[float|None]  = mapped_column(Numeric(precision=10, scale=2))
    currency:       Mapped[str]         = mapped_column(Text, default="USD")
    in_stock:       Mapped[bool|None]   = mapped_column(Boolean)
    status:         Mapped[str|None]    = mapped_column(Text)
    checked_at:     Mapped[datetime]    = mapped_column(DateTime(timezone=True))

class Watches(Base):
    """One user's relationship to a shared item: their criteria, target price,
    and notification preferences."""
    __tablename__ = "watches"

    id:                     Mapped[int]         = mapped_column(primary_key=True)
    user_id:                Mapped[int]         = mapped_column(ForeignKey("users.id"))
    item_id:                Mapped[int]         = mapped_column(ForeignKey("items.id"))
    target_price:           Mapped[float|None]  = mapped_column(Numeric(precision=10, scale=2))
    notify:                 Mapped[bool]        = mapped_column(Boolean, default=True)
    criteria:               Mapped[str|None]    = mapped_column(Text)
    selection_mode:         Mapped[str]         = mapped_column(Text, default="cheapest")
    max_listings:           Mapped[int]         = mapped_column(default=3)
    allow_reproductions:    Mapped[bool]        = mapped_column(Boolean, default=False)
    last_notified_at:       Mapped[datetime|None] = mapped_column(DateTime(timezone=True))
    created_at:             Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "item_id", name="uq_item_user"),
    )

class ListingChecks(Base):
    """Log of every listing the agent evaluated but did NOT save (poor fit,
    authenticity concerns, duplicate, etc.) so re-runs don't have to
    re-discover the same rejection from scratch and so rejections are
    auditable."""
    __tablename__ = "listing_checks"

    id:             Mapped[int]         = mapped_column(primary_key=True)
    watch_id:       Mapped[int]         = mapped_column(ForeignKey("watches.id"), index=True)
    site_id:        Mapped[int]         = mapped_column(ForeignKey("sites.id"))
    url:            Mapped[str]         = mapped_column(Text, nullable=False)
    reason:         Mapped[str]         = mapped_column(Text)
    notes:          Mapped[str|None]    = mapped_column(Text)
    checked_at:     Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now())

class JobRuns(Base):
    """One row per scraper job execution, for run history and error counts."""
    __tablename__ = "job_runs"

    id:             Mapped[int]         = mapped_column(primary_key=True)
    started_at:     Mapped[datetime]    = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at:    Mapped[datetime|None] = mapped_column(DateTime(timezone=True))
    sites_checked:  Mapped[int]         = mapped_column(default=0)
    errors:         Mapped[int]         = mapped_column(default=0)

async def get_watched_item_list() -> Sequence[RowMapping]:
    """
    Return the (watch, site) pairs to search: one row per site for every
    watch with notify enabled, carrying that watch's own
    criteria/selection_mode/max_listings/allow_reproductions.

    Returns:
      A sequence of row mappings with keys watch_id, criteria,
      selection_mode, max_listings, allow_reproductions, item_id, item_name,
      site_id, site_name, base_url. Returns an empty sequence if the query
      fails, so a DB hiccup skips this run's searches instead of crashing it.
    """
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(
                Watches.id.label("watch_id"),
                Watches.criteria.label("criteria"),
                Watches.selection_mode.label("selection_mode"),
                Watches.max_listings.label("max_listings"),
                Watches.allow_reproductions.label("allow_reproductions"),
                Items.id.label("item_id"),
                Items.name.label("item_name"),
                Sites.id.label("site_id"),
                Sites.name.label("site_name"),
                Sites.base_url.label("base_url"),
            ).join(
                Items, Items.id == Watches.item_id
            ).join(
                SiteCategories, SiteCategories.category_id == Items.category_id
            ).join(
                Sites, Sites.id == SiteCategories.site_id
            ).where(Watches.notify == True)

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
      site_id, site_name, item_id, item_name. Returns an empty sequence if
      the query fails, so a DB hiccup skips this run's rechecks instead of
      crashing it.
    """
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(
                Listings.id.label("listing_id"),
                Listings.url.label("listing_url"),
                Watches.id.label("watch_id"),
                Sites.id.label("site_id"),
                Sites.name.label("site_name"),
                Items.id.label("item_id"),
                Items.name.label("item_name")
            ).join(
                Sites, Sites.id == Listings.site_id
            ).join(
                Watches, Watches.id == Listings.watch_id
            ).join(
                Items, Items.id == Listings.item_id
            ).where(Listings.active == True)

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
            stmt = select(
                ListingChecks.url.label("url"),
                ListingChecks.reason.label("reason"),
                ListingChecks.notes.label("notes"),
            ).where(ListingChecks.watch_id == watch_id
            ).where(ListingChecks.site_id == site_id)

            results = await session.execute(stmt)
            return results.mappings().all()
        except Exception as e:
            log.error(f"Error fetching checked urls for watch {watch_id} on site {site_id}: {e}")
            return []
