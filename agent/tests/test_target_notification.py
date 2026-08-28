"""The target-hit push that save_price_check fires against a real Postgres:
the edge trigger only fires on a crossing, every gate (notify flag, target,
topic, stock, cooldown, unset server) stays silent, and a landed push stamps
the watch.

Same harness rules as test_save_listing_backstop.py: conftest rewrites
DATABASE_URL to the throwaway snagr_test, one module-wide event loop
(asyncpg connections are loop-bound), schema built here as a test affordance
(D1 still holds). Don't run concurrently with backend/tests. ntfy itself is
faked at the HTTP layer via httpx.MockTransport, as in
test_check_images_tool.py.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import notify
import pytest
import tools
from database import (
    AsyncSessionLocal,
    Base,
    Categories,
    Items,
    Listings,
    PriceChecks,
    Sites,
    User,
    Watches,
    engine,
)
from sqlalchemy import select, text

NTFY = "http://ntfy.test"
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


@pytest.fixture(autouse=True)
def _ntfy_url(monkeypatch):
    monkeypatch.setattr(notify, "NTFY_SERVER_URL", NTFY)


@pytest.fixture
def pushes(monkeypatch):
    """Route the push through a MockTransport and collect what was sent."""
    sent: list[httpx.Request] = []
    real_client = httpx.AsyncClient

    def handler(request):
        sent.append(request)
        return httpx.Response(200)

    def _factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)
    return sent


async def _seed(
    target_price: float | None = 100,
    notify_enabled: bool = True,
    ntfy_topic: str | None = "snagr-owner",
    last_notified_at: datetime | None = None,
    prior_price: float | None = None,
    rival_price: float | None = None,
) -> int:
    """One watch on one item, with a listing to check. prior_price seeds an
    earlier check on that same listing; rival_price seeds a second active
    listing on the same watch. Returns the listing id to price-check."""
    async with AsyncSessionLocal() as session:
        user = User(email="owner@test.local", ntfy_topic=ntfy_topic)
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


async def _last_notified_at() -> datetime | None:
    async with AsyncSessionLocal() as session:
        return await session.scalar(select(Watches.last_notified_at))


def test_first_price_under_target_pushes(pushes):
    listing_id = db(_seed())

    assert _check(listing_id).startswith("Successfully")

    assert len(pushes) == 1
    request = pushes[0]
    assert str(request.url) == f"{NTFY}/snagr-owner"
    assert request.headers["Click"] == LISTING_URL
    assert request.content.decode() == "Widget — 90.00 USD on TestBay (target 100.00)"
    assert db(_last_notified_at()) is not None


def test_crossing_down_from_above_target_pushes(pushes):
    listing_id = db(_seed(prior_price=120))

    _check(listing_id)

    assert len(pushes) == 1


def test_a_watch_already_at_target_stays_quiet(pushes):
    # a second listing on the same watch is already under target, so this
    # check is not a crossing — the owner was told when that one landed
    listing_id = db(_seed(rival_price=95))

    _check(listing_id)

    assert pushes == []
    assert db(_last_notified_at()) is None


def test_price_above_target_stays_quiet(pushes):
    listing_id = db(_seed())

    _check(listing_id, price=110)

    assert pushes == []


def test_out_of_stock_bargain_stays_quiet(pushes):
    listing_id = db(_seed())

    _check(listing_id, in_stock=False)

    assert pushes == []


def test_priceless_check_stays_quiet(pushes):
    listing_id = db(_seed())

    _check(listing_id, price=None)

    assert pushes == []


def test_notifications_off_for_the_watch_stays_quiet(pushes):
    listing_id = db(_seed(notify_enabled=False))

    _check(listing_id)

    assert pushes == []


def test_no_target_price_stays_quiet(pushes):
    listing_id = db(_seed(target_price=None))

    _check(listing_id)

    assert pushes == []


def test_owner_without_a_topic_stays_quiet(pushes):
    listing_id = db(_seed(ntfy_topic=None))

    _check(listing_id)

    assert pushes == []


def test_cooldown_suppresses_a_second_crossing(pushes):
    listing_id = db(_seed(prior_price=120, last_notified_at=datetime.now(UTC) - timedelta(hours=1)))

    _check(listing_id)

    assert pushes == []


def test_cooldown_elapsed_pushes_again(pushes):
    listing_id = db(_seed(prior_price=120, last_notified_at=datetime.now(UTC) - timedelta(days=2)))

    _check(listing_id)

    assert len(pushes) == 1


def test_unconfigured_server_never_calls_ntfy(pushes, monkeypatch):
    monkeypatch.setattr(notify, "NTFY_SERVER_URL", None)
    listing_id = db(_seed())

    assert _check(listing_id).startswith("Successfully")

    assert pushes == []


def test_a_failing_push_still_records_the_price_check(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("ntfy is down")

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)),
    )
    listing_id = db(_seed())

    assert _check(listing_id).startswith("Successfully")

    assert db(_last_notified_at()) is None
