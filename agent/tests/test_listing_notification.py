"""The listing.new enqueue that save_listing fires against a real Postgres:
a genuinely new row queues exactly one notification_outbox event, a
duplicate save (the uq_watch_site_url conflict path) queues nothing, and a
failed enqueue never changes what the tool returns to the model.

Same harness rules as test_target_notification.py: throwaway snagr_test DB,
one module-wide event loop, schema built here as a test affordance (D1
still holds). Don't run concurrently with backend/tests.
"""

import asyncio

import pytest
import tools
from database import (
    AsyncSessionLocal,
    Base,
    Categories,
    Items,
    NotificationOutbox,
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


async def _seed() -> tuple[int, int, int]:
    """One watch on one item on one site; returns (watch_id, item_id, site_id)."""
    async with AsyncSessionLocal() as session:
        user = User(email="owner@test.local")
        category = Categories(name="Games", slug="games")
        site = Sites(name="TestBay", base_url="https://example.test")
        session.add_all([user, category, site])
        await session.flush()
        item = Items(category_id=category.id, name="Widget")
        session.add(item)
        await session.flush()
        watch = Watches(user_id=user.id, item_id=item.id, target_price=100, notify=True)
        session.add(watch)
        await session.flush()
        ids = (watch.id, item.id, site.id)
        await session.commit()
        return ids


def _save(watch_id: int, item_id: int, site_id: int):
    return db(
        tools.save_listing(
            watch_id=watch_id,
            item_id=item_id,
            site_id=site_id,
            url=LISTING_URL,
            title="Widget, boxed",
            match_score=82,
            match_summary="complete in box, right region",
        )
    )


async def _read_outbox() -> list[dict]:
    async with AsyncSessionLocal() as session:
        # the mirror model carries only what the agent writes — status and
        # created_at are server-side, asserted in backend/tests instead
        rows = (await session.execute(select(NotificationOutbox))).scalars().all()
        return [{"user_id": r.user_id, "event": r.event, "payload": r.payload} for r in rows]


def test_a_new_listing_enqueues_with_the_full_payload():
    watch_id, item_id, site_id = db(_seed())

    listing_id = _save(watch_id, item_id, site_id)
    assert isinstance(listing_id, int)

    (row,) = db(_read_outbox())
    assert row == {
        "user_id": 1,
        "event": "listing.new",
        "payload": {
            "watch_id": watch_id,
            "item_id": item_id,
            "listing_id": listing_id,
            "site_id": site_id,
            "item_name": "Widget",
            "site_name": "TestBay",
            "listing_url": LISTING_URL,
            "title": "Widget, boxed",
            "match_score": 82,
            "match_summary": "complete in box, right region",
        },
    }


def test_a_duplicate_save_does_not_enqueue_again():
    watch_id, item_id, site_id = db(_seed())

    first = _save(watch_id, item_id, site_id)
    second = _save(watch_id, item_id, site_id)
    assert first == second  # the conflict path returns the existing id

    assert len(db(_read_outbox())) == 1


def test_a_failing_enqueue_still_returns_the_listing_id(monkeypatch):
    async def refuse(*args, **kwargs):
        return False

    monkeypatch.setattr(tools, "enqueue_new_listing", refuse)
    watch_id, item_id, site_id = db(_seed())

    listing_id = _save(watch_id, item_id, site_id)

    assert isinstance(listing_id, int)
    assert db(_read_outbox()) == []
