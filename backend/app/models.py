"""All ORM models for the Snagr schema.

The backend OWNS this schema (Decision D1). These definitions mirror the tables
agent/database.py already created — column-for-column — plus the auth/run tables
the API needs. Alembic reconciles the live database to match (see "Schema Gaps"
in docs/superpowers/plans/2026-07-08-backend-api.md).

Columns added on top of the agent's schema are marked  # + api.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class User(Base):
    """Registered user; owns watches."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    password_hash: Mapped[str | None] = mapped_column(
        Text
    )  # + api (argon2; NULL = can't log in yet)
    oidc_sub: Mapped[str | None] = mapped_column(
        Text, unique=True
    )  # + api (OIDC subject; NULL = password-only)
    role: Mapped[str] = mapped_column(Text, default="user")  # + api ('admin' | 'user')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # + api (admin can deactivate)
    ntfy_topic: Mapped[str | None] = mapped_column(Text)  # + api
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Sites(Base):
    """A marketplace/storefront the agent can search, keyed by base_url."""

    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Categories(Base):
    """Item category (e.g. video games, cards); links items to the sites that
    sell that kind of item via SiteCategories."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    condition_tiers: Mapped[list | None] = mapped_column(JSONB)
    price_sources: Mapped[list | None] = mapped_column(JSONB)
    pinned_sources: Mapped[list | None] = mapped_column(JSONB)


class SiteCategories(Base):
    """Join table: which categories each site carries — determines which sites
    get searched for a given item."""

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
    agent's grounding pass."""

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


class WatchSites(Base):
    """+ api. Per-watch site subset — the contract's `site_ids`. No rows for a
    watch means "search all of the category's sites" (site_ids: null)."""

    __tablename__ = "watch_sites"

    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id"), primary_key=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), primary_key=True)


class ListingChecks(Base):
    """Log of every listing the agent evaluated but did NOT save (poor fit,
    authenticity concerns, duplicate, etc.) so re-runs skip re-judging them."""

    __tablename__ = "listing_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"))
    url: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Invites(Base):
    """+ api. Admin-issued signup token; optionally pinned to an email."""

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(Text, unique=True)
    email: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, default="user")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Sessions(Base):
    """+ api. Refresh-token store; the raw token lives only in the httpOnly
    cookie, we persist its sha256. Rotated on every /api/auth/refresh."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    refresh_hash: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentRuns(Base):
    """+ api. One row per agent run. Supersedes the agent's unused JobRuns.
    Created status='queued' by the API; the agent claims and drives it."""

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
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
    """+ api. Ordered progress log for a run — the source the SSE stream fans
    out and a reconnecting client backfills from (?after_seq=N)."""

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
    """+ api. User-defined scheduled runs. The agent's --consume tick fires a
    due row by inserting a normal agent_runs row (scope copied verbatim):
    recurring rows (interval_minutes set) roll next_due_at forward anchored;
    one-shots (interval_minutes NULL) flip enabled off and keep the row."""

    __tablename__ = "run_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(Text)  # global | category | site | item
    scope_id: Mapped[int | None] = mapped_column()
    scope_label: Mapped[str] = mapped_column(Text)
    next_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    interval_minutes: Mapped[int | None] = mapped_column()  # NULL = one-shot
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
