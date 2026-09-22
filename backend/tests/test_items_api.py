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


# --- the hunter starts on a new watch, and stops on an untracked listing --------


async def _catalog(client, sites=("eBay", "Mercari")) -> dict:
    """A category linked to `sites`; returns {"category_id", "site_ids"}."""
    cat = (await client.post("/api/categories", json={"name": "Handhelds"}, headers=CSRF)).json()
    site_ids = []
    for name in sites:
        body = {"name": name, "base_url": f"https://{name.lower()}.test"}
        site_ids.append((await client.post("/api/sites", json=body, headers=CSRF)).json()["id"])
    await client.put(
        f"/api/categories/{cat['id']}/sites", json={"site_ids": site_ids}, headers=CSRF
    )
    return {"category_id": cat["id"], "site_ids": site_ids}


async def test_a_new_watch_is_hunting_before_the_request_returns(client):
    """The queue rows are written in the same transaction as the watch: a
    watch nothing will ever look for is not a state this API can produce."""
    await _sign_in(client)
    catalog = await _catalog(client)
    body = {"category_id": catalog["category_id"], "name": "Game Boy Color", "target_price": None}
    item = (await client.post("/api/items", json=body, headers=CSRF)).json()

    jobs = (await client.get("/api/jobs", params={"item_id": item["id"]})).json()["data"]
    hunts = [j for j in jobs if j["kind"] == "hunt"]
    assert sorted(j["site_name"] for j in hunts) == ["Mercari", "eBay"]
    assert {j["reason"] for j in hunts} == {"created"}
    # and the market stats its prompts read from
    assert [j["kind"] for j in jobs if j["kind"] == "ground"] == ["ground"]


async def test_a_pinned_site_subset_is_what_gets_hunted(client):
    await _sign_in(client)
    catalog = await _catalog(client)
    body = {
        "category_id": catalog["category_id"],
        "name": "Game Boy Color",
        "target_price": None,
        "site_ids": [catalog["site_ids"][0]],
    }
    item = (await client.post("/api/items", json=body, headers=CSRF)).json()

    jobs = (await client.get("/api/jobs", params={"item_id": item["id"], "kind": "hunt"})).json()
    assert [j["site_name"] for j in jobs["data"]] == ["eBay"]


async def test_untracking_a_listing_takes_it_out_of_the_rotation(client, db_session):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item = await sc.item()
        watch = await sc.watch(item=item)
        listing = await sc.listing(watch, item)
        await sc.job(kind="recheck", watch=watch, status="pending", listing_id=listing.id)
        listing_id = listing.id

    await client.patch(f"/api/listings/{listing_id}", json={"active": False}, headers=CSRF)

    jobs = (await client.get("/api/jobs", params={"kind": "recheck"})).json()["data"]
    assert [j["status"] for j in jobs] == ["cancelled"]


async def test_tracking_it_again_puts_it_back(client, db_session):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item = await sc.item()
        watch = await sc.watch(item=item)
        listing = await sc.listing(watch, item, active=False)
        listing_id = listing.id

    await client.patch(f"/api/listings/{listing_id}", json={"active": True}, headers=CSRF)

    jobs = (await client.get("/api/jobs", params={"kind": "recheck", "status": "pending"})).json()
    assert [j["listing_id"] for j in jobs["data"]] == [listing_id]


async def test_a_listing_remembers_the_hunt_that_found_it(client, db_session):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item = await sc.item()
        watch = await sc.watch(item=item)
        job = await sc.job(watch=watch, status="done")
        listing = await sc.listing(watch, item)
        listing.discovered_by_job_id = job.id
        item_id, job_id = item.id, job.id

    (row,) = (await client.get(f"/api/items/{item_id}")).json()["listings"]
    assert row["discovered_by_job_id"] == job_id


async def test_the_item_page_says_what_happens_next(client, db_session):
    """The facts line is computed from the watch's jobs — nothing about it is
    stored, and nothing about it is on ItemSummary (list queries stay cheap)."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item = await sc.item()
        watch = await sc.watch(item=item)
        listing = await sc.listing(watch, item)
        await sc.job(watch=watch, status="done", days_ago=0, stats={"new_listings": 2})
        await sc.job(watch=watch, status="pending", days_ago=0, site_id=(await sc.site("B")).id)
        await sc.job(kind="recheck", watch=watch, status="running", listing_id=listing.id)
        item_id = item.id

    detail = (await client.get(f"/api/items/{item_id}")).json()

    assert detail["hunt"]["running"] is False
    assert detail["hunt"]["last_result"] == "found"
    assert detail["hunt"]["next_at"] is not None
    assert detail["hunt"]["slots_open"] == 2  # max_listings 3, one tracked
    assert detail["recheck"]["running"] == 1
    assert detail["recheck"]["interval_minutes"] == 30

    summary = (await client.get("/api/items")).json()["data"][0]
    assert "hunt" not in summary


async def test_a_watch_the_hunter_has_never_touched_says_so(client, db_session):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item = await sc.item()
        await sc.watch(item=item)
        item_id = item.id

    detail = (await client.get(f"/api/items/{item_id}")).json()

    assert detail["hunt"] == {
        "running": False,
        "next_at": None,
        "last_at": None,
        "last_result": None,
        "slots_open": 3,
    }
    assert detail["recheck"]["next_at"] is None
