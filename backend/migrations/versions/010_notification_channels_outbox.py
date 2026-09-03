"""notification channels, outbox, and deliveries

The notifications rework (D-N1): the agent stops pushing to ntfy itself and
instead records one durable notification_outbox row per event; the trigger
below announces the insert on 'snagr_notifications' and the backend's
dispatcher expands it into per-channel notification_deliveries rows, sending
with retries. notification_channels holds each user's destinations — their
old users.ntfy_topic is copied into a ntfy channel row here (the column
itself is dropped by migration 011, once the agent no longer reads it).

A webhook channel's signing secret is stored recoverable on purpose: every
delivery re-signs with it, so a one-way hash would brick the channel.
Deliberately absent: an updated_at (channels are small, recreate is the
norm), a per-attempt audit table (deliveries.last_error suffices at
household scale), and a secret-rotation flow (delete + recreate).

Keep the trigger DDL in sync with the copy in tests/conftest.py — the test
schema is built by Base.metadata.create_all, which knows nothing about
triggers.

Revision ID: 010
Revises: 009
Create Date: 2026-09-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "010"
down_revision: str | Sequence[str] | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "notification_channels",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.Text, nullable=False),  # ntfy | webhook | discord
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("url", sa.Text),  # webhook/discord destination; NULL for ntfy
        sa.Column("topic", sa.Text),  # ntfy topic on the instance server; NULL otherwise
        sa.Column("secret", sa.Text),  # webhook HMAC key; NULL otherwise
        sa.Column("events", postgresql.JSONB),  # NULL = all events
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_notification_channels_user_id", "notification_channels", ["user_id"])

    op.create_table(
        "notification_outbox",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("event", sa.Text, nullable=False),  # target.hit | listing.new
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "status", sa.Text, nullable=False, server_default=sa.text("'pending'")
        ),  # pending | processed | skipped
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_notification_outbox_pending",
        "notification_outbox",
        ["id"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "outbox_id",
            sa.Integer,
            sa.ForeignKey("notification_outbox.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel_id",
            sa.Integer,
            sa.ForeignKey("notification_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.Text, nullable=False, server_default=sa.text("'pending'")
        ),  # pending | delivered | failed
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_error", sa.Text),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_notification_deliveries_due",
        "notification_deliveries",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # every configured topic becomes a ntfy channel — same behavior, new home
    op.execute(
        """
        INSERT INTO notification_channels (user_id, kind, name, topic)
        SELECT id, 'ntfy', 'ntfy', ntfy_topic FROM users WHERE ntfy_topic IS NOT NULL
        """
    )

    # wakeup hint for the dispatcher — ids only, rows re-read (007 idiom)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION notify_outbox() RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify(
                'snagr_notifications',
                json_build_object('outbox_id', NEW.id)::text
            );
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER notification_outbox_notify
            AFTER INSERT ON notification_outbox
            FOR EACH ROW EXECUTE FUNCTION notify_outbox()
        """
    )


def downgrade() -> None:
    """Downgrade schema. The backfilled channel rows are lost — users.ntfy_topic
    still holds the original values until migration 011 drops it."""
    op.execute("DROP TRIGGER notification_outbox_notify ON notification_outbox")
    op.execute("DROP FUNCTION notify_outbox()")
    op.drop_index("ix_notification_deliveries_due", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
    op.drop_index("ix_notification_outbox_pending", table_name="notification_outbox")
    op.drop_table("notification_outbox")
    op.drop_index("ix_notification_channels_user_id", table_name="notification_channels")
    op.drop_table("notification_channels")
