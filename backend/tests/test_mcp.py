"""The MCP endpoint (POST /api/mcp) — the bearer gate, tool visibility per
scope and per setting, and each read tool's shape and error codes.

Tools run through fastmcp's own client over an in-process ASGI transport, so
the real auth middleware, the real services and the throwaway DB are all in
the loop. Seeding goes through the REST API where it can (categories, sites,
items, tokens) and through the Scenario factory where only the agent writes
(listings, price checks). Every tool error is asserted on the REST envelope
{"error": {code, ...}} that ApiErrorEnvelope puts in the tool error text.
"""

import asyncio
import json

import httpx2
import pytest
from app.config import settings
from app.main import app, mcp_app
from app.models import User
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from tests.conftest import CSRF
from tests.factories import Scenario

OWNER = {"email": "mcp@example.com", "password": "hunter2hunter2"}
STRANGER = {"email": "stranger@example.com", "password": "hunter2hunter2"}
MCP_URL = "http://test/api/mcp"
ACCEPT = {"Accept": "application/json, text/event-stream"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}

READ_TOOLS = {
    "get_instance",
    "whoami",
    "list_categories",
    "list_sites",
    "list_items",
    "get_item",
    "list_listings",
    "list_price_checks",
    "get_price_history",
    "get_price_summary",
    "get_dashboard_stats",
    "get_price_drops",
    "get_category_price_change",
    "list_runs",
    "get_run",
}
VISION_TOOLS = {"list_review_queue", "list_references"}


@pytest.fixture(scope="session", autouse=True)
async def _mcp_lifespan():
    """The MCP sub-app's lifespan (its session manager) for the whole run —
    the ASGI transport behind the `client` fixture never runs lifespans.
    It lives in its own task: the manager's task group is an anyio cancel
    scope, which must be exited by the task that entered it, and a fixture's
    setup and teardown are not guaranteed to share one."""
    started, stop = asyncio.Event(), asyncio.Event()

    async def runner():
        async with mcp_app.router.lifespan_context(mcp_app):
            started.set()
            await stop.wait()

    task = asyncio.create_task(runner())
    await started.wait()
    yield
    stop.set()
    await task


@pytest.fixture(autouse=True)
def _vision_off(monkeypatch):
    """Off is the documented default; a developer .env may say otherwise."""
    monkeypatch.setattr(settings, "VISION_SIDECAR_URL", None)


@pytest.fixture
def vision_on(monkeypatch):
    monkeypatch.setattr(settings, "VISION_SIDECAR_URL", "http://vision.test")


async def _sign_in(client, creds=OWNER) -> int:
    res = await client.post("/api/auth/register", json=creds, headers=CSRF)
    assert res.status_code == 201, res.text
    return res.json()["user"]["id"]


async def _token(client, scopes=("read",)) -> str:
    body = {"name": "agent", "scopes": list(scopes)}
    res = await client.post("/api/me/tokens", json=body, headers=CSRF)
    assert res.status_code == 201, res.text
    return res.json()["token"]


def _factory(headers=None, auth=None, timeout=None, **_):
    return httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://test",
        headers=headers,
        auth=auth,
        timeout=timeout,
    )


def _agent(token: str) -> Client:
    """What an MCP client looks like from the server's side: the endpoint URL
    and a bearer header, nothing else."""
    transport = StreamableHttpTransport(
        MCP_URL, headers={"Authorization": f"Bearer {token}"}, httpx_client_factory=_factory
    )
    return Client(transport)


async def _ok(agent: Client, name: str, **args):
    """A successful call's structured payload (list results come unwrapped)."""
    res = await agent.call_tool(name, args, raise_on_error=False)
    assert not res.is_error, res.content[0].text
    payload = res.structured_content
    return payload["result"] if set(payload) == {"result"} else payload


async def _error(agent: Client, name: str, **args) -> dict:
    """A failed call's REST envelope — the `error` object."""
    res = await agent.call_tool(name, args, raise_on_error=False)
    assert res.is_error, res.structured_content
    return json.loads(res.content[0].text)["error"]


async def _seed_listings(db_session, user_id: int):
    """Two watched items with one listing each — one live, one sold."""
    async with db_session() as session:
        sc = Scenario(session)
        owner = await session.get(User, user_id)
        cat = await sc.category()
        site = await sc.site(name="eBay")
        alpha = await sc.item("Alpha", cat)
        beta = await sc.item("Beta", cat)
        watch_a = await sc.watch(alpha, target_price="100.00", user=owner)
        watch_b = await sc.watch(beta, user=owner)
        live = await sc.listing(watch_a, alpha, site=site, title="Alpha, boxed")
        sold = await sc.listing(watch_b, beta, site=site, active=False)
        await sc.checks(live, (1, "90.00"))
        await sc.checks(sold, (2, "50.00"))
        await sc.commit()
        return cat.id, cat.slug, alpha.id, beta.id


# --- the gate -------------------------------------------------------------------


async def test_endpoint_requires_a_bearer(client):
    await _sign_in(client)  # a signed-in browser, cookie and all
    res = await client.post("/api/mcp", json=LIST_TOOLS, headers=ACCEPT)
    assert res.status_code == 401
    assert res.headers["www-authenticate"].startswith("Bearer")

    bad = {**ACCEPT, "Authorization": "Bearer nope"}
    assert (await client.post("/api/mcp", json=LIST_TOOLS, headers=bad)).status_code == 401


async def test_mcp_disabled_rejects_valid_tokens(client, monkeypatch):
    await _sign_in(client)
    token = await _token(client)
    headers = {**ACCEPT, "Authorization": f"Bearer {token}"}
    assert (await client.post("/api/mcp", json=LIST_TOOLS, headers=headers)).status_code == 200
    monkeypatch.setattr(settings, "MCP_ENABLED", False)
    assert (await client.post("/api/mcp", json=LIST_TOOLS, headers=headers)).status_code == 401


async def test_tool_list_follows_the_vision_setting(client, monkeypatch):
    await _sign_in(client)
    token = await _token(client)
    async with _agent(token) as agent:
        assert {t.name for t in await agent.list_tools()} == READ_TOOLS
        monkeypatch.setattr(settings, "VISION_SIDECAR_URL", "http://vision.test")
        assert {t.name for t in await agent.list_tools()} == READ_TOOLS | VISION_TOOLS


async def test_read_tools_are_annotated_read_only(client):
    await _sign_in(client)
    async with _agent(await _token(client)) as agent:
        for tool in await agent.list_tools():
            assert tool.annotations.read_only_hint is True, tool.name


# --- orientation ------------------------------------------------------------------


async def test_get_instance_and_whoami(client):
    await _sign_in(client)
    async with _agent(await _token(client, scopes=("read", "runs"))) as agent:
        instance = await _ok(agent, "get_instance")
        assert instance["mcp_enabled"] is True
        assert instance["vision_enabled"] is False

        me = await _ok(agent, "whoami")
        assert me["user"]["email"] == OWNER["email"]
        assert me["scopes"] == ["read", "runs"]


# --- catalog ------------------------------------------------------------------------


async def test_catalog_tools_mirror_rest(client):
    await _sign_in(client)
    cat = (await client.post("/api/categories", json={"name": "Cameras"}, headers=CSRF)).json()
    site_body = {"name": "eBay", "base_url": "https://ebay.com"}
    site = (await client.post("/api/sites", json=site_body, headers=CSRF)).json()
    res = await client.put(
        f"/api/categories/{cat['id']}/sites", json={"site_ids": [site["id"]]}, headers=CSRF
    )
    assert res.status_code == 200, res.text

    async with _agent(await _token(client)) as agent:
        (category,) = await _ok(agent, "list_categories")
        assert category["slug"] == "cameras"
        assert category["site_ids"] == [site["id"]]
        assert category["item_count"] == 0

        (listed_site,) = await _ok(agent, "list_sites")
        assert listed_site["base_url"] == "https://ebay.com"
        assert listed_site["category_ids"] == [cat["id"]]
        assert listed_site["listing_count"] == 0


# --- items --------------------------------------------------------------------------


async def test_items_by_category_slug_and_id(client):
    await _sign_in(client)
    cat = (await client.post("/api/categories", json={"name": "Cameras"}, headers=CSRF)).json()
    body = {"category_id": cat["id"], "name": "Leica M6", "target_price": "1500.00"}
    item = (await client.post("/api/items", json=body, headers=CSRF)).json()

    async with _agent(await _token(client)) as agent:
        page = await _ok(agent, "list_items", category="cameras")
        assert page["meta"]["total"] == 1
        (summary,) = page["data"]
        assert summary["name"] == "Leica M6"
        assert summary["target_price"] == "1500.00"  # a decimal string, never a number
        assert summary["active_listing_count"] == 0

        assert (await _ok(agent, "list_items", category=cat["id"]))["meta"]["total"] == 1
        assert (await _ok(agent, "list_items", search="nothing"))["meta"]["total"] == 0

        detail = await _ok(agent, "get_item", item=item["id"])
        assert detail["category_slug"] == "cameras"
        assert detail["listings"] == []

        assert (await _error(agent, "get_item", item=999))["code"] == "not_found"
        assert (await _error(agent, "list_items", category="nope"))["code"] == "not_found"
        assert (await _error(agent, "list_items", site="nowhere"))["code"] == "not_found"


async def test_listings_across_items(client, make_client, monkeypatch, db_session):
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
    user_id = await _sign_in(client)
    _cat_id, _slug, alpha_id, beta_id = await _seed_listings(db_session, user_id)

    async with _agent(await _token(client)) as agent:
        live = await _ok(agent, "list_listings")
        assert live["meta"]["total"] == 1
        (row,) = live["data"]
        assert row["item_id"] == alpha_id
        assert row["item_name"] == "Alpha"
        assert row["site_name"] == "eBay"
        assert row["latest_price"] == "90.00"
        assert row["active"] is True

        assert (await _ok(agent, "list_listings", active=None))["meta"]["total"] == 2
        (gone,) = (await _ok(agent, "list_listings", active=False))["data"]
        assert gone["item_id"] == beta_id
        assert (await _ok(agent, "list_listings", site="ebay"))["meta"]["total"] == 1
        assert (await _ok(agent, "list_listings", item=beta_id, active=None))["meta"]["total"] == 1

        checks = await _ok(agent, "list_price_checks", item=alpha_id)
        assert [c["price"] for c in checks] == ["90.00"]
        assert await _ok(agent, "list_price_checks", item=999) == []

    # another user's token sees none of it — hidden ≡ nonexistent
    stranger = await make_client()
    await _sign_in(stranger, STRANGER)
    async with _agent(await _token(stranger)) as agent:
        assert (await _ok(agent, "list_listings", active=None))["meta"]["total"] == 0
        assert (await _error(agent, "get_item", item=alpha_id))["code"] == "not_found"


# --- price intelligence -------------------------------------------------------------


async def test_price_tools(client, db_session):
    user_id = await _sign_in(client)
    cat_id, slug, alpha_id, _beta_id = await _seed_listings(db_session, user_id)

    async with _agent(await _token(client)) as agent:
        history = await _ok(agent, "get_price_history", item=alpha_id, range="30d")
        assert history["item_id"] == alpha_id
        assert history["target_price"] == "100.00"
        assert len(history["series"]) == 1

        summary = await _ok(agent, "get_price_summary", item=alpha_id)
        assert summary["range"] == "30d"
        assert isinstance(summary["points"], list)

        stats = await _ok(agent, "get_dashboard_stats", range="30d")
        assert isinstance(stats, dict) and stats

        drops = await _ok(agent, "get_price_drops", range="30d")
        assert isinstance(drops, list)

        change = await _ok(agent, "get_category_price_change", category=slug)
        assert change["category_id"] == cat_id
        assert isinstance(change["items"], list)

        assert (await _error(agent, "get_price_history", item=999))["code"] == "not_found"
        # an invalid range is rejected at the door, before any query runs
        res = await agent.call_tool(
            "get_price_history", {"item": alpha_id, "range": "2d"}, raise_on_error=False
        )
        assert res.is_error


# --- runs -----------------------------------------------------------------------------


async def test_run_visibility_matches_rest(client, make_client, monkeypatch):
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
    await _sign_in(client)  # the admin, whose run this is
    res = await client.post("/api/runs", json={"scope": "global"}, headers=CSRF)
    assert res.status_code == 202, res.text
    run_id = res.json()["run"]["id"]

    async with _agent(await _token(client)) as agent:
        runs = await _ok(agent, "list_runs")
        assert [r["id"] for r in runs["data"]] == [run_id]
        run = await _ok(agent, "get_run", run_id=run_id)
        assert run["status"] == "queued"
        assert run["scope_label"] == "Everything"
        assert run["events"] == []

    stranger = await make_client()
    await _sign_in(stranger, STRANGER)
    async with _agent(await _token(stranger)) as agent:
        assert (await _ok(agent, "list_runs"))["meta"]["total"] == 0
        assert (await _error(agent, "get_run", run_id=run_id))["code"] == "not_found"


# --- vision -----------------------------------------------------------------------------


async def test_vision_tools_when_on(client, vision_on):
    await _sign_in(client)
    async with _agent(await _token(client)) as agent:
        queue = await _ok(agent, "list_review_queue")
        assert queue == {"data": [], "meta": {"page": 1, "per_page": 25, "total": 0}}
        assert (await _error(agent, "list_references", item=999))["code"] == "not_found"
