"""api tokens — personal access tokens for agents and scripts

The bearer credential for the MCP endpoint and the REST API. Only the sha256 is
stored — the sessions.refresh_hash scheme — and the raw
value is shown once at creation. Revoking deletes the row: no soft-delete, so a
revoked token can't be resurrected by anything later.

Revision ID: 012
Revises: 011
Create Date: 2026-09-11

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "012"
down_revision: str | Sequence[str] | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False, unique=True),
        sa.Column("scopes", postgresql.JSONB, nullable=False),  # subset of read | write | runs
        sa.Column("expires_at", sa.DateTime(timezone=True)),  # NULL = never
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_api_tokens_user_id", table_name="api_tokens")
    op.drop_table("api_tokens")
