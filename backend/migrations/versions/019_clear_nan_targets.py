"""clear target prices stored as NaN

The API once handed target_price straight to Decimal(), which takes "NaN",
and Postgres numeric stores it. A NaN target breaks every read that compares
a price with it: the item list and item page answer 500, and the dashboard
counts the item as at target. The API now refuses anything but an amount in
whole cents, so this clears the rows that got in before it did; the watch
goes on tracking prices, with no target, until its owner sets a real one.
"Infinity" and anything out of range never reached a row — the column
overflowed first.

The downgrade is a no-op on purpose: there is no reason to put a NaN back.

Revision ID: 019
Revises: 018
Create Date: 2026-09-26

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "019"
down_revision: str | Sequence[str] | None = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("UPDATE watches SET target_price = NULL WHERE target_price = 'NaN'")


def downgrade() -> None:
    """Downgrade schema."""
    # nothing to undo: a NaN target is only ever a bug
