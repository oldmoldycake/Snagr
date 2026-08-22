"""pg_notify triggers announcing run activity

The SSE hub (app/services/events.py) holds one LISTEN connection on the
'snagr_run_events' channel. These triggers make every committed run_events
insert and agent_runs status change announce itself there, no matter who
wrote it — the agent's consumer, the backend's cancel, a psql session.
Writers can't forget to notify because they don't have to remember.

Payloads carry ids only (kind=event: run_id+seq; kind=status:
run_id+status) and the hub re-reads the rows: NOTIFY delivers on commit,
so an announcement can never outrun what's readable.

Keep the DDL in sync with the copy in tests/conftest.py — the test schema
is built by Base.metadata.create_all, which knows nothing about triggers.

Revision ID: 007
Revises: 006
Create Date: 2026-08-20

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: str | Sequence[str] | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        """
        CREATE OR REPLACE FUNCTION notify_run_event() RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify(
                'snagr_run_events',
                json_build_object('kind', 'event', 'run_id', NEW.run_id, 'seq', NEW.seq)::text
            );
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION notify_run_status() RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify(
                'snagr_run_events',
                json_build_object('kind', 'status', 'run_id', NEW.id, 'status', NEW.status)::text
            );
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER run_events_notify
            AFTER INSERT ON run_events
            FOR EACH ROW EXECUTE FUNCTION notify_run_event()
        """
    )
    # INSERT too: scheduled and nightly runs are born 'running' (no UPDATE ever
    # fires for their start), and the hub ignores 'queued' births anyway
    op.execute(
        """
        CREATE TRIGGER agent_runs_insert_notify
            AFTER INSERT ON agent_runs
            FOR EACH ROW EXECUTE FUNCTION notify_run_status()
        """
    )
    op.execute(
        """
        CREATE TRIGGER agent_runs_status_notify
            AFTER UPDATE OF status ON agent_runs
            FOR EACH ROW
            WHEN (OLD.status IS DISTINCT FROM NEW.status)
            EXECUTE FUNCTION notify_run_status()
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER agent_runs_status_notify ON agent_runs")
    op.execute("DROP TRIGGER agent_runs_insert_notify ON agent_runs")
    op.execute("DROP TRIGGER run_events_notify ON run_events")
    op.execute("DROP FUNCTION notify_run_status()")
    op.execute("DROP FUNCTION notify_run_event()")
