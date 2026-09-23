"""queue a first check for listings that predate the jobs table

A listing's recheck chain is started by save_listing, the moment the listing
is saved. Listings saved before migration 015 created the queue never had a
first check queued, so an upgraded install kept showing the prices it had
silently stopped re-reading. This queues that first check for every tracked
listing with no open recheck, and the chain takes it from there.

The spread is a fixed 30 minutes: a migration cannot read the agent's
RECHECK_INTERVAL_MINUTES, and the point is only that a busy instance does not
open every tracked page the second the daemon comes up.

Idempotent — a listing with a pending or running recheck is skipped, so
running it twice adds nothing. The downgrade is a no-op on purpose: the rows
it queued are indistinguishable from the ones save_listing queues, and a
pending recheck is harmless to leave behind (015's downgrade drops the table
anyway).

Revision ID: 016
Revises: 015
Create Date: 2026-09-21

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "016"
down_revision: str | Sequence[str] | None = "015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # fixed 30 minutes — the agent's interval is not readable from here
    op.execute(
        """
        INSERT INTO jobs (kind, watch_id, item_id, site_id, listing_id, reason, run_after)
        SELECT 'recheck', l.watch_id, l.item_id, l.site_id, l.id, 'created',
               now() + random() * interval '30 minutes'
          FROM listings l
         WHERE l.active
           AND NOT EXISTS (
               SELECT 1
                 FROM jobs j
                WHERE j.kind = 'recheck'
                  AND j.listing_id = l.id
                  AND j.status IN ('pending', 'running')
           )
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    # nothing to undo: the queued rows cannot be told apart from organic ones,
    # and a pending recheck does no harm
