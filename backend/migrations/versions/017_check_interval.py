"""a per-watch check interval, and why a listing stopped being tracked

watches.recheck_interval_minutes lets one watch be re-read more or less often
than the instance's RECHECK_INTERVAL_MINUTES; null means the instance default,
which is every existing watch. The agent floors it at
RECHECK_INTERVAL_FLOOR_MINUTES when it queues each successor check.

listings.inactive_reason records why tracking ended: 'sold', 'ended' or
'auction' when the hunter saw it happen, 'replaced' when a better listing took
the slot, 'untracked' when the user switched it off. A CHECK keeps it to those
five. Rows made inactive before this revision backfill to 'ended' — the reason
was only ever logged, and ended is the one that is true of all of them.

Revision ID: 017
Revises: 016
Create Date: 2026-09-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "017"
down_revision: str | Sequence[str] | None = "016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("watches", sa.Column("recheck_interval_minutes", sa.Integer(), nullable=True))

    op.add_column("listings", sa.Column("inactive_reason", sa.Text(), nullable=True))
    op.execute("UPDATE listings SET inactive_reason = 'ended' WHERE NOT active")
    op.create_check_constraint(
        "ck_listings_inactive_reason",
        "listings",
        "inactive_reason IN ('sold', 'ended', 'auction', 'replaced', 'untracked')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_listings_inactive_reason", "listings", type_="check")
    op.drop_column("listings", "inactive_reason")
    op.drop_column("watches", "recheck_interval_minutes")
