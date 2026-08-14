"""Market-price grounding: source registry, aliases, market_prices, signals

Guide-first grounding schema (docs/superpowers/specs/2026-08-09-guide-first-
grounding-design.md). Categories learn WHERE prices live: price_sources is
the system-managed registry (LLM-seeded, promoted to trusted only by a
successful parse), pinned_sources is user-owned and never system-written.
Items learn HOW to be searched (search_aliases, generated once) and WHERE
their guide pages are (guide_pages, {domain: url} cache that lets re-grounds
skip search). market_prices holds the per-tier stats with the observation
audit trail every stat must be explainable from. Watches carry the user's
own expected_price (beats market stats in the prompt) and condition_hint.
Listings record the post-pass component signals and verdict.

Revision ID: 005
Revises: 004
Create Date: 2026-08-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "005"
down_revision: str | Sequence[str] | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "categories",
        sa.Column("price_sources", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "categories",
        sa.Column("pinned_sources", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "items",
        sa.Column("search_aliases", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "items",
        sa.Column("guide_pages", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "watches",
        sa.Column("expected_price", sa.Numeric(precision=10, scale=2), nullable=True),
    )
    op.add_column("watches", sa.Column("condition_hint", sa.Text(), nullable=True))
    op.add_column(
        "listings",
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("listings", sa.Column("verdict", sa.Text(), nullable=True))
    op.create_table(
        "market_prices",
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("tiers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("observations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("confidence", sa.Text(), nullable=True),
        sa.Column("confidence_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.PrimaryKeyConstraint("item_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("market_prices")
    op.drop_column("listings", "verdict")
    op.drop_column("listings", "signals")
    op.drop_column("watches", "condition_hint")
    op.drop_column("watches", "expected_price")
    op.drop_column("items", "guide_pages")
    op.drop_column("items", "search_aliases")
    op.drop_column("categories", "pinned_sources")
    op.drop_column("categories", "price_sources")
