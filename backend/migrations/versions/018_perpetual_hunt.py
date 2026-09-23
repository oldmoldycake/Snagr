"""a per-watch hunting switch, and the state a hunt passes to the next

watches.hunt is the per-watch toggle for perpetual hunting: true (every
existing watch) lets the hunter look for new listings on its own while the
watch has open slots; false means the watch is hunted only when someone
presses Hunt now. Rechecks of its tracked listings continue either way.

jobs.payload carries what one job hands to its successor. A hunt that found
nothing queues the next one further out, and the wait it used —
{"backoff_minutes": 30} — is how the next one knows to double it. Null for
every job that is not part of a chain.

Revision ID: 018
Revises: 017
Create Date: 2026-09-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "018"
down_revision: str | Sequence[str] | None = "017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "watches",
        sa.Column("hunt", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column("jobs", sa.Column("payload", JSONB(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("jobs", "payload")
    op.drop_column("watches", "hunt")
