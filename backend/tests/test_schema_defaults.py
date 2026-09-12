"""Column defaults that have to live in the DB, not only in Python.

A `default=` on a mapped_column is applied by SQLAlchemy when the ORM builds
the INSERT; it puts no DEFAULT on the column. The migrations do declare one
(`server_default=sa.text("true")`), so a model missing it describes a table
the migrations never build — conftest's create_all schema then diverges from a
migrated database, and anything inserting outside the ORM (psql, the agent's
raw SQL, a future `INSERT ... SELECT`) hits a NOT NULL violation on a column
the real deployment fills in for it.

These tests INSERT with raw SQL precisely to skip the ORM's default.
"""

from sqlalchemy import text


async def test_notification_channels_are_enabled_by_default(sc):
    """Migration 010 gives the column DEFAULT true."""
    user = await sc.user()

    await sc.db.execute(
        text(
            "INSERT INTO notification_channels (user_id, kind, name) VALUES (:u, 'ntfy', 'Phone')"
        ),
        {"u": user.id},
    )

    assert await sc.db.scalar(text("SELECT enabled FROM notification_channels")) is True


async def test_run_schedules_are_enabled_by_default(sc):
    """Migration 006 gives the column DEFAULT true."""
    await sc.db.execute(
        text(
            "INSERT INTO run_schedules (scope, scope_label, next_due_at) "
            "VALUES ('global', 'Everything', now())"
        )
    )

    assert await sc.db.scalar(text("SELECT enabled FROM run_schedules")) is True
