"""learned price locators on listings, and how each price check was read

The agent learns where a price lives on a listing's page the first time the
LLM confirms one, then replays that locator on every later recheck with no
model in the loop (agent/locators.py). Five columns on listings carry what
was learned: the locator and its kind, when it was last verified, how many
times it has come back empty since, and whether the same locator works
against the raw HTML — which is what lets a recheck skip the browser too.

price_checks gains the other half. method records HOW the price was read
('llm', 'jsonld', 'meta', 'microdata', 'locator'); existing rows backfill to
'llm', which is what they were. confirmed records whether the reading was
believed: a price outside the plausibility bands is still recorded — hiding
an observation is its own failure — but it does not notify and it is left out
of every aggregate until a second read agrees with it. Existing rows are
confirmed, since nothing was judging them.

Revision ID: 014
Revises: 013
Create Date: 2026-09-16

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "014"
down_revision: str | Sequence[str] | None = "013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("listings", sa.Column("price_locator", sa.Text(), nullable=True))
    op.add_column("listings", sa.Column("locator_kind", sa.Text(), nullable=True))
    op.add_column(
        "listings", sa.Column("locator_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "listings",
        sa.Column("locator_failures", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "listings",
        sa.Column("static_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # every price recorded before this revision was typed by the model
    op.add_column("price_checks", sa.Column("method", sa.Text(), nullable=True))
    op.execute("UPDATE price_checks SET method = 'llm' WHERE method IS NULL")
    op.add_column(
        "price_checks",
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("price_checks", "confirmed")
    op.drop_column("price_checks", "method")
    op.drop_column("listings", "static_ok")
    op.drop_column("listings", "locator_failures")
    op.drop_column("listings", "locator_verified_at")
    op.drop_column("listings", "locator_kind")
    op.drop_column("listings", "price_locator")
