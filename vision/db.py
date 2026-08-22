"""Sync SQLAlchemy setup and the sidecar's column-compatible subset of the
canonical schema (backend/app/models.py owns it, decision D1): the three
vision_* tables in full, plus the minimal slices of users/watches/items the
sidecar joins through — thresholds, watch → owner, and FK targets."""

from datetime import datetime

from config import DATABASE_URL
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

assert DATABASE_URL is not None, "DATABASE_URL environment variable is not set"
engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(engine)


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""

    pass


class Users(Base):
    """Subset: the per-user vision thresholds (D-V9) the scoring and
    promotion paths resolve through watch → owner."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    vision_auto_reject_fake: Mapped[float] = mapped_column(
        Numeric(precision=3, scale=2), server_default=text("0.85")
    )
    vision_auto_promote_real: Mapped[float] = mapped_column(
        Numeric(precision=3, scale=2), server_default=text("0.90")
    )
    vision_auto_promote_fake: Mapped[float] = mapped_column(
        Numeric(precision=3, scale=2), server_default=text("0.90")
    )


class Items(Base):
    """Subset: FK target for references and scans."""

    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)


class Watches(Base):
    """Subset: the capturing watch, resolved to its owner for thresholds and
    review-queue scoping (D-V11)."""

    __tablename__ = "watches"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))


class VisionReferences(Base):
    """The per-item gold library — mirrors backend/app/models.py. Scoring
    reads only live rows (revoked_at IS NULL)."""

    __tablename__ = "vision_references"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    label: Mapped[str] = mapped_column(Text)  # real | fake
    variant_tag: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[str] = mapped_column(Text)  # human | upload | auto
    embedding: Mapped[list[float]] = mapped_column(Vector(384))
    model_name: Mapped[str] = mapped_column(Text)
    object_key: Mapped[str] = mapped_column(Text)  # sha256 of the bytes
    source_listing_url: Mapped[str | None] = mapped_column(Text)  # NULL for uploads
    captured_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VisionScans(Base):
    """One scan per (watch, listing_url) — mirrors backend/app/models.py.
    auto_reject is stamped at scan time from the owner's threshold; a rescore
    never flips it (D-V8 boundary)."""

    __tablename__ = "vision_scans"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    watch_id: Mapped[int] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"))
    listing_url: Mapped[str] = mapped_column(Text)
    llm_authenticity_read: Mapped[str | None] = mapped_column(Text)
    verdict: Mapped[str] = mapped_column(Text)  # leans_real | leans_fake | inconclusive
    fake_confidence: Mapped[float | None] = mapped_column(Numeric(precision=5, scale=4))
    auto_reject: Mapped[bool] = mapped_column(Boolean, default=False)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("watch_id", "listing_url", name="uq_vision_scan"),)


class VisionListingImages(Base):
    """One captured listing photo — mirrors backend/app/models.py."""

    __tablename__ = "vision_listing_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("vision_scans.id", ondelete="CASCADE"))
    image_url: Mapped[str] = mapped_column(Text)
    object_key: Mapped[str] = mapped_column(Text)  # sha256 content hash (D-V12 dedup)
    embedding: Mapped[list[float]] = mapped_column(Vector(384))
    model_name: Mapped[str] = mapped_column(Text)
    real_similarity: Mapped[float | None] = mapped_column(Numeric(precision=5, scale=4))
    fake_similarity: Mapped[float | None] = mapped_column(Numeric(precision=5, scale=4))
    fake_confidence: Mapped[float | None] = mapped_column(Numeric(precision=5, scale=4))
    suggested_label: Mapped[str | None] = mapped_column(Text)  # real | fake
    review_state: Mapped[str] = mapped_column(
        Text, default="none"
    )  # none | suggested | confirmed | discarded
    reference_id: Mapped[int | None] = mapped_column(
        ForeignKey("vision_references.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
