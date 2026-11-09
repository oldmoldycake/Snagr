"""who created each category

Any signed-in user may now create a category, and its creator may rename it
and choose its sites; until now only an admin could do either. The new
column records the creator. Categories already in stay NULL — they were made
by an admin, and a category nobody created is one only an admin manages.

ON DELETE SET NULL, so deleting the creator's account leaves the category
for everyone else tracking items in it, back in an admin's hands.

Revision ID: 024
Revises: 023
Create Date: 2026-10-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "024"
down_revision: str | Sequence[str] | None = "023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "categories",
        sa.Column(
            "created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("categories", "created_by")
