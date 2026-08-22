"""vision authenticity: reference library, scans, listing images, thresholds

The visual-authenticity feature (design decisions D-V1…D-V12):
vision_references is the per-item gold library the vision sidecar scores
against; vision_scans stores one verdict per (watch, listing_url) — listing
badges join on it rather than storing a copy; vision_listing_images holds
each captured photo's embedding, scores, and review-queue state. Three users
columns carry the per-user thresholds, backfilled to the shipped defaults.

Embeddings are pgvector vector(384), which makes the extension a
project-wide prerequisite from this revision on — vision enabled or not.
CREATE EXTENSION needs superuser rights the app's DB role should not have,
so this migration only prechecks pg_extension and fails with a pointer to
the docs instead of a traceback.

Revision ID: 009
Revises: 008
Create Date: 2026-08-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: str | Sequence[str] | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    installed = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
        .scalar()
    )
    if not installed:
        raise RuntimeError(
            "Snagr now requires the pgvector extension. Run `CREATE EXTENSION vector;` "
            "as your Postgres admin (see README → Requirements), then re-run "
            "`alembic upgrade head`."
        )

    op.create_table(
        "vision_references",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "item_id",
            sa.Integer,
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("variant_tag", sa.Text),
        sa.Column("provenance", sa.Text, nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("model_name", sa.Text, nullable=False),
        sa.Column("object_key", sa.Text, nullable=False),
        sa.Column("source_listing_url", sa.Text),
        sa.Column("captured_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("confirmed_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_vision_references_item_live",
        "vision_references",
        ["item_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "vision_scans",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "item_id",
            sa.Integer,
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "watch_id",
            sa.Integer,
            sa.ForeignKey("watches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("listing_url", sa.Text, nullable=False),
        sa.Column("llm_authenticity_read", sa.Text),
        sa.Column("verdict", sa.Text, nullable=False),
        sa.Column("fake_confidence", sa.Numeric(precision=5, scale=4)),
        sa.Column("auto_reject", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("watch_id", "listing_url", name="uq_vision_scan"),
    )

    op.create_table(
        "vision_listing_images",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "scan_id",
            sa.Integer,
            sa.ForeignKey("vision_scans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("image_url", sa.Text, nullable=False),
        sa.Column("object_key", sa.Text, nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("model_name", sa.Text, nullable=False),
        sa.Column("real_similarity", sa.Numeric(precision=5, scale=4)),
        sa.Column("fake_similarity", sa.Numeric(precision=5, scale=4)),
        sa.Column("fake_confidence", sa.Numeric(precision=5, scale=4)),
        sa.Column("suggested_label", sa.Text),
        sa.Column("review_state", sa.Text, nullable=False, server_default=sa.text("'none'")),
        sa.Column(
            "reference_id",
            sa.Integer,
            sa.ForeignKey("vision_references.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_vision_listing_images_queue",
        "vision_listing_images",
        ["scan_id", "review_state"],
    )

    op.add_column(
        "users",
        sa.Column(
            "vision_auto_reject_fake",
            sa.Numeric(precision=3, scale=2),
            nullable=False,
            server_default=sa.text("0.85"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "vision_auto_promote_real",
            sa.Numeric(precision=3, scale=2),
            nullable=False,
            server_default=sa.text("0.90"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "vision_auto_promote_fake",
            sa.Numeric(precision=3, scale=2),
            nullable=False,
            server_default=sa.text("0.90"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "vision_auto_promote_fake")
    op.drop_column("users", "vision_auto_promote_real")
    op.drop_column("users", "vision_auto_reject_fake")
    op.drop_table("vision_listing_images")
    op.drop_table("vision_scans")
    op.drop_table("vision_references")
