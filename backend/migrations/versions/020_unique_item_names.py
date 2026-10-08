"""one item per name in a category

Adding an item finds the category's item by that name or creates it, and it
read then inserted: two submits of the same form made two items of one name,
and so did renaming an item to another's name. Once there were two, adding
that name failed outright, the lookup finding more than one. A unique index
on (category_id, lower(name)) now keeps it to one; the API trims names and
refuses blank ones before they get there.

The rows already in are made to fit first. Names are trimmed, and a blank one
becomes "Untitled item <id>" for its watchers to rename. Of each set of items
sharing a name (ignoring case) the oldest is kept, and the watches on the
others move to it along with their listings, jobs and vision scans — unless
their user watches the kept item already, as a double-clicked Add leaves
them, since two watches of one user can't share an item. Those, and the
emptied items (which keep their vision libraries and market prices), are
renamed "<name> (duplicate <id>)", for their watchers to delete or rename.

The downgrade drops the index and leaves the data as the upgrade left it:
merging items again is not a thing to undo.

Revision ID: 020
Revises: 019
Create Date: 2026-09-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "020"
down_revision: str | Sequence[str] | None = "019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(r"UPDATE items SET name = regexp_replace(name, '^\s+|\s+$', '', 'g')")
    op.execute("UPDATE items SET name = 'Untitled item ' || id WHERE name = ''")

    # each item that shares its name with an older one, and the oldest
    op.execute(
        """
        CREATE TEMP TABLE item_dups ON COMMIT DROP AS
        SELECT id AS dup, keeper FROM (
            SELECT id, min(id) OVER (PARTITION BY category_id, lower(name)) AS keeper
            FROM items
        ) named
        WHERE id <> keeper
        """
    )
    # one watch per user moves: a user on two duplicates of the kept item
    # can't have both land on it
    op.execute(
        """
        CREATE TEMP TABLE moved_watches ON COMMIT DROP AS
        SELECT DISTINCT ON (w.user_id, d.keeper) w.id AS watch_id, d.keeper
        FROM watches w JOIN item_dups d ON d.dup = w.item_id
        WHERE NOT EXISTS (
            SELECT 1 FROM watches kept WHERE kept.item_id = d.keeper AND kept.user_id = w.user_id
        )
        ORDER BY w.user_id, d.keeper, w.id
        """
    )
    for table, key in (
        ("listings", "watch_id"),
        ("jobs", "watch_id"),
        ("vision_scans", "watch_id"),
        ("watches", "id"),
    ):
        op.execute(
            f"UPDATE {table} SET item_id = m.keeper "
            f"FROM moved_watches m WHERE {table}.{key} = m.watch_id"
        )
    op.execute(
        "UPDATE items SET name = name || ' (duplicate ' || id || ')' "
        "FROM item_dups WHERE items.id = item_dups.dup"
    )

    op.create_index(
        "uq_items_category_name", "items", ["category_id", sa.text("lower(name)")], unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_items_category_name", table_name="items")
