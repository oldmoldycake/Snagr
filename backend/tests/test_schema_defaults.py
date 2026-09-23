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

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


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


async def test_a_job_is_born_pending_and_due_now(sc):
    """Migration 015 gives jobs every default the queue reads.

    The agent inserts a successor recheck with nothing but its target, so a
    missing DEFAULT on status, run_after, priority or attempts would either
    reject the insert or hand the claim query a row it can never sort."""
    item = await sc.item()
    watch = await sc.watch(item=item)

    await sc.db.execute(
        text("INSERT INTO jobs (kind, watch_id, item_id) VALUES ('hunt', :w, :i)"),
        {"w": watch.id, "i": item.id},
    )

    row = (
        await sc.db.execute(
            text("SELECT status, priority, attempts, last_seq, run_after <= now() FROM jobs")
        )
    ).one()

    assert row == ("pending", 0, 0, 0, True)


async def test_a_site_starts_with_no_errors_and_no_pause(sc):
    """Migration 015 gives consecutive_errors DEFAULT 0, NOT NULL — the
    breaker counts up from it, and a null would make "five in a row" never
    arrive."""
    await sc.db.execute(
        text("INSERT INTO sites (name, base_url) VALUES ('fresh.test', 'https://fresh.test')")
    )

    row = (
        await sc.db.execute(
            text(
                "SELECT consecutive_errors, paused_until, paused_reason "
                "FROM sites WHERE name = 'fresh.test'"
            )
        )
    ).one()

    assert row == (0, None, None)


async def test_a_price_check_is_believed_by_default(sc):
    """Migration 014 gives the column DEFAULT true.

    The agent writes `confirmed` explicitly, but everything else that ever
    inserts a check — a backfill, a psql session, a future component — should
    land on "believed", because that is what every row written before the
    confirm rule existed was.
    """
    item = await sc.item()
    listing = await sc.listing(await sc.watch(item=item), item)

    await sc.db.execute(
        text(
            "INSERT INTO price_checks (listing_id, currency, checked_at) VALUES (:l, 'USD', now())"
        ),
        {"l": listing.id},
    )

    assert await sc.db.scalar(text("SELECT confirmed FROM price_checks")) is True


async def test_a_listing_starts_with_no_locator_and_no_failures(sc):
    """Migration 014 gives locator_failures DEFAULT 0 and static_ok DEFAULT
    false, both NOT NULL — a null failure count would make the
    "clear it after three misses" arithmetic silently do nothing."""
    item = await sc.item()
    watch = await sc.watch(item=item)

    # `active` is spelled out because it has no server default of its own —
    # a separate gap, left alone here rather than fixed in passing
    await sc.db.execute(
        text(
            "INSERT INTO listings (watch_id, item_id, site_id, url, active) "
            "VALUES (:w, :i, :s, 'https://example.test/raw', true)"
        ),
        {"w": watch.id, "i": item.id, "s": (await sc.site()).id},
    )

    row = (
        await sc.db.execute(
            text(
                "SELECT price_locator, locator_kind, locator_verified_at, "
                "locator_failures, static_ok FROM listings WHERE url = 'https://example.test/raw'"
            )
        )
    ).one()

    assert row == (None, None, None, 0, False)


async def test_a_watch_starts_on_the_instance_interval(sc):
    """Migration 017's recheck_interval_minutes has no default on either side:
    null is the value that means "the instance's RECHECK_INTERVAL_MINUTES".
    Built through the factory — watches has several NOT NULL columns with
    only an ORM default, and none of them is what this is about."""
    watch = await sc.watch(item=await sc.item())

    assert (
        await sc.db.scalar(
            text("SELECT recheck_interval_minutes FROM watches WHERE id = :w"), {"w": watch.id}
        )
        is None
    )


async def test_a_listing_only_ends_for_a_known_reason(sc):
    """Migration 017's CHECK: inactive_reason is null or one of five words —
    the item page and the Activity feed switch on it."""
    item = await sc.item()
    watch = await sc.watch(item=item)
    params = {"w": watch.id, "i": item.id, "s": (await sc.site()).id}

    await sc.db.execute(
        text(
            "INSERT INTO listings (watch_id, item_id, site_id, url, active, inactive_reason) "
            "VALUES (:w, :i, :s, 'https://example.test/sold', false, 'sold')"
        ),
        params,
    )
    with pytest.raises(IntegrityError):
        await sc.db.execute(
            text(
                "INSERT INTO listings (watch_id, item_id, site_id, url, active, inactive_reason) "
                "VALUES (:w, :i, :s, 'https://example.test/gone', false, 'gone')"
            ),
            params,
        )
