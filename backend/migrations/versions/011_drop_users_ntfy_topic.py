"""drop users.ntfy_topic — channels own the destination now

Second half of migration 010's two-step: 010 copied every configured topic
into a notification_channels row while the agent still SELECTed the column;
this revision lands together with the agent port that stops reading it, so
neither ever sees a schema it doesn't expect.

Revision ID: 011
Revises: 010
Create Date: 2026-09-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011"
down_revision: str | Sequence[str] | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("users", "ntfy_topic")


def downgrade() -> None:
    """Downgrade schema. Values are not restored — 010's backfilled channel
    rows are the surviving record of what each topic was."""
    op.add_column("users", sa.Column("ntfy_topic", sa.Text(), nullable=True))
