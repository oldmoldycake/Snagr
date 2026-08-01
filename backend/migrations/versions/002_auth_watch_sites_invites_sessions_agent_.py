"""auth, watch_sites, invites, sessions, agent_runs, run_events

The "Schema Gaps" revision (plan §Schema Gaps): everything the API needs on
top of the agent-era schema. Adds the auth columns to `users`, creates the
five new tables, and drops the dead `job_runs` (verified empty; superseded by
`agent_runs`).

`password_hash` is nullable — the pre-existing agent-era user row has no
password, and auth.py treats NULL as "cannot log in".

Revision ID: 002
Revises: 001
Create Date: 2026-07-08 18:40:48.631860

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: str | Sequence[str] | None = '001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- users: auth columns (server defaults backfill the existing rows) ---
    op.add_column("users", sa.Column("password_hash", sa.Text, nullable=True))
    op.add_column("users", sa.Column("role", sa.Text, nullable=False, server_default=sa.text("'user'")))
    op.add_column("users", sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")))
    op.add_column("users", sa.Column("ntfy_topic", sa.Text, nullable=True))

    # --- watch_sites: the contract's `site_ids` (no rows = all category sites) ---
    op.create_table(
        "watch_sites",
        sa.Column("watch_id", sa.Integer, sa.ForeignKey("watches.id"), primary_key=True),
        sa.Column("site_id", sa.Integer, sa.ForeignKey("sites.id"), primary_key=True),
    )

    # --- invites: admin-issued signup tokens ---
    op.create_table(
        "invites",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("token", sa.Text, nullable=False, unique=True),
        sa.Column("email", sa.Text),
        sa.Column("role", sa.Text, nullable=False, server_default=sa.text("'user'")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- sessions: refresh-token store (sha256 of the cookie value) ---
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("refresh_hash", sa.Text, nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    # --- agent_runs: queued by the API, claimed by the agent ---
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("scope_id", sa.Integer),
        sa.Column("scope_label", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'queued'")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("stats", JSONB),
        sa.Column("error", sa.Text),
        sa.Column("last_seq", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- run_events: ordered progress log; SSE fans out from here ---
    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("run_id", sa.Integer, sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.Text, nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("payload", JSONB),
        sa.UniqueConstraint("run_id", "seq", name="uq_run_seq"),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])

    # --- job_runs: dead (0 rows, agent never wrote it); agent_runs replaces it ---
    op.drop_table("job_runs")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("sites_checked", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("errors", sa.Integer, nullable=False, server_default=sa.text("0")),
    )
    op.drop_table("run_events")
    op.drop_table("agent_runs")
    op.drop_table("sessions")
    op.drop_table("invites")
    op.drop_table("watch_sites")
    op.drop_column("users", "ntfy_topic")
    op.drop_column("users", "is_active")
    op.drop_column("users", "role")
    op.drop_column("users", "password_hash")
