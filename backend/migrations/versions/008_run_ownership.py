"""run ownership: user_id on agent_runs + run_schedules

Per-user run privacy (D-P2): a run/schedule belongs to the user who created
it; NULL means a system run (operator-created schedules, the nightly sweep,
pre-migration rows) — visible to every user. Existing rows stay NULL, which
matches what those runs were when they ran.

ON DELETE SET NULL, deliberately: admin user-deletion is a hard delete
(refused only while the user still has watches), so a watchless user who
owns runs must stay deletable — their runs degrade to system instead of
blocking the delete.

Revision ID: 008
Revises: 007
Create Date: 2026-08-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: str | Sequence[str] | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_runs",
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
    )
    op.add_column(
        "run_schedules",
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("run_schedules", "user_id")
    op.drop_column("agent_runs", "user_id")
