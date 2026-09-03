"""The target-hit enqueue that save_price_check fires against a real Postgres:
the edge trigger only fires on a crossing, every gate (notify flag, target,
stock, cooldown) stays quiet, and a successful enqueue stamps the watch.

The agent only writes notification_outbox rows now — the backend's dispatcher
owns delivery — so these tests assert rows and payloads, not HTTP.

Same harness rules as test_save_listing_backstop.py: conftest rewrites
DATABASE_URL to the throwaway snagr_test, one module-wide event loop
(asyncpg connections are loop-bound), schema built here as a test affordance
(D1 still holds). Don't run concurrently with backend/tests.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import notify
import pytest
import tools
from database import (
    AsyncSessionLocal,
    Base,
    Categories,
    Items,
    Listings,
    NotificationOutbox,
    PriceChecks,
    Sites,
    User,
    Watches,
    engine,
)
from sqlalchemy import select, text

LISTING_URL = "https://example.test/listing"

_ALL_TABLES = ", ".join(t.name for t in Base.metadata.sorted_tables)

_LOOP = asyncio.new_event_loop()


def db(coro):
    """Run one coroutine on the module's shared event loop."""
    return _LOOP.run_until_complete(coro)


async def _create_schema():
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f"DROP TABLE IF EXISTS {table.name} CASCADE"))
        await conn.run_sync(Base.metadata.create_all)


async def _drop_schema():
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f"DROP TABLE IF EXISTS {table.name} CASCADE"))


async def _truncate():
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {_ALL_TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="module", autouse=True)
def _schema():
    db(_create_schema())
    yield
    db(_drop_schema())
    db(engine.dispose())
    _LOOP.close()


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    db(_truncate())


async def _seed(
    target_price: float | None = 100,
    notify_enabled: bool = True,
    last_notified_at: datetime | None = None,
    prior_price: float | None = None,
    rival_price: float | None = None,
) -> int:
    """One watch on one item, with a listing to check. prior_price seeds an
    earlier check on that same listing; rival_price seeds a second active
    listing on the same watch. Returns the listing id to price-check."""
    async with AsyncSessionLocal() as session:
        user = User(email="owner@test.local")
        category = Categories(name="Games", slug="games")
        site = Sites(name="TestBay", base_url="https://example.test")
        session.add_all([user, category, site])
        await session.flush()
        item = Items(category_id=category.id, name="Widget")
        session.add(item)
        await session.flush()
        watch = Watches(
            user_id=user.id,
            item_id=item.id,
            target_price=target_price,
            notify=notify_enabled,
            last_notified_at=last_notified_at,
        )
        session.add(watch)
        await session.flush()
        listing = Listings(
            watch_id=watch.id, item_id=item.id, site_id=site.id, url=LISTING_URL, active=True
        )
        session.add(listing)
        await session.flush()

        earlier = datetime.now(UTC) - timedelta(days=7)
        if prior_price is not None:
            session.add(
                PriceChecks(
                    listing_id=listing.id, price=prior_price, in_stock=True, checked_at=earlier
                )
            )
        if rival_price is not None:
            rival = Listings(
                watch_id=watch.id,
                item_id=item.id,
                site_id=site.id,
                url=f"{LISTING_URL}/rival",
                active=True,
            )
            session.add(rival)
            await session.flush()
            session.add(
                PriceChecks(
                    listing_id=rival.id, price=rival_price, in_stock=True, checked_at=earlier
                )
            )

        listing_id = listing.id
        await session.commit()
        return listing_id


def _check(listing_id: int, price: float | None = 90, in_stock: bool = True) -> str:
    return db(
        tools.save_price_check(listing_id=listing_id, in_stock=in_stock, status="ok", price=price)
    )


async def _read_outbox() -> list[dict]:
    async with AsyncSessionLocal() as session:
        # the mirror model carries only what the agent writes — status and
        # created_at are server-side, asserted in backend/tests instead
        rows = (await session.execute(select(NotificationOutbox))).scalars().all()
        return [{"user_id": r.user_id, "event": r.event, "payload": r.payload} for r in rows]


async def _last_notified_at() -> datetime | None:
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(Watches.last_notified_at))


def test_first_price_under_target_enqueues():
    listing_id = db(_seed())

    assert _check(listing_id).startswith("Successfully")

    (row,) = db(_read_outbox())
    assert row == {
        "user_id": 1,
        "event": "target.hit",
        "payload": {
            "watch_id": 1,
            "item_id": 1,
            "listing_id": listing_id,
            "site_id": 1,
            "item_name": "Widget",
            "site_name": "TestBay",
            "listing_url": LISTING_URL,
            "price": "90.00",
            "currency": "USD",
            "target_price": "100.00",
        },
    }
    # the cooldown stamp lands at enqueue — no dispatcher ran here
    assert db(_last_notified_at()) is not None


def test_crossing_down_from_above_target_enqueues():
    listing_id = db(_seed(prior_price=120))

    _check(listing_id)

    assert len(db(_read_outbox())) == 1


def test_a_watch_already_at_target_stays_quiet():
    # a second listing on the same watch is already under target, so this
    # check is not a crossing — the owner was told when that one landed
    listing_id = db(_seed(rival_price=95))

    _check(listing_id)

    assert db(_read_outbox()) == []
    assert db(_last_notified_at()) is None


def test_price_above_target_stays_quiet():
    listing_id = db(_seed())

    _check(listing_id, price=110)

    assert db(_read_outbox()) == []


def test_out_of_stock_bargain_stays_quiet():
    listing_id = db(_seed())

    _check(listing_id, in_stock=False)

    assert db(_read_outbox()) == []


def test_priceless_check_stays_quiet():
    listing_id = db(_seed())

    _check(listing_id, price=None)

    assert db(_read_outbox()) == []


def test_notifications_off_for_the_watch_stays_quiet():
    listing_id = db(_seed(notify_enabled=False))

    _check(listing_id)

    assert db(_read_outbox()) == []


def test_no_target_price_stays_quiet():
    listing_id = db(_seed(target_price=None))

    _check(listing_id)

    assert db(_read_outbox()) == []


def test_a_channelless_owner_still_enqueues():
    # channel eligibility is the dispatcher's business, not the agent's: the
    # event is recorded either way and a channel-less owner's row simply gets
    # marked 'skipped' backend-side (the old owner-without-a-topic gate died
    # with the ntfy port)
    listing_id = db(_seed())

    _check(listing_id)

    assert len(db(_read_outbox())) == 1


def test_cooldown_suppresses_a_second_crossing():
    listing_id = db(_seed(prior_price=120, last_notified_at=datetime.now(UTC) - timedelta(hours=1)))

    _check(listing_id)

    assert db(_read_outbox()) == []


def test_cooldown_elapsed_enqueues_again():
    listing_id = db(_seed(prior_price=120, last_notified_at=datetime.now(UTC) - timedelta(days=2)))

    _check(listing_id)

    assert len(db(_read_outbox())) == 1


def test_a_failing_enqueue_still_records_the_price_check(monkeypatch):
    async def refuse(user_id, event, payload):
        return False

    monkeypatch.setattr(notify, "enqueue_notification", refuse)
    listing_id = db(_seed())

    assert _check(listing_id).startswith("Successfully")

    # not told = not stamped: the next crossing may try again
    assert db(_last_notified_at()) is None

    async def _count_checks():
        async with AsyncSessionLocal() as session:
            return len((await session.execute(select(PriceChecks))).scalars().all())

    assert db(_count_checks()) == 1
