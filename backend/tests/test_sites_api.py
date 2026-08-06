"""HTTP layer for /api/sites.

The GET tests characterize list_sites (written before its rework, so the
refactor had to preserve them); the PATCH tests assert the mock's contract
and were written failing-first against the update_site bugs.

The computed fields mirror the mock's toSite() (frontend/src/mocks/serializers.ts):
listing_count counts ACTIVE listings only, while last_checked_at scans checks on
ALL listings — inactive and unpriced ones included.

Seeding here goes through `db_session` and COMMITS, because each request runs on
its own session — uncommitted rows would be invisible to the endpoint under test.
"""

from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from app.models import SiteCategories, User

from tests.conftest import CSRF
from tests.factories import Scenario

OWNER = {"email": "sites@example.com", "password": "hunter2hunter2"}


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


async def _sites_by_name(client) -> dict[str, dict]:
    """The list keyed by name, so tests don't depend on response order."""
    res = await client.get("/api/sites")
    assert res.status_code == 200, res.text
    return {s["name"]: s for s in res.json()["data"]}


# --- authentication -----------------------------------------------------------


async def test_sites_require_a_session(client):
    res = await client.get("/api/sites")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


# --- envelope + shape ---------------------------------------------------------


async def test_no_sites_is_an_empty_data_list(client):
    await _sign_in(client)
    body = (await client.get("/api/sites")).json()
    assert body == {"data": []}


async def test_site_shape_and_plain_list_envelope(client, db_session):
    """A site with no listings/categories/checks: every computed field at its
    zero value — 0 / [] / null, never missing and never a fake default."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        await sc.site()

    body = (await client.get("/api/sites")).json()

    assert list(body) == ["data"]
    (site,) = body["data"]
    assert set(site) == {
        "id",
        "name",
        "base_url",
        "category_ids",
        "listing_count",
        "last_checked_at",
        "created_at",
    }
    assert site["name"] == "TestBay"
    assert site["base_url"] == "https://example.test"
    assert site["listing_count"] == 0
    assert site["category_ids"] == []
    assert site["last_checked_at"] is None
    datetime.fromisoformat(site["created_at"])  # ISO-8601, or this raises


# --- listing_count ------------------------------------------------------------


async def test_listing_count_counts_only_active_listings(client, db_session):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item, watch = await sc.tracked()
        await sc.listing(watch, item, "live")
        await sc.listing(watch, item, "gone", active=False)

    sites = await _sites_by_name(client)
    assert sites["TestBay"]["listing_count"] == 1


async def test_counts_span_all_users(client, db_session):
    """Sites are shared catalog: the aggregates include other users' watches,
    like categories' global item_count. handlers.ts runs a single-user store so
    the mock can't express this either way — pinned on the catalog precedent.
    """
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        stranger = await sc.other_user()
        item = await sc.item()
        their_watch = await sc.watch(item, user=stranger)
        their_listing = await sc.listing(their_watch, item, "theirs")
        await sc.checks(their_listing, (3, "75.00"))
        their_ts = sc.ago(3)

    sites = await _sites_by_name(client)
    assert sites["TestBay"]["listing_count"] == 1
    assert datetime.fromisoformat(sites["TestBay"]["last_checked_at"]) == their_ts


# --- last_checked_at ----------------------------------------------------------


async def test_last_checked_at_sees_inactive_listings(client, db_session):
    """listing_count filters on active; last_checked_at deliberately does NOT —
    a check on a now-dead listing is still the site's most recent visit."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item, watch = await sc.tracked()
        live = await sc.listing(watch, item, "live")
        gone = await sc.listing(watch, item, "gone", active=False)
        await sc.checks(live, (10, "100.00"))
        await sc.checks(gone, (2, "90.00"))  # newer, but on the inactive listing
        newest = sc.ago(2)

    sites = await _sites_by_name(client)
    assert datetime.fromisoformat(sites["TestBay"]["last_checked_at"]) == newest


async def test_last_checked_at_counts_unpriced_checks(client, db_session):
    """price=None means sold/unavailable — still a check, still bumps the clock."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item, watch = await sc.tracked()
        listing = await sc.listing(watch, item)
        await sc.checks(listing, (10, "100.00"), (1, None))
        newest = sc.ago(1)

    sites = await _sites_by_name(client)
    assert datetime.fromisoformat(sites["TestBay"]["last_checked_at"]) == newest


async def test_last_checked_at_is_null_before_any_check(client, db_session):
    """A listing the agent hasn't visited yet: null, not epoch or empty string."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item, watch = await sc.tracked()
        await sc.listing(watch, item)

    sites = await _sites_by_name(client)
    assert sites["TestBay"]["last_checked_at"] is None


# --- category_ids -------------------------------------------------------------


async def test_category_ids_reflect_site_categories(client, db_session):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        site = await sc.site()
        cameras = await sc.category()
        lenses = await sc.category("Lenses")
        await sc.category("Unlinked")
        sc.db.add(SiteCategories(site_id=site.id, category_id=cameras.id))
        sc.db.add(SiteCategories(site_id=site.id, category_id=lenses.id))
        linked = {cameras.id, lenses.id}

    sites = await _sites_by_name(client)
    # sorted(): the pre-rework route doesn't order these; the mock is ascending
    assert sorted(sites["TestBay"]["category_ids"]) == sorted(linked)


# --- multiple sites -----------------------------------------------------------


async def test_aggregates_do_not_bleed_between_sites(client, db_session):
    """Each site's count/timestamp comes only from its own listings."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item, watch = await sc.tracked()
        testbay = await sc.site()
        rival = await sc.site("Rivalmart")
        a1 = await sc.listing(watch, item, "a1", site=testbay)
        await sc.listing(watch, item, "a2", site=testbay)
        b1 = await sc.listing(watch, item, "b1", site=rival)
        await sc.checks(a1, (5, "100.00"))
        await sc.checks(b1, (1, "50.00"))
        testbay_ts, rival_ts = sc.ago(5), sc.ago(1)

    sites = await _sites_by_name(client)
    assert sites["TestBay"]["listing_count"] == 2
    assert sites["Rivalmart"]["listing_count"] == 1
    assert datetime.fromisoformat(sites["TestBay"]["last_checked_at"]) == testbay_ts
    assert datetime.fromisoformat(sites["Rivalmart"]["last_checked_at"]) == rival_ts


# --- POST /api/sites ----------------------------------------------------------


async def test_create_site_requires_a_session(client):
    res = await client.post(
        "/api/sites", json={"name": "X", "base_url": "https://x.test"}, headers=CSRF
    )
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


async def test_create_site_requires_the_csrf_header(client):
    await _sign_in(client)
    res = await client.post("/api/sites", json={"name": "X", "base_url": "https://x.test"})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "csrf"


async def test_create_site_returns_the_new_site_with_zeroed_aggregates(client):
    """A brand-new site can't have listings/categories/checks yet — 0 / [] / null."""
    await _sign_in(client)

    res = await client.post(
        "/api/sites", json={"name": "NewBay", "base_url": "https://newbay.test"}, headers=CSRF
    )

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == "NewBay"
    assert body["base_url"] == "https://newbay.test"
    assert body["listing_count"] == 0
    assert body["category_ids"] == []
    assert body["last_checked_at"] is None
    datetime.fromisoformat(body["created_at"])  # ISO-8601, or this raises

    # and it shows up in the list
    sites = await _sites_by_name(client)
    assert sites["NewBay"]["id"] == body["id"]


async def test_create_site_normalizes_inputs_like_the_mock(client):
    """toSite parity: both fields trimmed, base_url loses one trailing slash."""
    await _sign_in(client)

    res = await client.post(
        "/api/sites",
        json={"name": "  Padded  ", "base_url": "  https://padded.test/  "},
        headers=CSRF,
    )

    assert res.status_code == 201, res.text
    assert res.json()["name"] == "Padded"
    assert res.json()["base_url"] == "https://padded.test"


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "   "},
        {"base_url": ""},
        {"base_url": "   "},
    ],
)
async def test_create_site_rejects_blank_fields(client, overrides):
    """The mock 422s on empty OR whitespace-only — it trims before checking."""
    await _sign_in(client)
    body = {"name": "Valid", "base_url": "https://valid.test"} | overrides

    res = await client.post("/api/sites", json=body, headers=CSRF)

    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "validation_error"


# --- PATCH /api/sites/{site_id} -----------------------------------------------


async def test_update_site_requires_a_session(client):
    res = await client.patch("/api/sites/1", json={"name": "X"}, headers=CSRF)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


async def test_update_site_requires_the_csrf_header(client):
    await _sign_in(client)
    res = await client.patch("/api/sites/1", json={"name": "X"})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "csrf"


async def test_update_unknown_site_is_404(client):
    await _sign_in(client)
    res = await client.patch("/api/sites/99999", json={"name": "X"}, headers=CSRF)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


async def test_update_site_returns_computed_fields_not_zeros(client, db_session):
    """PATCH answers with toSite() like the mock — the client writes this
    payload straight into its cache, so hardcoded zeros blank out real counts."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        site = await sc.site()
        cameras = await sc.category()
        sc.db.add(SiteCategories(site_id=site.id, category_id=cameras.id))
        item, watch = await sc.tracked()
        listing = await sc.listing(watch, item)
        await sc.checks(listing, (3, "75.00"))
        site_id, camera_id, checked = site.id, cameras.id, sc.ago(3)

    res = await client.patch(f"/api/sites/{site_id}", json={"name": "Renamed"}, headers=CSRF)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "Renamed"
    assert body["listing_count"] == 1
    assert body["category_ids"] == [camera_id]
    assert datetime.fromisoformat(body["last_checked_at"]) == checked


async def test_update_site_normalizes_inputs_like_the_mock(client, db_session):
    """toSite parity: both fields are trimmed, base_url loses a trailing slash."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        site_id = (await sc.site()).id

    res = await client.patch(
        f"/api/sites/{site_id}",
        json={"name": "  NewBay  ", "base_url": "https://newbay.test/"},
        headers=CSRF,
    )

    assert res.status_code == 200, res.text
    assert res.json()["name"] == "NewBay"
    assert res.json()["base_url"] == "https://newbay.test"

    # and it stuck — the list reflects the same values
    sites = await _sites_by_name(client)
    assert sites["NewBay"]["base_url"] == "https://newbay.test"


async def test_update_site_ignores_empty_strings(client, db_session):
    """The mock skips falsy fields — {"name": ""} is a no-op, not a wipe."""
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        site_id = (await sc.site()).id

    res = await client.patch(f"/api/sites/{site_id}", json={"name": ""}, headers=CSRF)

    assert res.status_code == 200, res.text
    assert res.json()["name"] == "TestBay"
