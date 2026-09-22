"""the hunter's work queue replaces runs

A run was a batch somebody started. The hunter has no batches: it claims one
job at a time from `jobs` and works it — a `hunt` searches one (watch, site)
pair, a `recheck` re-reads one listing's price, a `ground` refreshes an item's
market stats. `job_events` is the run_events shape keyed by job; only hunts
and grounding write to it, because a recheck's whole output is its price
check.

The partial unique index is the design: at most one open job per target, so
"check this now" is an UPDATE of the pending row rather than a second row, and
a double-click can never queue two hunts of the same pair.

Three triggers announce the work. `jobs_notify` wakes the daemon on
'snagr_jobs' (insert and status change) and feeds the SSE hub's lifecycle
frames; `job_events_notify` and `price_checks_notify` both announce on
'snagr_job_events', which is what puts a hunt's log and every price check on
the Activity page as they happen. Payloads carry ids only and the hub re-reads
the rows: NOTIFY delivers on commit, so an announcement can never outrun what
is readable. Keep the DDL in sync with the copy in tests/conftest.py — the
test schema is built by Base.metadata.create_all, which knows nothing about
triggers.

`sites` gains the circuit breaker's state: consecutive read errors, and the
pause they trip. While a site is paused its jobs are not claimed and no LLM
reads it, so a bot wall costs five reads instead of every listing forever.

The three run tables go. The downgrade recreates them empty — run history is
not migrated back, because nothing can reconstruct it and a half-restored
history is worse than none.

Revision ID: 015
Revises: 014
Create Date: 2026-09-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "015"
down_revision: str | Sequence[str] | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The two run triggers (migration 007) die with their tables, but their
# functions do not — and 007's own downgrade expects to drop them, so the
# downgrade below puts both back.
_RUN_NOTIFY_FUNCTIONS = [
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
    """,
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
    """,
]

_RUN_TRIGGERS = [
    """
    CREATE TRIGGER run_events_notify
        AFTER INSERT ON run_events
        FOR EACH ROW EXECUTE FUNCTION notify_run_event()
    """,
    """
    CREATE TRIGGER agent_runs_insert_notify
        AFTER INSERT ON agent_runs
        FOR EACH ROW EXECUTE FUNCTION notify_run_status()
    """,
    """
    CREATE TRIGGER agent_runs_status_notify
        AFTER UPDATE OF status ON agent_runs
        FOR EACH ROW
        WHEN (OLD.status IS DISTINCT FROM NEW.status)
        EXECUTE FUNCTION notify_run_status()
    """,
]


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False),  # hunt | recheck | ground
        # NULL = nobody asked; the hunter queued it itself
        sa.Column(
            "user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        # denormalised from the listing so ownership filters stay one join short
        sa.Column("watch_id", sa.Integer, sa.ForeignKey("watches.id", ondelete="CASCADE")),
        sa.Column("site_id", sa.Integer, sa.ForeignKey("sites.id", ondelete="CASCADE")),
        sa.Column("listing_id", sa.Integer, sa.ForeignKey("listings.id", ondelete="CASCADE")),
        sa.Column("item_id", sa.Integer, sa.ForeignKey("items.id", ondelete="CASCADE")),
        # pending | running | done | failed | cancelled
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("priority", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("attempts", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("locked_by", sa.Text),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text),
        # why it was queued: user | created | slot_freed | sweep | paused
        sa.Column("reason", sa.Text),
        sa.Column("stats", JSONB),
        sa.Column("last_seq", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    # one open job per target — what makes "check this now" a bump, not a queue
    op.execute(
        """
        CREATE UNIQUE INDEX uq_jobs_open ON jobs (
            kind,
            coalesce(listing_id, 0),
            coalesce(watch_id, 0),
            coalesce(site_id, 0),
            coalesce(item_id, 0)
        ) WHERE status IN ('pending', 'running')
        """
    )
    op.create_index(
        "ix_jobs_due",
        "jobs",
        ["run_after", sa.text("priority DESC")],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("ix_jobs_watch", "jobs", ["watch_id", sa.text("created_at DESC")])

    op.create_table(
        "job_events",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column(
            "job_id", sa.BigInteger, sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.Text, nullable=False),  # info | success | warn | error
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("payload", JSONB),
        sa.UniqueConstraint("job_id", "seq", name="uq_job_seq"),
    )
    op.create_index("ix_job_events_job_id", "job_events", ["job_id"])

    op.execute(
        """
        CREATE OR REPLACE FUNCTION notify_job() RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify(
                'snagr_jobs',
                json_build_object('id', NEW.id, 'kind', NEW.kind, 'status', NEW.status)::text
            );
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION notify_job_event() RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify(
                'snagr_job_events',
                json_build_object('job_id', NEW.job_id, 'seq', NEW.seq)::text
            );
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION notify_price_check() RETURNS trigger AS $$
        BEGIN
            PERFORM pg_notify('snagr_job_events', json_build_object('check', NEW.id)::text);
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    # insert as well as status change: an insert is what wakes the daemon, and
    # a job born 'pending' never fires an UPDATE for its own arrival
    op.execute(
        """
        CREATE TRIGGER jobs_insert_notify
            AFTER INSERT ON jobs
            FOR EACH ROW EXECUTE FUNCTION notify_job()
        """
    )
    op.execute(
        """
        CREATE TRIGGER jobs_status_notify
            AFTER UPDATE OF status ON jobs
            FOR EACH ROW
            WHEN (OLD.status IS DISTINCT FROM NEW.status)
            EXECUTE FUNCTION notify_job()
        """
    )
    op.execute(
        """
        CREATE TRIGGER job_events_notify
            AFTER INSERT ON job_events
            FOR EACH ROW EXECUTE FUNCTION notify_job_event()
        """
    )
    op.execute(
        """
        CREATE TRIGGER price_checks_notify
            AFTER INSERT ON price_checks
            FOR EACH ROW EXECUTE FUNCTION notify_price_check()
        """
    )

    # which hunt found a listing — the job page is one click from the listing
    op.add_column("listings", sa.Column("discovered_by_job_id", sa.BigInteger, nullable=True))
    # named, because jobs.listing_id points back at listings: the two tables
    # reference each other, and a cycle needs a constraint the models can name
    op.create_foreign_key(
        "fk_listings_job", "listings", "jobs", ["discovered_by_job_id"], ["id"], ondelete="SET NULL"
    )

    # the circuit breaker's state (design §4.4)
    op.add_column(
        "sites",
        sa.Column("consecutive_errors", sa.Integer, nullable=False, server_default=sa.text("0")),
    )
    op.add_column("sites", sa.Column("paused_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sites", sa.Column("paused_reason", sa.Text, nullable=True))

    # a token minted to trigger runs now triggers jobs — same power, new name
    op.execute(
        """
        UPDATE api_tokens
           SET scopes = (
               SELECT jsonb_agg(
                          CASE WHEN scope = '"runs"'::jsonb THEN '"jobs"'::jsonb ELSE scope END
                      )
                 FROM jsonb_array_elements(scopes) AS scope
           )
         WHERE scopes @> '["runs"]'::jsonb
        """
    )

    op.drop_table("run_events")
    op.drop_table("agent_runs")
    op.drop_table("run_schedules")
    op.execute("DROP FUNCTION notify_run_status()")
    op.execute("DROP FUNCTION notify_run_event()")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "run_schedules",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
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
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("scope_id", sa.Integer),
        sa.Column("scope_label", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'queued'")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("stats", JSONB),
        sa.Column("error", sa.Text),
        sa.Column("last_seq", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
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
    for ddl in _RUN_NOTIFY_FUNCTIONS + _RUN_TRIGGERS:
        op.execute(ddl)

    op.execute(
        """
        UPDATE api_tokens
           SET scopes = (
               SELECT jsonb_agg(
                          CASE WHEN scope = '"jobs"'::jsonb THEN '"runs"'::jsonb ELSE scope END
                      )
                 FROM jsonb_array_elements(scopes) AS scope
           )
         WHERE scopes @> '["jobs"]'::jsonb
        """
    )

    op.drop_column("sites", "paused_reason")
    op.drop_column("sites", "paused_until")
    op.drop_column("sites", "consecutive_errors")
    op.drop_constraint("fk_listings_job", "listings", type_="foreignkey")
    op.drop_column("listings", "discovered_by_job_id")

    op.execute("DROP TRIGGER price_checks_notify ON price_checks")
    op.execute("DROP TRIGGER job_events_notify ON job_events")
    op.execute("DROP TRIGGER jobs_status_notify ON jobs")
    op.execute("DROP TRIGGER jobs_insert_notify ON jobs")
    op.execute("DROP FUNCTION notify_price_check()")
    op.execute("DROP FUNCTION notify_job_event()")
    op.execute("DROP FUNCTION notify_job()")

    op.drop_index("ix_job_events_job_id", table_name="job_events")
    op.drop_table("job_events")
    op.drop_index("ix_jobs_watch", table_name="jobs")
    op.drop_index("ix_jobs_due", table_name="jobs")
    op.drop_index("uq_jobs_open", table_name="jobs")
    op.drop_table("jobs")
