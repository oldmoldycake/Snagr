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

import asyncio

import httpx
import pytest
from app.config import settings
from app.models import NotificationChannels, NotificationDeliveries, User
from app.routers.me import MAX_CHANNELS
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

    res = await client.post("/api/me/channels/test", json={"kind": "discord"}, headers=CSRF)
    assert res.status_code == 401


async def test_channel_mutations_require_the_csrf_header(client):
    res = await client.post("/api/me/channels", json={"kind": "discord"})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "csrf"

    res = await client.post("/api/me/channels/test", json={"kind": "discord"})
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


async def test_channels_stop_at_the_limit(client):
    await _sign_in(client)
    for n in range(MAX_CHANNELS):
        res = await _create(client, kind="webhook", name=f"hook {n}", url="https://example.com/h")
        assert res.status_code == 201, res.text

    res = await _create(client, kind="webhook", name="one more", url="https://example.com/h")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "channel_limit"
    assert len((await client.get("/api/me/channels")).json()["data"]) == MAX_CHANNELS


async def test_a_create_racing_another_stops_at_the_limit(client, db_session):
    user_id = await _sign_in(client)
    for n in range(MAX_CHANNELS - 1):
        res = await _create(client, kind="webhook", name=f"hook {n}", url="https://example.com/h")
        assert res.status_code == 201, res.text

    # a second create, mid-transaction: it holds the owner's row and adds the
    # last channel, so this request must wait for it, not count under the limit too
    async with db_session() as other:
        await other.execute(select(User.id).where(User.id == user_id).with_for_update())
        racing = asyncio.create_task(
            _create(client, kind="webhook", name="one more", url="https://example.com/h")
        )
        await asyncio.sleep(0.3)
        assert not racing.done()
        other.add(
            NotificationChannels(
                user_id=user_id, kind="webhook", name="last", url="https://example.com/h"
            )
        )
        await other.commit()

    res = await racing
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "channel_limit"
    assert len((await client.get("/api/me/channels")).json()["data"]) == MAX_CHANNELS


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


@pytest.mark.parametrize(
    "url",
    [
        "http://vision:8100/rescore",
        "http://minio:9000/snagr",
        "http://localhost:8000/api/items",
        "http://nas.local/hook",
        "http://127.0.0.1/",
        "http://127.1/",
        "http://2130706433/",
        "http://10.0.0.5/hook",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[::1",
        "https://example.com:99999/hook",
        "https://user:pass@example.com/hook",
    ],
)
async def test_webhook_urls_must_be_public(client, url):
    await _sign_in(client)
    res = await _create(client, kind="webhook", name="x", url=url)
    assert res.status_code == 422, url
    error = res.json()["error"]
    assert error["code"] == "validation_error"
    assert "url" in error["fields"]


@pytest.mark.parametrize("topic", ["a/../v1/account", "has space", "a?b=c", "x" * 65])
async def test_ntfy_topics_are_a_single_path_segment(client, ntfy_server, topic):
    await _sign_in(client)
    res = await _create(client, kind="ntfy", name="x", topic=topic)
    assert res.status_code == 422, topic
    error = res.json()["error"]
    assert error["code"] == "validation_error"
    assert "topic" in error["fields"]


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


async def test_patch_cannot_point_a_channel_inward(client):
    await _sign_in(client)
    created = (
        await _create(client, kind="webhook", name="x", url="https://example.com/hook")
    ).json()

    res = await client.patch(
        f"/api/me/channels/{created['id']}", json={"url": "http://minio:9000/"}, headers=CSRF
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"
    (channel,) = (await client.get("/api/me/channels")).json()["data"]
    assert channel["url"] == "https://example.com/hook"


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


async def _saved_before_the_guard(db_session, user_id, url):
    """A webhook channel written straight to the DB, as rows from before the
    URL guard existed were — the API would refuse to create it."""
    async with db_session() as session:
        channel = NotificationChannels(
            user_id=user_id, kind="webhook", name="old", url=url, secret="s", enabled=True
        )
        session.add(channel)
        await session.commit()
        return channel.id


async def test_testing_an_internal_url_sends_nothing(client, db_session, outbound):
    user_id = await _sign_in(client)
    channel_id = await _saved_before_the_guard(db_session, user_id, "http://169.254.169.254/")

    res = await client.post(f"/api/me/channels/{channel_id}/test", headers=CSRF)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"
    assert outbound == []


async def test_a_url_httpx_cannot_parse_is_not_a_500(client, db_session, outbound):
    user_id = await _sign_in(client)
    channel_id = await _saved_before_the_guard(db_session, user_id, "https://example.com/a\x01b")

    res = await client.post(f"/api/me/channels/{channel_id}/test", headers=CSRF)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"
    assert outbound == []


# --- test sends before saving -------------------------------------------------


async def _test_unsaved(client, **body):
    return await client.post("/api/me/channels/test", json=body, headers=CSRF)


async def test_an_unsaved_channel_is_tested_without_saving_it(client, ntfy_server, outbound):
    await _sign_in(client)
    res = await _test_unsaved(client, kind="ntfy", topic=" my-topic ")
    assert res.status_code == 204, res.text
    (request,) = outbound
    assert str(request.url) == "https://ntfy.test/my-topic"
    assert request.headers["Title"] == "Snagr"
    assert (await client.get("/api/me/channels")).json() == {"data": []}


async def test_an_unsaved_webhook_test_carries_every_delivery_header(client, outbound):
    await _sign_in(client)
    res = await _test_unsaved(client, kind="webhook", url="https://example.com/hook")
    assert res.status_code == 204, res.text
    (request,) = outbound
    assert str(request.url) == "https://example.com/hook"
    assert request.headers["X-Snagr-Event"] == "test"
    assert request.headers["X-Snagr-Delivery"] == "test"
    assert request.headers["X-Snagr-Signature"].startswith("sha256=")


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"kind": "carrier-pigeon"}, "kind"),
        ({"kind": "ntfy"}, "topic"),
        ({"kind": "ntfy", "topic": "a/../v1/account"}, "topic"),
        ({"kind": "webhook"}, "url"),
        ({"kind": "webhook", "url": "ftp://nope"}, "url"),
        ({"kind": "discord", "url": "https://example.com/hook"}, "url"),
        ({"kind": "webhook", "url": "http://vision:8100/rescore"}, "url"),
        ({"kind": "webhook", "url": "http://127.1/"}, "url"),
        ({"kind": "webhook", "url": "http://169.254.169.254/latest/meta-data/"}, "url"),
        ({"kind": "webhook", "url": "https://user:pass@example.com/hook"}, "url"),
    ],
)
async def test_an_unsaved_test_refuses_what_create_would(
    client, ntfy_server, outbound, body, field
):
    await _sign_in(client)
    res = await _test_unsaved(client, **body)
    assert res.status_code == 422, res.text
    error = res.json()["error"]
    assert error["code"] == "validation_error"
    assert field in error["fields"]
    assert outbound == []


async def test_an_unsaved_ntfy_test_without_a_server_is_no_server(client, monkeypatch, outbound):
    monkeypatch.setattr(settings, "NTFY_SERVER_URL", None)
    await _sign_in(client)
    res = await _test_unsaved(client, kind="ntfy", topic="t")
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "no_server"
    assert outbound == []


async def test_an_unsaved_test_the_destination_refuses_is_channel_failed(client, monkeypatch):
    await _sign_in(client)
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        # what Discord answers a webhook URL with a mistyped token
        return httpx.Response(401)

    def factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(notifications_service.httpx, "AsyncClient", factory)
    res = await _test_unsaved(client, kind="discord", url="https://discord.com/api/webhooks/1/t")
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "channel_failed"


async def test_an_unsaved_url_httpx_cannot_parse_is_not_a_500(client, outbound):
    await _sign_in(client)
    res = await _test_unsaved(client, kind="webhook", url="https://example.com/a\x01b")
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"
    assert outbound == []
