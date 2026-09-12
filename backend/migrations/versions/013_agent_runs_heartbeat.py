"""agent_runs.heartbeat_at — liveness for the agent's stale-run reaper

The agent stamps this every RUN_HEARTBEAT_INTERVAL_SECONDS while it drives a
run, and each consumer tick fails any 'running' row silent for longer than
RUN_STALE_AFTER_SECONDS. Without it a run whose process died (SIGKILL, OOM,
power loss) stayed 'running' forever, and enqueue_run's one-active-run guard
turned that into a 409 on every Run button and a skip on every schedule.
Nullable: rows from before this revision are judged on started_at instead.

Revision ID: 013
Revises: 012
Create Date: 2026-09-11

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: str | Sequence[str] | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "agent_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("agent_runs", "heartbeat_at")
