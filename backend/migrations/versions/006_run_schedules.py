"""run_schedules: user-defined scheduled agent runs

One row per schedule the agent's --consume tick can fire. Recurring rows
have interval_minutes set: when fired, next_due_at rolls forward anchored
(k * interval past the original due time, so "daily at 02:00" stays at
02:00 after downtime). One-shots have interval_minutes NULL: they fire once
at next_due_at, then enabled flips false and the row is kept for history.
next_due_at is NOT NULL — a schedule is always aimed at a time. The scope
triple mirrors agent_runs. No CRUD endpoints yet: rows are seeded via SQL
until the UI refresh defines the management contract.

Revision ID: 006
Revises: 005
Create Date: 2026-08-15

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: str | Sequence[str] | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "run_schedules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("scope_id", sa.Integer),
        sa.Column("scope_label", sa.Text, nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_minutes", sa.Integer),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("last_fired_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("run_schedules")
