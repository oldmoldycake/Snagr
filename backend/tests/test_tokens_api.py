"""HTTP layer for /api/me/tokens and bearer auth — status codes and error.codes
as frontend/src/mocks/handlers.ts defines them, plus the bearer rules the mock
can't exercise (it only ever speaks cookies): scope enforcement by method, the
cookie-only account routes, expiry / revocation / deactivation, the CSRF
exemption for bearer callers, and the MCP_ENABLED kill switch.

An "agent" here is a fresh client with no cookie jar that sends only the
Authorization header — exactly what an MCP client or a script looks like.
"""

from datetime import UTC, datetime, timedelta

from app.config import settings
from app.core.security import API_TOKEN_PREFIX
from app.models import ApiTokens, User

from tests.conftest import CSRF

OWNER = {"email": "tokens@example.com", "password": "hunter2hunter2"}
STRANGER = {"email": "stranger@example.com", "password": "hunter2hunter2"}


async def _sign_in(client, creds=OWNER):
    """Register (which also signs in) and return the new user's id."""
    res = await client.post("/api/auth/register", json=creds, headers=CSRF)
    assert res.status_code == 201, res.text
    return res.json()["user"]["id"]


async def _mint(client, name="agent", scopes=("read",), **extra):
    body = {"name": name, "scopes": list(scopes), **extra}
    res = await client.post("/api/me/tokens", json=body, headers=CSRF)
    assert res.status_code == 201, res.text
    return res.json()


def _bearer(raw: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw}"}


# --- token management ---------------------------------------------------------


async def test_tokens_require_a_session(client):
    for res in (
        await client.get("/api/me/tokens"),
        await client.post("/api/me/tokens", json={"name": "x", "scopes": ["read"]}, headers=CSRF),
        await client.delete("/api/me/tokens/1", headers=CSRF),
    ):
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "unauthenticated"


async def test_no_tokens_is_an_empty_data_list(client):
    await _sign_in(client)
    res = await client.get("/api/me/tokens")
    assert res.status_code == 200
    assert res.json() == {"data": []}


async def test_create_serializes_every_field_and_shows_the_token_once(client):
    await _sign_in(client)
    created = await _mint(client, name="laptop", scopes=("read", "write"), expires_in_days=30)
    assert created["token"].startswith(API_TOKEN_PREFIX)
    assert len(created["token"]) > 40
    assert created["name"] == "laptop"
    assert created["scopes"] == ["read", "write"]
    assert created["last_used_at"] is None
    expires = datetime.fromisoformat(created["expires_at"])
    assert timedelta(days=29) < expires - datetime.now(UTC) <= timedelta(days=30)
    assert created["created_at"].endswith("+00:00")

    # the list never carries the raw token again
    (listed,) = (await client.get("/api/me/tokens")).json()["data"]
    assert "token" not in listed
    assert listed["id"] == created["id"]
    assert listed["name"] == "laptop"


async def test_never_expiring_token_has_null_expires_at(client):
    await _sign_in(client)
    created = await _mint(client)
    assert created["expires_at"] is None


async def test_scopes_come_back_in_canonical_order(client):
    await _sign_in(client)
    created = await _mint(client, scopes=("jobs", "read"))
    assert created["scopes"] == ["read", "jobs"]


async def test_create_field_validation(client):
    await _sign_in(client)
    cases = [
        ({"name": "  ", "scopes": ["read"]}, "name"),
        ({"name": "x" * 65, "scopes": ["read"]}, "name"),
        ({"name": "ok", "scopes": []}, "scopes"),
        ({"name": "ok"}, "scopes"),
        ({"name": "ok", "scopes": ["admin"]}, "scopes"),
        ({"name": "ok", "scopes": ["read"], "expires_in_days": 0}, "expires_in_days"),
    ]
    for body, field in cases:
        res = await client.post("/api/me/tokens", json=body, headers=CSRF)
        assert res.status_code == 422, (body, res.text)
        assert res.json()["error"]["code"] == "validation_error"
        assert field in res.json()["error"]["fields"], body


async def test_revoke_deletes_and_the_token_stops_working(client, make_client):
    await _sign_in(client)
    created = await _mint(client)
    agent = await make_client()
    res = await agent.get("/api/categories", headers=_bearer(created["token"]))
    assert res.status_code == 200

    res = await client.delete(f"/api/me/tokens/{created['id']}", headers=CSRF)
    assert res.status_code == 204
    assert (await client.get("/api/me/tokens")).json()["data"] == []

    res = await agent.get("/api/categories", headers=_bearer(created["token"]))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


async def test_another_users_token_is_hidden(client, make_client, monkeypatch):
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
    await _sign_in(client)
    created = await _mint(client)

    stranger = await make_client()
    await _sign_in(stranger, STRANGER)
    res = await stranger.delete(f"/api/me/tokens/{created['id']}", headers=CSRF)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"
    assert (await stranger.get("/api/me/tokens")).json()["data"] == []

    (mine,) = (await client.get("/api/me/tokens")).json()["data"]
    assert mine["id"] == created["id"]


async def test_deleting_a_missing_token_is_not_found(client):
    await _sign_in(client)
    res = await client.delete("/api/me/tokens/999", headers=CSRF)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


# --- bearer on the REST API -----------------------------------------------------


async def test_bearer_reads_without_cookie_or_csrf(client, make_client):
    await _sign_in(client)
    token = (await _mint(client))["token"]
    agent = await make_client()
    res = await agent.get("/api/categories", headers=_bearer(token))
    assert res.status_code == 200
    assert res.json() == {"data": []}


async def test_read_only_token_cannot_mutate(client, make_client):
    await _sign_in(client)
    token = (await _mint(client, scopes=("read",)))["token"]
    agent = await make_client()
    res = await agent.post("/api/categories", json={"name": "Cameras"}, headers=_bearer(token))
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "insufficient_scope"


async def test_write_token_mutates_without_the_csrf_header(client, make_client):
    await _sign_in(client)
    token = (await _mint(client, scopes=("read", "write")))["token"]
    agent = await make_client()
    res = await agent.post("/api/categories", json={"name": "Cameras"}, headers=_bearer(token))
    assert res.status_code == 201, res.text
    assert res.json()["name"] == "Cameras"


async def test_asking_the_hunter_for_work_needs_the_jobs_scope(client, make_client, sc):
    """A hunt spends LLM money, which is why it is its own scope: `write` lets
    a token edit the user's data, not spend on their behalf."""
    user_id = await _sign_in(client)
    writer = (await _mint(client, name="writer", scopes=("read", "write")))["token"]
    runner = (await _mint(client, name="runner", scopes=("read", "write", "jobs")))["token"]
    agent = await make_client()
    request = {"kind": "hunt", "scope": "global"}

    res = await agent.post("/api/jobs", json=request, headers=_bearer(writer))
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "insufficient_scope"

    item = await sc.item("Alpha")
    watch = await sc.watch(item, user=await sc.db.get(User, user_id))
    job = await sc.job(watch=watch, status="running")
    await sc.commit()

    res = await agent.post(f"/api/jobs/{job.id}/cancel", headers=_bearer(writer))
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "insufficient_scope"
    res = await agent.post(f"/api/jobs/{job.id}/cancel", headers=_bearer(runner))
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "cancelled"


async def test_account_routes_are_cookie_only(client, make_client):
    await _sign_in(client)  # the first user is the admin
    token = (await _mint(client, scopes=("read", "write", "jobs")))["token"]
    agent = await make_client()
    for res in (
        await agent.get("/api/me/tokens", headers=_bearer(token)),
        await agent.post(
            "/api/me/tokens", json={"name": "more", "scopes": ["read"]}, headers=_bearer(token)
        ),
        await agent.patch("/api/me", json={"email": "new@example.com"}, headers=_bearer(token)),
        await agent.get("/api/me/channels", headers=_bearer(token)),
        await agent.get("/api/auth/me", headers=_bearer(token)),
        await agent.get("/api/admin/users", headers=_bearer(token)),
    ):
        assert res.status_code == 403, res.text
        assert res.json()["error"]["code"] == "forbidden"


async def test_unknown_and_expired_tokens_are_unauthenticated(client, make_client, db_session):
    await _sign_in(client)
    created = await _mint(client, expires_in_days=1)
    agent = await make_client()

    res = await agent.get("/api/categories", headers=_bearer("nope"))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"

    async with db_session() as session:
        token = await session.get(ApiTokens, created["id"])
        token.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()
    res = await agent.get("/api/categories", headers=_bearer(created["token"]))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


async def test_deactivated_owner_locks_the_token_out(client, make_client, monkeypatch):
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
    await _sign_in(client)  # admin
    member = await make_client()
    member_id = await _sign_in(member, STRANGER)
    token = (await _mint(member))["token"]
    agent = await make_client()
    assert (await agent.get("/api/categories", headers=_bearer(token))).status_code == 200

    res = await client.patch(
        f"/api/admin/users/{member_id}", json={"is_active": False}, headers=CSRF
    )
    assert res.status_code == 200, res.text
    res = await agent.get("/api/categories", headers=_bearer(token))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


async def test_last_used_at_is_stamped(client, make_client):
    await _sign_in(client)
    created = await _mint(client)
    agent = await make_client()
    await agent.get("/api/categories", headers=_bearer(created["token"]))
    (listed,) = (await client.get("/api/me/tokens")).json()["data"]
    assert listed["last_used_at"] is not None


async def test_the_header_wins_over_the_cookie(client):
    await _sign_in(client)
    # a signed-in browser sending a bad bearer is judged on the bearer
    res = await client.get("/api/categories", headers=_bearer("nope"))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


async def test_mcp_disabled_turns_bearer_off(client, make_client, monkeypatch):
    await _sign_in(client)
    token = (await _mint(client))["token"]
    monkeypatch.setattr(settings, "MCP_ENABLED", False)
    assert (await client.get("/api/instance")).json()["mcp_enabled"] is False
    agent = await make_client()
    res = await agent.get("/api/categories", headers=_bearer(token))
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


async def test_instance_reports_mcp_enabled(client):
    assert (await client.get("/api/instance")).json()["mcp_enabled"] is True
