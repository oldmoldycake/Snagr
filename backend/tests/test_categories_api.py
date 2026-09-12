"""HTTP layer for /api/categories — the computed counts and name validation.

snagged_count means one thing across the app: per active listing take its
LATEST check, take the cheapest of those, and compare it to the CALLER's
target with `<=`. That is what serializers.ts:76 (via targetMet) reports, what
item_rollups' `target_met` puts on every item row, and what the dashboard's
snagged tile counts — so the category chip has to agree with the badge on the
items underneath it. The tests below are the four ways the old "any historical
check under anybody's target" query disagreed.

item_count stays instance-wide on purpose: `items` is the shared catalog, and
the mock's single-user store can't distinguish the two. Only snagged_count is
scoped to the caller.

Seeding here goes through `db_session` and COMMITS, like test_sites_api.py:
each request runs on its own session, so uncommitted rows are invisible.
"""

from contextlib import asynccontextmanager

import pytest
from app.models import User

from tests.conftest import CSRF
from tests.factories import Scenario

OWNER = {"email": "categories@example.com", "password": "hunter2hunter2"}


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


async def _categories_by_name(client) -> dict[str, dict]:
    """The list keyed by name, so tests don't depend on response order."""
    res = await client.get("/api/categories")
    assert res.status_code == 200, res.text
    return {c["name"]: c for c in res.json()["data"]}


# --- authentication -----------------------------------------------------------


async def test_categories_require_a_session(client):
    res = await client.get("/api/categories")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


# --- envelope + shape ---------------------------------------------------------


async def test_category_shape_and_plain_list_envelope(client, db_session):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        await sc.category()

    body = (await client.get("/api/categories")).json()

    assert list(body) == ["data"]
    (category,) = body["data"]
    assert set(category) == {"id", "name", "slug", "site_ids", "item_count", "snagged_count"}
    assert category["name"] == "Cameras"
    assert category["item_count"] == 0
    assert category["snagged_count"] == 0


# --- snagged_count ------------------------------------------------------------


async def test_snagged_count_counts_items_at_or_under_my_target(client, db_session):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        cheap = await sc.item("Cheap")
        pricey = await sc.item("Pricey")
        await sc.checks(await sc.listing(await sc.watch(cheap, "100.00"), cheap), (1, "80.00"))
        await sc.checks(await sc.listing(await sc.watch(pricey, "100.00"), pricey), (1, "150.00"))

    categories = await _categories_by_name(client)
    assert categories["Cameras"]["item_count"] == 2
    assert categories["Cameras"]["snagged_count"] == 1


async def test_snagged_count_ignores_a_dip_that_has_since_recovered(client, db_session):
    """Only the latest check per listing counts. A price that fell under target
    once and bounced back is not a snag you can act on today."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item = await sc.item()
        listing = await sc.listing(await sc.watch(item, "100.00"), item)
        await sc.checks(listing, (30, "80.00"), (1, "120.00"))

    assert (await _categories_by_name(client))["Cameras"]["snagged_count"] == 0


async def test_snagged_count_ignores_another_users_target(client, db_session):
    """`items` is shared catalog, targets are not — a stranger's generous
    target must never light up my category chip."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        stranger = await sc.other_user()
        item = await sc.item()
        await sc.checks(await sc.listing(await sc.watch(item, "50.00"), item), (1, "80.00"))
        their_watch = await sc.watch(item, "100.00", user=stranger)
        await sc.checks(await sc.listing(their_watch, item, "theirs"), (1, "80.00"))

    categories = await _categories_by_name(client)
    assert categories["Cameras"]["item_count"] == 1  # the catalog is shared
    assert categories["Cameras"]["snagged_count"] == 0  # their snag, not mine


async def test_snagged_count_includes_a_price_exactly_at_target(client, db_session):
    """`<=`, not `<` — hitting the number you asked for is the whole point."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item = await sc.item()
        await sc.checks(await sc.listing(await sc.watch(item, "100.00"), item), (1, "100.00"))

    assert (await _categories_by_name(client))["Cameras"]["snagged_count"] == 1


async def test_snagged_count_ignores_retired_listings(client, db_session):
    """A dead listing's last price is not something you can buy."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item = await sc.item()
        watch = await sc.watch(item, "100.00")
        await sc.checks(await sc.listing(watch, item, "gone", active=False), (1, "80.00"))
        await sc.checks(await sc.listing(watch, item, "live"), (1, "150.00"))

    assert (await _categories_by_name(client))["Cameras"]["snagged_count"] == 0


async def test_a_watch_without_a_target_is_never_snagged(client, db_session):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item = await sc.item()
        await sc.checks(await sc.listing(await sc.watch(item), item), (1, "80.00"))

    assert (await _categories_by_name(client))["Cameras"]["snagged_count"] == 0


async def test_snagged_counts_stay_inside_their_category(client, db_session):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        lenses = await sc.category("Lenses")
        camera = await sc.item("Camera")
        lens = await sc.item("Lens", category=lenses)
        await sc.checks(await sc.listing(await sc.watch(camera, "100.00"), camera), (1, "80.00"))
        await sc.checks(await sc.listing(await sc.watch(lens, "100.00"), lens), (1, "150.00"))

    categories = await _categories_by_name(client)
    assert categories["Cameras"]["snagged_count"] == 1
    assert categories["Lenses"]["snagged_count"] == 0


# --- POST /api/categories -----------------------------------------------------


async def test_create_category_derives_a_slug_and_trims_the_name(client):
    await _sign_in(client)

    res = await client.post("/api/categories", json={"name": "  Game Boy games  "}, headers=CSRF)

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "Game Boy games"
    assert body["slug"] == "game-boy-games"
    assert body["item_count"] == 0
    assert body["snagged_count"] == 0


@pytest.mark.parametrize("name", ["", "   "])
async def test_create_category_rejects_a_blank_name(client, name):
    """The mock trims before testing, so whitespace-only is blank too. The
    field message repeats the message — it is what the form renders."""
    await _sign_in(client)

    res = await client.post("/api/categories", json={"name": name}, headers=CSRF)

    assert res.status_code == 422, res.text
    error = res.json()["error"]
    assert error["code"] == "validation_error"
    assert error["message"] == "Name is required"
    assert error["fields"] == {"name": "Name is required"}


@pytest.mark.parametrize("name", ["Cameras", "  cameras  "])
async def test_create_category_rejects_a_duplicate_name(client, db_session, name):
    """Case-insensitive, on the trimmed name, and `duplicate` — not
    `validation_error`, which is what the form shows for a malformed field."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        await sc.category()

    res = await client.post("/api/categories", json={"name": name}, headers=CSRF)

    assert res.status_code == 422, res.text
    error = res.json()["error"]
    assert error["code"] == "duplicate"
    assert error["message"] == "A category with this name already exists"
    assert error["fields"] == {"name": "A category with this name already exists"}


# --- the write routes answer with the same counts ------------------------------


async def test_write_routes_return_the_callers_snagged_count(client, db_session):
    """PATCH and PUT answer with a full Category the client writes straight
    into its cache — a zero here blanks the chip until the next list refresh."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        category_id = (await sc.category()).id
        item = await sc.item()
        await sc.checks(await sc.listing(await sc.watch(item, "100.00"), item), (1, "80.00"))

    renamed = await client.patch(
        f"/api/categories/{category_id}", json={"name": "Bodies"}, headers=CSRF
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["snagged_count"] == 1

    sites = await client.put(
        f"/api/categories/{category_id}/sites", json={"site_ids": []}, headers=CSRF
    )
    assert sites.status_code == 200, sites.text
    assert sites.json()["snagged_count"] == 1
