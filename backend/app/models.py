"""All ORM models for the Snagr schema.

The backend OWNS this schema (Decision D1, CLAUDE.md): agent/database.py and
vision/db.py each keep a column-compatible SUBSET of these definitions, so a
change lands as an Alembic revision here — never as create_all() from there.

Columns added on top of the agent's schema are marked  # + api.
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
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
    vision_auto_reject_fake: Mapped[float] = mapped_column(
        Numeric(precision=3, scale=2), server_default=text("0.85")
    )  # + api (D-V9 threshold: fake confidence at/above this auto-rejects the listing)
    vision_auto_promote_real: Mapped[float] = mapped_column(
        Numeric(precision=3, scale=2), server_default=text("0.90")
    )  # + api (D-V7 guardrail: min confidence for a real reference to self-promote)
    vision_auto_promote_fake: Mapped[float] = mapped_column(
        Numeric(precision=3, scale=2), server_default=text("0.90")
    )  # + api (D-V7 guardrail: min confidence for a fake reference to self-promote)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Sites(Base):
    """A marketplace/storefront the agent can search, keyed by base_url.

    The pause columns are the per-site circuit breaker: the hunter counts
    consecutive read errors, and at the threshold stops reading the site at
    all until paused_until passes. A bot wall then costs five reads instead of
    every listing every interval forever."""

    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    consecutive_errors: Mapped[int] = mapped_column(  # + api
        default=0, server_default=text("0")
    )
    paused_until: Mapped[datetime | None] = mapped_column(  # + api
        DateTime(timezone=True)
    )
    paused_reason: Mapped[str | None] = mapped_column(Text)  # + api
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
    # Where this listing's price lives on its page, learned by code at the
    # moment the LLM confirms a price and replayed on every later recheck
    # (agent/locators.py). kind is jsonld|meta|microdata|css. locator_failures
    # counts reads that came back empty since the last verify — past
    # LOCATOR_MAX_FAILURES the locator is cleared and the next LLM read learns
    # a fresh one. static_ok means the same locator reads the same price out
    # of the raw HTML, so rechecks need no browser at all.
    price_locator: Mapped[str | None] = mapped_column(Text)  # + api
    locator_kind: Mapped[str | None] = mapped_column(Text)  # + api
    locator_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # + api
    locator_failures: Mapped[int] = mapped_column(default=0, server_default="0")  # + api
    static_ok: Mapped[bool] = mapped_column(  # + api
        Boolean, default=False, server_default=text("false")
    )
    # use_alter because jobs.listing_id points back here: the two tables
    # reference each other, so one constraint has to be added after both exist
    discovered_by_job_id: Mapped[int | None] = mapped_column(  # + api
        BigInteger,
        ForeignKey("jobs.id", ondelete="SET NULL", use_alter=True, name="fk_listings_job"),
    )
    # Why tracking ended: sold | ended | auction when the hunter saw it,
    # replaced when a better listing took the slot, untracked when the user
    # switched it off. Null while active.
    inactive_reason: Mapped[str | None] = mapped_column(Text)  # + api
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("watch_id", "site_id", "url", name="uq_watch_site_url"),
        CheckConstraint(
            "inactive_reason IN ('sold', 'ended', 'auction', 'replaced', 'untracked')",
            name="ck_listings_inactive_reason",
        ),
    )


class PriceChecks(Base):
    """Point-in-time price/availability observation for a listing. A
    "sold"/"ended" status does not itself deactivate the listing — the agent is
    instructed to follow the check with disable_listing (agent/tools.py)."""

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
    method: Mapped[str | None] = mapped_column(Text)  # + api
    confirmed: Mapped[bool] = mapped_column(  # + api
        Boolean, default=True, server_default=text("true")
    )
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
    # minutes between rechecks of this watch's listings; null = the instance's
    # RECHECK_INTERVAL_MINUTES. The agent floors it at RECHECK_INTERVAL_FLOOR_MINUTES.
    recheck_interval_minutes: Mapped[int | None] = mapped_column()  # + api
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


class ApiTokens(Base):
    """+ api. Personal access tokens — the bearer credential agents (MCP) and
    scripts use. Only the sha256 is stored, like sessions.refresh_hash; the raw
    `snagr_pat_…` value is shown once at creation. Revoking deletes the row."""

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    scopes: Mapped[list] = mapped_column(JSONB)  # subset of read | write | jobs
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # NULL = never
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Jobs(Base):
    """+ api. One unit of the hunter's work, claimed one at a time by the agent
    daemon (SELECT ... FOR UPDATE SKIP LOCKED). A `hunt` searches one
    (watch, site) pair with the model; a `recheck` re-reads one listing's
    price with no model in the loop; a `ground` refreshes an item's market
    stats.

    `uq_jobs_open` is the design, not a safety net: at most one open job per
    target means "check this listing now" is an UPDATE of the pending row, so
    a queue can never grow a second copy of the same work. `user_id` NULL is
    the hunter queueing itself; `reason` is why, and the Activity page shows
    it verbatim.

    `stats` is the terminal tally (listings_checked, prices_found,
    new_listings, errors, tokens_in, tokens_out, duration_ms, and for a
    recheck the method and transport that read the price)."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)  # hunt | recheck | ground
    # NULL = nobody asked; the hunter queued this itself
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # denormalised from the listing: every ownership filter keys on it
    watch_id: Mapped[int | None] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"))
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    listing_id: Mapped[int | None] = mapped_column(ForeignKey("listings.id", ondelete="CASCADE"))
    item_id: Mapped[int | None] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(
        Text, server_default=text("'pending'")
    )  # pending|running|done|failed|cancelled
    priority: Mapped[int] = mapped_column(server_default=text("0"))  # user-triggered = 100
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    locked_by: Mapped[str | None] = mapped_column(Text)
    # stamped by the worker holding the job; the reaper judges liveness by it
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)  # user|created|slot_freed|sweep|paused
    stats: Mapped[dict | None] = mapped_column(JSONB)
    last_seq: Mapped[int] = mapped_column(server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index(
            "uq_jobs_open",
            "kind",
            text("coalesce(listing_id, 0)"),
            text("coalesce(watch_id, 0)"),
            text("coalesce(site_id, 0)"),
            text("coalesce(item_id, 0)"),
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
        Index(
            "ix_jobs_due",
            "run_after",
            text("priority DESC"),
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_jobs_watch", "watch_id", text("created_at DESC")),
    )


class JobEvents(Base):
    """+ api. Ordered progress log for one job — what the Activity page's
    terminal shows and a reconnecting client backfills from (?after_seq=N).
    Written by hunts and grounding only: a recheck's whole output is its
    price_checks row, so it would have nothing to say here."""

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


class NotificationChannels(Base):
    """+ api. One per-user notification destination: a ntfy topic on the
    instance's server, a Discord incoming webhook, or a generic signed
    webhook. `events` filters what it receives (NULL = everything, so a
    channel picks up future event kinds automatically). A webhook's signing
    `secret` is stored recoverable on purpose — every delivery re-signs with
    it — unlike the hashed refresh tokens in `sessions`."""

    __tablename__ = "notification_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(Text)  # ntfy | webhook | discord
    name: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)  # webhook/discord destination; NULL for ntfy
    topic: Mapped[str | None] = mapped_column(Text)  # ntfy topic; NULL otherwise
    secret: Mapped[str | None] = mapped_column(Text)  # webhook HMAC key; NULL otherwise
    events: Mapped[list | None] = mapped_column(JSONB)  # NULL = all events
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationOutbox(Base):
    """+ api. Durable event queue: the agent (and any future writer) records
    one row per notification-worthy event; migration 010's trigger announces
    the insert on 'snagr_notifications' and the backend's dispatcher expands
    it into per-channel deliveries. `payload` is display facts frozen at
    enqueue — entity ids, names, decimal-string prices."""

    __tablename__ = "notification_outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    event: Mapped[str] = mapped_column(Text)  # target.hit | listing.new
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        Text, server_default=text("'pending'")
    )  # pending|processed|skipped
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_notification_outbox_pending", "id", postgresql_where=text("status = 'pending'")),
    )


class NotificationDeliveries(Base):
    """+ api. One channel's send lifecycle for one outbox event. The
    dispatcher claims due pending rows (FOR UPDATE SKIP LOCKED), sends, and
    either marks delivered or spends an attempt and backs off; after
    MAX_ATTEMPTS the row goes 'failed' and stays as the delivery log."""

    __tablename__ = "notification_deliveries"

    id: Mapped[int] = mapped_column(primary_key=True)
    outbox_id: Mapped[int] = mapped_column(ForeignKey("notification_outbox.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("notification_channels.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(
        Text, server_default=text("'pending'")
    )  # pending|delivered|failed
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "ix_notification_deliveries_due",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )


class VisionReferences(Base):
    """+ api. Per-item gold library for the visual-authenticity check: the
    human-confirmed (or guardrail-auto-promoted) real/fake exemplars the
    vision sidecar scores listing photos against. Communal per item (D-V11);
    source_listing_url is shown only to its capturer and admins. Revocation
    is soft — scoring reads WHERE revoked_at IS NULL — so a drifted library
    can be audited, not just emptied."""

    __tablename__ = "vision_references"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(Text)  # real | fake
    variant_tag: Mapped[str | None] = mapped_column(Text)  # e.g. "alternate art" (D-V5)
    provenance: Mapped[str] = mapped_column(Text)  # human | upload | auto (D-V7)
    embedding: Mapped[list[float]] = mapped_column(Vector(384))
    model_name: Mapped[str] = mapped_column(Text)
    object_key: Mapped[str] = mapped_column(Text)  # sha256 of the bytes (D-V12 dedup)
    source_listing_url: Mapped[str | None] = mapped_column(Text)  # NULL for uploads
    captured_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # NULL when provenance='auto' — nobody vouched for it
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index(
            "ix_vision_references_item_live",
            "item_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )


class VisionScans(Base):
    """+ api. One authenticity scan per (watch, listing_url) — the stored
    verdict listing badges are computed from (join on watch_id + url, house
    pattern: computed, not stored on listings). auto_reject is the owner's
    threshold applied AT SCAN TIME: save_listing's backstop reads it, and a
    rescore never flips it (D-V8 boundary)."""

    __tablename__ = "vision_scans"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    # the capturing watch — its owner is whose review queue the images enter (D-V11)
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"))
    listing_url: Mapped[str] = mapped_column(Text)
    llm_authenticity_read: Mapped[str | None] = mapped_column(
        Text
    )  # looks_authentic | suspect | unsure
    verdict: Mapped[str] = mapped_column(Text)  # leans_real | leans_fake | inconclusive
    # NULL = the item's library couldn't score it (no usable references)
    fake_confidence: Mapped[float | None] = mapped_column(Numeric(precision=5, scale=4))
    auto_reject: Mapped[bool] = mapped_column(Boolean, default=False)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("watch_id", "listing_url", name="uq_vision_scan"),)


class VisionListingImages(Base):
    """+ api. One captured listing photo: its embedding, per-image scores,
    and review-queue state. Rows persist independent of any listing save —
    rejected listings are precisely where fake reference candidates come
    from (D-V2). object_key is the sha256 of the bytes, so a duplicate photo
    stores once and a hash reappearing across listings is a stolen-photo
    signal recorded for free (D-V12)."""

    __tablename__ = "vision_listing_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("vision_scans.id", ondelete="CASCADE"))
    image_url: Mapped[str] = mapped_column(Text)  # where it was fetched from
    object_key: Mapped[str] = mapped_column(Text)  # sha256 content hash
    embedding: Mapped[list[float]] = mapped_column(Vector(384))
    model_name: Mapped[str] = mapped_column(Text)
    # nearest live gold cosine per label; NULL = the item has no refs of that label
    real_similarity: Mapped[float | None] = mapped_column(Numeric(precision=5, scale=4))
    fake_similarity: Mapped[float | None] = mapped_column(Numeric(precision=5, scale=4))
    fake_confidence: Mapped[float | None] = mapped_column(Numeric(precision=5, scale=4))
    suggested_label: Mapped[str | None] = mapped_column(Text)  # real | fake | NULL (below suggest)
    review_state: Mapped[str] = mapped_column(
        Text, default="none"
    )  # none | suggested | confirmed | discarded
    # set when this image became a reference (confirm or auto-promote)
    reference_id: Mapped[int | None] = mapped_column(
        ForeignKey("vision_references.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_vision_listing_images_queue", "scan_id", "review_state"),)
