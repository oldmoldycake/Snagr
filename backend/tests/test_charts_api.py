"""HTTP layer for the charts + dashboard routes.

test_aggregates.py proves the math. This file covers what only the router can
get wrong: auth, ownership 404s, response envelopes, and query params that reach
the service unvalidated.

Seeding here goes through `db_session` and COMMITS, because each request runs on
its own session — uncommitted rows would be invisible to the endpoint under test.
"""

from contextlib import asynccontextmanager

import pytest
from app.models import User

from tests.conftest import CSRF
from tests.factories import Scenario

OWNER = {"email": "charts@example.com", "password": "hunter2hunter2"}

# every authenticated chart route, for the blanket auth check
CHART_ROUTES = [
    "/api/items/1/price-history?range=30d",
    "/api/items/1/price-summary?range=30d",
    "/api/categories/1/price-change?range=30d",
    "/api/dashboard/stats?range=30d",
    "/api/dashboard/price-drops?range=30d",
]


async def _sign_in(client, creds=OWNER):
    """Register (which also signs in) and return the new user's id."""
    res = await client.post("/api/auth/register", json=creds, headers=CSRF)
    assert res.status_code == 201, res.text
    return res.json()["user"]["id"]


@asynccontextmanager
async def _seed_for(db_session, user_id):
    """Scenario bound to an already-registered user, committed on exit."""
    async with db_session() as session:
        scenario = Scenario(session)
        scenario._user = await session.get(User, user_id)
        yield scenario
        await session.commit()


async def _item_with_history(db_session, user_id, name="Alpha", target="85.00"):
    async with _seed_for(db_session, user_id) as sc:
        item, watch = await sc.tracked(name, target_price=target)
        listing = await sc.listing(watch, item)
        await sc.checks(listing, (40, "100.00"), (5, "80.00"))
        return item.id, (await sc.category()).id


# --- authentication -----------------------------------------------------------

@pytest.mark.parametrize("path", CHART_ROUTES)
async def test_chart_routes_require_a_session(client, path):
    res = await client.get(path)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


# --- ownership + 404s ---------------------------------------------------------

@pytest.mark.parametrize("route", ["price-history", "price-summary"])
async def test_unknown_item_is_404(client, route):
    await _sign_in(client)
    res = await client.get(f"/api/items/99999/{route}?range=30d")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("route", ["price-history", "price-summary"])
async def test_another_users_item_is_404_not_403(client, db_session, route):
    """An item you don't watch is indistinguishable from one that doesn't exist.

    403 would confirm the item is real, leaking the catalog of other accounts.
    """
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        stranger = await sc.other_user()
        item = await sc.item("Not Yours")
        their_watch = await sc.watch(item, user=stranger)
        await sc.listing(their_watch, item, "theirs")
        foreign_item_id = item.id

    res = await client.get(f"/api/items/{foreign_item_id}/{route}?range=30d")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


async def test_unknown_category_is_404(client):
    await _sign_in(client)
    res = await client.get("/api/categories/99999/price-change?range=30d")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


async def test_category_you_watch_nothing_in_is_empty_not_404(client, db_session):
    # The category exists; you just have no watches in it. That's an empty list.
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        empty = await sc.category("Lenses")
        empty_id = empty.id

    res = await client.get(f"/api/categories/{empty_id}/price-change?range=30d")
    assert res.status_code == 200
    assert res.json()["items"] == []


async def test_error_responses_use_the_error_envelope(client):
    """Never FastAPI's default {"detail": ...} — the client reads error.code."""
    await _sign_in(client)
    body = (await client.get("/api/categories/99999/price-change?range=30d")).json()
    assert "error" in body and "detail" not in body
    assert set(body["error"]) >= {"code", "message"}


# --- query parameters ---------------------------------------------------------

async def test_invalid_range_is_rejected(client):
    await _sign_in(client)
    res = await client.get("/api/dashboard/stats?range=banana")
    assert res.status_code == 422
    # NOTE: 422s come from FastAPI's own validation, which is not wired to the
    # error-envelope handler in main.py, so this body is {"detail": [...]}.
    # Documented rather than asserted — see the envelope gap in the test above.


@pytest.mark.parametrize("points", [0, -1, 99999])
async def test_degenerate_points_do_not_500(client, db_session, points):
    """Regression: `?points=0` divided by zero inside the bucket math.

    `points` reaches the service straight off the query string, so the guard
    lives there. Anything unusable is clamped, never fatal.
    """
    owner_id = await _sign_in(client)
    item_id, _ = await _item_with_history(db_session, owner_id)

    history = await client.get(f"/api/items/{item_id}/price-history?range=30d&points={points}")
    summary = await client.get(f"/api/items/{item_id}/price-summary?range=30d&points={points}")

    assert history.status_code == 200, history.text
    assert summary.status_code == 200, summary.text


async def test_price_drops_respects_limit(client, db_session):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        for name in ("Alpha", "Bravo"):
            item, watch = await sc.tracked(name)
            listing = await sc.listing(watch, item, name)
            await sc.checks(listing, (20, "100.00"), (10, "50.00"))

    everything = await client.get("/api/dashboard/price-drops?range=30d")
    capped = await client.get("/api/dashboard/price-drops?range=30d&limit=1")

    assert len(everything.json()["data"]) == 2
    assert len(capped.json()["data"]) == 1


# --- response envelopes -------------------------------------------------------
#
# Paginated = {data, meta}; plain list = {data: [...]}; everything else is a
# bare object. Getting this wrong breaks the client silently.

async def test_price_drops_uses_the_plain_list_envelope(client, db_session):
    owner_id = await _sign_in(client)
    await _item_with_history(db_session, owner_id)

    body = (await client.get("/api/dashboard/price-drops?range=30d")).json()

    assert list(body) == ["data"]
    assert isinstance(body["data"], list)


async def test_dashboard_stats_returns_all_four_tiles(client):
    await _sign_in(client)

    body = (await client.get("/api/dashboard/stats?range=30d")).json()

    assert set(body) == {"tracked_items", "active_listings", "price_drops", "snagged"}
    for tile in body.values():
        assert set(tile) == {"value", "delta", "spark"}
        assert len(tile["spark"]) == 12


async def test_price_history_response_shape(client, db_session):
    owner_id = await _sign_in(client)
    item_id, _ = await _item_with_history(db_session, owner_id)

    body = (await client.get(f"/api/items/{item_id}/price-history?range=30d")).json()

    assert body["item_id"] == item_id
    assert body["target_price"] == "85.00"      # decimal string, from the watch
    assert body["currency"] == "USD"
    assert body["range"] == "30d"
    assert len(body["series"]) == 1
    assert set(body["series"][0]) == {"listing_id", "site_name", "title", "active", "points"}


async def test_price_summary_response_shape(client, db_session):
    owner_id = await _sign_in(client)
    item_id, _ = await _item_with_history(db_session, owner_id)

    body = (await client.get(f"/api/items/{item_id}/price-summary?range=30d&points=4")).json()

    assert body["item_id"] == item_id
    assert body["target_price"] == "85.00"
    assert len(body["points"]) == 4
    assert set(body["points"][0]) == {"ts", "avg", "best"}


async def test_category_price_change_response_shape(client, db_session):
    owner_id = await _sign_in(client)
    item_id, category_id = await _item_with_history(db_session, owner_id)

    body = (await client.get(f"/api/categories/{category_id}/price-change?range=30d")).json()

    assert body["category_id"] == category_id
    assert body["range"] == "30d"
    assert len(body["items"]) == 1
    row = body["items"][0]
    assert set(row) == {"item_id", "name", "pct_change", "old_best", "new_best"}
    assert row["pct_change"] == "-20.00"        # 100.00 -> 80.00


async def test_target_price_is_null_not_zero_when_unset(client, db_session):
    # The contract uses null for "no target"; 0 would mean "free".
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item, watch = await sc.tracked("No Target", target_price=None)
        await sc.listing(watch, item)
        item_id = item.id

    body = (await client.get(f"/api/items/{item_id}/price-history?range=30d")).json()

    assert body["target_price"] is None
