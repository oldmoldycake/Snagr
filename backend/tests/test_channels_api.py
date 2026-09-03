"""HTTP layer for /api/me/channels — status codes and error.codes as
frontend/src/mocks/handlers.ts defines them.

The two branches the mock can't exercise (its instance always has a ntfy
server) are pinned here instead: 422 no_server on creating/testing a ntfy
channel while NTFY_SERVER_URL is unset, and 502 channel_failed when a test
send's destination rejects. Outbound HTTP is routed into a MockTransport by
monkeypatching httpx.AsyncClient in the dispatcher module — the same idiom
the agent's notification tests use.

Seeding goes through `db_session` and COMMITS, because each request runs on
its own session.
"""

import httpx
import pytest
from app.config import settings
from app.models import NotificationDeliveries
from app.services import notifications as notifications_service
from sqlalchemy import select

from tests.conftest import CSRF
from tests.factories import Scenario

OWNER = {"email": "channels@example.com", "password": "hunter2hunter2"}


async def _sign_in(client, creds=OWNER):
    """Register (which also signs in) and return the new user's id."""
    res = await client.post("/api/auth/register", json=creds, headers=CSRF)
    assert res.status_code == 201, res.text
    return res.json()["user"]["id"]


async def _create(client, **body):
    return await client.post("/api/me/channels", json=body, headers=CSRF)


@pytest.fixture
def ntfy_server(monkeypatch):
    """A configured instance ntfy server, so the ntfy kind is creatable."""
    monkeypatch.setattr(settings, "NTFY_SERVER_URL", "https://ntfy.test")


@pytest.fixture
def outbound(monkeypatch):
    """Capture the dispatcher's outbound HTTP; every send succeeds with 200."""
    requests: list[httpx.Request] = []
    real_client = httpx.AsyncClient  # the patch below replaces the module attr

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200)

    def factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(notifications_service.httpx, "AsyncClient", factory)
    return requests


# --- authentication -----------------------------------------------------------


async def test_channels_require_a_session(client):
    res = await client.get("/api/me/channels")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"

    res = await client.post("/api/me/channels", json={"kind": "discord"}, headers=CSRF)
    assert res.status_code == 401


async def test_channel_mutations_require_the_csrf_header(client):
    res = await client.post("/api/me/channels", json={"kind": "discord"})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "csrf"


# --- envelope + shape ---------------------------------------------------------


async def test_no_channels_is_an_empty_data_list(client):
    await _sign_in(client)
    body = (await client.get("/api/me/channels")).json()
    assert body == {"data": []}


async def test_ntfy_create_serializes_every_field(client, ntfy_server):
    await _sign_in(client)
    res = await _create(client, kind="ntfy", name="my phone", topic="snagr-x")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body == {
        "id": body["id"],
        "kind": "ntfy",
        "name": "my phone",
        "url": None,
        "topic": "snagr-x",
        "has_secret": False,
        "events": None,
        "enabled": True,
        "created_at": body["created_at"],
        "secret": None,
    }


async def test_webhook_secret_is_shown_exactly_once(client):
    await _sign_in(client)
    res = await _create(client, kind="webhook", name="hook", url="https://example.com/hook")
    assert res.status_code == 201, res.text
    created = res.json()
    assert created["has_secret"] is True
    assert isinstance(created["secret"], str) and len(created["secret"]) >= 32

    # the list never carries the secret again — only has_secret
    (listed,) = (await client.get("/api/me/channels")).json()["data"]
    assert "secret" not in listed
    assert listed["has_secret"] is True


# --- validation ---------------------------------------------------------------


async def test_unknown_kind_is_a_field_error(client):
    await _sign_in(client)
    res = await _create(client, kind="carrier-pigeon", name="x")
    assert res.status_code == 422
    body = res.json()["error"]
    assert body["code"] == "validation_error"
    assert body["fields"] == {"kind": "Unknown channel kind"}


async def test_ntfy_without_a_server_is_no_server(client, monkeypatch):
    monkeypatch.setattr(settings, "NTFY_SERVER_URL", None)
    await _sign_in(client)
    res = await _create(client, kind="ntfy", name="x", topic="t")
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "no_server"


async def test_create_field_validation(client, ntfy_server):
    await _sign_in(client)
    cases = [
        ({"kind": "discord", "url": "https://discord.com/api/webhooks/1/t"}, "name"),
        ({"kind": "ntfy", "name": "x"}, "topic"),
        ({"kind": "webhook", "name": "x"}, "url"),
        ({"kind": "webhook", "name": "x", "url": "ftp://nope"}, "url"),
        ({"kind": "discord", "name": "x", "url": "https://example.com/hook"}, "url"),
        (
            {
                "kind": "discord",
                "name": "x",
                "url": "https://discord.com/api/webhooks/1/t",
                "events": ["price.wiggled"],
            },
            "events",
        ),
    ]
    for body, field in cases:
        res = await _create(client, **body)
        assert res.status_code == 422, (body, res.text)
        assert res.json()["error"]["code"] == "validation_error"
        assert field in res.json()["error"]["fields"], body


async def test_empty_and_full_event_sets_normalize_to_null(client):
    await _sign_in(client)
    full = await _create(
        client,
        kind="discord",
        name="a",
        url="https://discord.com/api/webhooks/1/t",
        events=["target.hit", "listing.new"],
    )
    assert full.json()["events"] is None
    empty = await _create(
        client, kind="discord", name="b", url="https://discord.com/api/webhooks/1/t", events=[]
    )
    assert empty.json()["events"] is None
    subset = await _create(
        client,
        kind="discord",
        name="c",
        url="https://discord.com/api/webhooks/1/t",
        events=["target.hit"],
    )
    assert subset.json()["events"] == ["target.hit"]


# --- update + delete ----------------------------------------------------------


async def test_patch_updates_and_keeps_kind(client):
    await _sign_in(client)
    created = (
        await _create(
            client, kind="discord", name="old", url="https://discord.com/api/webhooks/1/t"
        )
    ).json()

    res = await client.patch(
        f"/api/me/channels/{created['id']}",
        json={"name": "new", "enabled": False, "events": ["listing.new"]},
        headers=CSRF,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert (body["name"], body["enabled"], body["events"], body["kind"]) == (
        "new",
        False,
        ["listing.new"],
        "discord",
    )


async def test_another_users_channel_is_hidden(client, make_client, monkeypatch, ntfy_server):
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
    await _sign_in(client)
    channel = (await _create(client, kind="ntfy", name="mine", topic="t")).json()

    stranger = await make_client()
    await _sign_in(stranger, {"email": "stranger@example.com", "password": "hunter2hunter2"})
    for res in (
        await stranger.patch(f"/api/me/channels/{channel['id']}", json={"name": "x"}, headers=CSRF),
        await stranger.delete(f"/api/me/channels/{channel['id']}", headers=CSRF),
        await stranger.post(f"/api/me/channels/{channel['id']}/test", headers=CSRF),
    ):
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"

    # the owner still sees it untouched
    (mine,) = (await client.get("/api/me/channels")).json()["data"]
    assert mine["name"] == "mine"


async def test_delete_cascades_pending_deliveries(client, db_session):
    user_id = await _sign_in(client)
    created = (
        await _create(client, kind="discord", name="x", url="https://discord.com/api/webhooks/1/t")
    ).json()

    async with db_session() as session:
        sc = Scenario(session)
        from app.models import User

        sc._user = await session.get(User, user_id)
        outbox = await sc.outbox()
        session.add(NotificationDeliveries(outbox_id=outbox.id, channel_id=created["id"]))
        await session.commit()

    res = await client.delete(f"/api/me/channels/{created['id']}", headers=CSRF)
    assert res.status_code == 204

    async with db_session() as session:
        remaining = (await session.execute(select(NotificationDeliveries))).scalars().all()
        assert remaining == []


async def test_deleting_a_missing_channel_is_not_found(client):
    await _sign_in(client)
    res = await client.delete("/api/me/channels/9999", headers=CSRF)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


# --- test sends ---------------------------------------------------------------


async def test_test_send_goes_through_the_real_adapter(client, ntfy_server, outbound):
    await _sign_in(client)
    channel = (await _create(client, kind="ntfy", name="x", topic="my-topic")).json()

    res = await client.post(f"/api/me/channels/{channel['id']}/test", headers=CSRF)
    assert res.status_code == 204, res.text
    (request,) = outbound
    assert str(request.url) == "https://ntfy.test/my-topic"
    assert request.headers["Title"] == "Snagr"


async def test_failing_destination_is_channel_failed(client, monkeypatch):
    await _sign_in(client)
    channel = (
        await _create(client, kind="webhook", name="x", url="https://example.com/hook")
    ).json()

    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    def factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(notifications_service.httpx, "AsyncClient", factory)
    res = await client.post(f"/api/me/channels/{channel['id']}/test", headers=CSRF)
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "channel_failed"


async def test_ntfy_test_without_a_server_is_no_server(client, ntfy_server, monkeypatch):
    await _sign_in(client)
    channel = (await _create(client, kind="ntfy", name="x", topic="t")).json()
    # the server was unconfigured after the channel was created
    monkeypatch.setattr(settings, "NTFY_SERVER_URL", None)
    res = await client.post(f"/api/me/channels/{channel['id']}/test", headers=CSRF)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "no_server"
