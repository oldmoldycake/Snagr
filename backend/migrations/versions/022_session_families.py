"""refresh tokens grouped into the sign-in they came from

sessions.family_id names one sign-in: login, register and SSO start a new
family, and every refresh token rotated out of it carries the same id. The
access JWT carries it too, so a sign-in can be ended as a whole — on a
password change (every sign-in but the one making it), and when a refresh
token that was already rotated away is presented again, which means someone
else holds a copy of it.

Every existing row becomes a family of its own: which rows were rotated out of
which was never recorded.

Revision ID: 022
Revises: 021
Create Date: 2026-09-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "022"
down_revision: str | Sequence[str] | None = "021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("sessions", sa.Column("family_id", sa.Uuid(), nullable=True))
    op.execute("UPDATE sessions SET family_id = gen_random_uuid()")
    op.alter_column("sessions", "family_id", nullable=False)
    op.create_index("ix_sessions_family_id", "sessions", ["family_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_sessions_family_id", table_name="sessions")
    op.drop_column("sessions", "family_id")
