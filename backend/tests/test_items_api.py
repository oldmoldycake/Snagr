"""HTTP layer for /api/items — the per-watch tracking fields.

allow_reproductions is the one tracking field the mock validated and then
dropped, so nothing pinned it end to end on either side (the mock now applies
it in POST and PATCH like its siblings). These tests hold the backend to the
same contract: it is written on create, changed on PATCH, and a JSON null or
an absent key leaves it alone — the "only non-null fields change" rule every
other field on ItemUpdateRequest follows.

Seeding here goes through `db_session` and COMMITS, like test_sites_api.py:
each request runs on its own session, so uncommitted rows are invisible.
"""

from contextlib import asynccontextmanager

import pytest
from app.models import User

from tests.conftest import CSRF
from tests.factories import Scenario

OWNER = {"email": "items@example.com", "password": "hunter2hunter2"}


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


async def _create(client, category_id, **overrides) -> dict:
    body = {
        "category_id": category_id,
        "name": "Alpha",
        "target_price": None,
    } | overrides
    res = await client.post("/api/items", json=body, headers=CSRF)
    assert res.status_code == 201, res.text
    return res.json()


# --- POST /api/items ----------------------------------------------------------


@pytest.mark.parametrize("allowed", [True, False])
async def test_create_item_stores_allow_reproductions(client, db_session, allowed):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        category_id = (await sc.category()).id

    created = await _create(client, category_id, allow_reproductions=allowed)

    assert created["allow_reproductions"] is allowed
    # and it stuck — the read path serializes the stored value, not the request
    detail = (await client.get(f"/api/items/{created['id']}")).json()
    assert detail["allow_reproductions"] is allowed


async def test_create_item_defaults_allow_reproductions_to_false(client, db_session):
    """Omitted means "screen for counterfeits" — the mock's `?? false`."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        category_id = (await sc.category()).id

    assert (await _create(client, category_id))["allow_reproductions"] is False


# --- PATCH /api/items/{item_id} -----------------------------------------------


@pytest.mark.parametrize("allowed", [True, False])
async def test_update_item_changes_allow_reproductions(client, db_session, allowed):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        category_id = (await sc.category()).id
    item_id = (await _create(client, category_id, allow_reproductions=not allowed))["id"]

    res = await client.patch(
        f"/api/items/{item_id}", json={"allow_reproductions": allowed}, headers=CSRF
    )

    assert res.status_code == 200, res.text
    assert res.json()["allow_reproductions"] is allowed
    detail = (await client.get(f"/api/items/{item_id}")).json()
    assert detail["allow_reproductions"] is allowed


@pytest.mark.parametrize("body", [{"name": "Renamed"}, {"allow_reproductions": None}])
async def test_update_item_leaves_allow_reproductions_alone(client, db_session, body):
    """Absent or null is "leave it" — a PATCH of some other field must not
    quietly re-enable counterfeit screening."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        category_id = (await sc.category()).id
    item_id = (await _create(client, category_id, allow_reproductions=True))["id"]

    res = await client.patch(f"/api/items/{item_id}", json=body, headers=CSRF)

    assert res.status_code == 200, res.text
    assert res.json()["allow_reproductions"] is True


# --- GET /api/items/{item_id}/price-checks ------------------------------------


async def _seed_checks(db_session, owner_id, *points, **kwargs):
    """One watched item with one listing carrying the given checks. Returns
    the item id."""
    async with _seed_for(db_session, owner_id) as sc:
        item = await sc.item()
        watch = await sc.watch(item=item)
        listing = await sc.listing(watch, item)
        await sc.checks(listing, *points, **kwargs)
    return item.id


async def test_price_checks_carry_how_each_price_was_read(client, db_session):
    owner_id = await _sign_in(client)
    item_id = await _seed_checks(db_session, owner_id, (1, "100.00"), method="jsonld")

    (check,) = (await client.get(f"/api/items/{item_id}/price-checks")).json()["data"]

    assert check["method"] == "jsonld"
    assert check["confirmed"] is True


async def test_an_unbelieved_reading_is_still_in_the_log(client, db_session):
    # hiding an observation is its own failure: the log shows what was seen,
    # flagged as the disbelieved reading it is
    owner_id = await _sign_in(client)
    item_id = await _seed_checks(db_session, owner_id, (1, "4.49"), confirmed=False)

    (check,) = (await client.get(f"/api/items/{item_id}/price-checks")).json()["data"]

    assert (check["price"], check["confirmed"]) == ("4.49", False)


async def test_an_unbelieved_reading_is_not_the_items_best_price(client, db_session):
    """The whole point of the confirm rule: a "$4.49" nobody trusts must not
    reach the board, the charts or a target-hit badge."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item = await sc.item()
        watch = await sc.watch(item=item, target_price="50.00")
        listing = await sc.listing(watch, item)
        await sc.checks(listing, (2, "100.00"))
        await sc.checks(listing, (1, "4.49"), confirmed=False)
        item_id = item.id

    summary = (await client.get(f"/api/items/{item_id}")).json()

    assert summary["best_price"] == "100.00"


async def test_an_unbelieved_reading_is_not_a_listings_current_price(client, db_session):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item = await sc.item()
        watch = await sc.watch(item=item)
        listing = await sc.listing(watch, item)
        await sc.checks(listing, (2, "100.00"))
        await sc.checks(listing, (1, "4.49"), confirmed=False)
        item_id = item.id

    (row,) = (await client.get(f"/api/items/{item_id}")).json()["listings"]

    assert row["latest_price"] == "100.00"


async def test_an_unbelieved_reading_still_counts_as_a_check_that_happened(client, db_session):
    # last_checked_at answers "when did we last look", which is true whether
    # or not the number that came back was believed
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item = await sc.item()
        watch = await sc.watch(item=item)
        listing = await sc.listing(watch, item)
        await sc.checks(listing, (5, "100.00"))
        await sc.checks(listing, (1, "4.49"), confirmed=False)
        item_id = item.id

    (row,) = (await client.get(f"/api/items/{item_id}")).json()["listings"]
    checks = (await client.get(f"/api/items/{item_id}/price-checks")).json()["data"]

    assert row["last_checked_at"] == max(c["checked_at"] for c in checks)


async def test_an_unbelieved_reading_is_absent_from_the_price_history(client, db_session):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item = await sc.item()
        watch = await sc.watch(item=item)
        listing = await sc.listing(watch, item)
        await sc.checks(listing, (5, "100.00"))
        await sc.checks(listing, (1, "4.49"), confirmed=False)
        item_id = item.id

    history = (await client.get(f"/api/items/{item_id}/price-history?range=30d")).json()
    prices = [
        point["price"]
        for series in history["series"]
        for point in series["points"]
        if point["price"] is not None
    ]

    assert prices and "4.49" not in prices
