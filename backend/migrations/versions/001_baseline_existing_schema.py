"""baseline existing schema

The nine tables the agent created and already populated (verified against the
live DB 2026-07-08). This revision is STAMPED on the live database, never run
there — it exists so a fresh database can be built from zero with
`alembic upgrade head`. The `users` table here is the agent-era shape; the
auth columns arrive in 002.

Revision ID: 001
Revises:
Create Date: 2026-07-08 18:40:48.398674

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("email_verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "sites",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("base_url", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("slug", sa.Text, nullable=False, unique=True),
    )

    op.create_table(
        "site_categories",
        sa.Column("site_id", sa.Integer, sa.ForeignKey("sites.id"), primary_key=True),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id"), primary_key=True),
    )

    op.create_table(
        "items",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("category_id", sa.Integer, sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_items_category_id", "items", ["category_id"])

    op.create_table(
        "watches",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("target_price", sa.Numeric(10, 2)),
        sa.Column("notify", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("criteria", sa.Text),
        sa.Column("selection_mode", sa.Text, nullable=False, server_default=sa.text("'cheapest'")),
        sa.Column("max_listings", sa.Integer, nullable=False, server_default=sa.text("3")),
        sa.Column("allow_reproductions", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("last_notified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "item_id", name="uq_item_user"),
    )

    op.create_table(
        "listings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("watch_id", sa.Integer, sa.ForeignKey("watches.id"), nullable=False),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id"), nullable=False),
        sa.Column("site_id", sa.Integer, sa.ForeignKey("sites.id"), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("site_sku", sa.Text),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("match_score", sa.Integer),
        sa.Column("match_summary", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("watch_id", "site_id", "url", name="uq_watch_site_url"),
    )
    op.create_index("ix_listings_watch_id", "listings", ["watch_id"])

    op.create_table(
        "price_checks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("listing_id", sa.Integer, sa.ForeignKey("listings.id"), nullable=False),
        sa.Column("price", sa.Numeric(10, 2)),
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'USD'")),
        sa.Column("in_stock", sa.Boolean),
        sa.Column("status", sa.Text),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "listing_checks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("watch_id", sa.Integer, sa.ForeignKey("watches.id"), nullable=False),
        sa.Column("site_id", sa.Integer, sa.ForeignKey("sites.id"), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_listing_checks_watch_id", "listing_checks", ["watch_id"])

    # Agent-era table, already superseded — 002 drops it. Included so the
    # revision chain replays history faithfully on a fresh DB.
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("sites_checked", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("errors", sa.Integer, nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    for table in (
        "job_runs",
        "listing_checks",
        "price_checks",
        "listings",
        "watches",
        "items",
        "site_categories",
        "categories",
        "sites",
        "users",
    ):
        op.drop_table(table)
