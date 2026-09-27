"""one category and one site per name, and no empty slugs

Creating a category refused a blank or taken name, but renaming one didn't,
and sites checked neither: "homelab" could sit beside "Homelab", and "EBAY"
beside "Ebay", after which every MCP call naming that site failed as
ambiguous. A category whose name had no letters or digits (an emoji, "++")
got the slug "" and a link to /categories/ that led nowhere. Unique indexes
on lower(name) now keep both tables to one row per name; the API trims names,
refuses blank ones and never generates an empty slug.

The rows already in are made to fit first, without merging anything: names
are trimmed, a blank one becomes "Untitled category <id>" / "Untitled site
<id>", every row that shares its name (ignoring case) with an older one is
renamed "<name> (duplicate <id>)" for an admin to rename or delete, and an
empty slug becomes "category-<id>".

The downgrade drops the indexes and leaves the names as the upgrade left
them.

Revision ID: 021
Revises: 020
Create Date: 2026-09-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "021"
down_revision: str | Sequence[str] | None = "020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    for table, noun in (("categories", "category"), ("sites", "site")):
        op.execute(rf"UPDATE {table} SET name = regexp_replace(name, '^\s+|\s+$', '', 'g')")
        op.execute(f"UPDATE {table} SET name = 'Untitled {noun} ' || id WHERE name = ''")
        op.execute(
            f"""
            UPDATE {table} SET name = {table}.name || ' (duplicate ' || {table}.id || ')'
            FROM (
                SELECT id, min(id) OVER (PARTITION BY lower(name)) AS keeper FROM {table}
            ) named
            WHERE {table}.id = named.id AND named.id <> named.keeper
            """
        )
        op.create_index(f"uq_{table}_name", table, [sa.text("lower(name)")], unique=True)

    op.execute("UPDATE categories SET slug = 'category-' || id WHERE slug = ''")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_sites_name", table_name="sites")
    op.drop_index("uq_categories_name", table_name="categories")
