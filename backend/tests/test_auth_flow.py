"""Registration toggle, invites, /api/me, and admin user management.

Each test starts from an empty DB (conftest truncates between tests), so
"first user" scenarios are the default and every actor is created explicitly.
"""

from app.config import settings

from tests.conftest import CSRF

ADMIN = {"email": "admin@example.com", "password": "hunter2hunter2"}
GUEST = {"email": "guest@example.com", "password": "guest-password"}


async def _register(client, creds=ADMIN):
    return await client.post("/api/auth/register", json=creds, headers=CSRF)


# --- registration + toggle ----------------------------------------------------


async def test_first_user_registers_as_admin(client):
    res = await _register(client)
    assert res.status_code == 201
    assert res.json()["user"]["role"] == "admin"
    # register also signs you in (cookies on the same client)
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == ADMIN["email"]


async def test_registration_closed_after_first_user(client, monkeypatch):
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", False)
    await _register(client)
    res = await _register(client, GUEST)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "registration_closed"


async def test_registration_toggle_opens_signup(client, monkeypatch):
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
    await _register(client)
    res = await _register(client, GUEST)
    assert res.status_code == 201
    assert res.json()["user"]["role"] == "user"  # only the FIRST user is admin


async def test_register_duplicate_email(client, monkeypatch):
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
    await _register(client)
    res = await _register(client, {"email": ADMIN["email"], "password": "whatever123"})
    assert res.status_code == 422
    assert "email" in res.json()["error"]["fields"]


async def test_instance_reflects_toggle(client, monkeypatch):
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", False)
    assert (await client.get("/api/instance")).json()["registration_open"] is True  # 0 users
    await _register(client)
    assert (await client.get("/api/instance")).json()["registration_open"] is False
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
    assert (await client.get("/api/instance")).json()["registration_open"] is True


# --- invites -------------------------------------------------------------------


async def test_invite_lifecycle(client, make_client):
    await _register(client)  # client is now the admin

    created = await client.post("/api/admin/invites", json={}, headers=CSRF)
    assert created.status_code == 201
    token = created.json()["token"]

    # the invitee is a different browser: fresh client, no cookies
    invitee = await make_client()
    valid = await invitee.get(f"/api/auth/invites/{token}")
    assert valid.status_code == 200
    assert valid.json()["email"] is None

    accepted = await invitee.post(f"/api/auth/invites/{token}/accept", json=GUEST, headers=CSRF)
    assert accepted.status_code == 201
    assert accepted.json()["user"]["role"] == "user"
    assert (await invitee.get("/api/auth/me")).json()["email"] == GUEST["email"]

    # single-use: the same link is dead now
    assert (await invitee.get(f"/api/auth/invites/{token}")).status_code == 410

    # and it no longer shows in the admin's pending list
    pending = await client.get("/api/admin/invites")
    assert pending.json()["data"] == []


async def test_invite_unknown_token_404(client):
    await _register(client)
    assert (await client.get("/api/auth/invites/nope")).status_code == 404


async def test_invite_pinned_email_wins(client, make_client):
    await _register(client)
    created = await client.post(
        "/api/admin/invites", json={"email": "pinned@example.com"}, headers=CSRF
    )
    token = created.json()["token"]

    invitee = await make_client()
    res = await invitee.post(
        f"/api/auth/invites/{token}/accept",
        json={"email": "other@example.com", "password": "pw-pw-pw-pw"},
        headers=CSRF,
    )
    assert res.status_code == 201
    assert res.json()["user"]["email"] == "pinned@example.com"


async def test_invite_revoke(client):
    await _register(client)
    created = await client.post("/api/admin/invites", json={}, headers=CSRF)
    invite_id = created.json()["id"]
    assert (await client.delete(f"/api/admin/invites/{invite_id}", headers=CSRF)).status_code == 204
    assert (await client.get(f"/api/auth/invites/{created.json()['token']}")).status_code == 404


# --- /api/me --------------------------------------------------------------------


async def test_password_change(client, make_client):
    await _register(client)

    wrong = await client.post(
        "/api/me/password",
        json={"current_password": "nope", "new_password": "new-password-1"},
        headers=CSRF,
    )
    assert wrong.status_code == 422
    assert wrong.json()["error"]["code"] == "invalid_password"

    ok = await client.post(
        "/api/me/password",
        json={"current_password": ADMIN["password"], "new_password": "new-password-1"},
        headers=CSRF,
    )
    assert ok.status_code == 204

    fresh = await make_client()
    old = await fresh.post("/api/auth/login", json=ADMIN, headers=CSRF)
    assert old.status_code == 401
    new = await fresh.post(
        "/api/auth/login",
        json={"email": ADMIN["email"], "password": "new-password-1"},
        headers=CSRF,
    )
    assert new.status_code == 200


async def test_me_update_and_ntfy_guard(client):
    await _register(client)
    res = await client.patch("/api/me", json={"ntfy_topic": "my-topic"}, headers=CSRF)
    assert res.status_code == 200
    assert res.json()["ntfy_topic"] == "my-topic"

    cleared = await client.patch("/api/me", json={"ntfy_topic": None}, headers=CSRF)
    assert cleared.json()["ntfy_topic"] is None

    no_topic = await client.post("/api/me/ntfy/test", headers=CSRF)
    assert no_topic.status_code == 422
    assert no_topic.json()["error"]["code"] == "no_topic"


# --- admin ----------------------------------------------------------------------


async def test_admin_endpoints_require_admin(client, make_client, monkeypatch):
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
    await _register(client)
    plain = await make_client()
    await _register(plain, GUEST)  # second user -> role 'user'
    assert (await plain.get("/api/admin/users")).status_code == 403


async def test_admin_cannot_delete_self(client):
    await _register(client)
    me = (await client.get("/api/auth/me")).json()
    res = await client.delete(f"/api/admin/users/{me['id']}", headers=CSRF)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "cannot_delete_self"


async def test_admin_deactivate_locks_out(client, make_client, monkeypatch):
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
    await _register(client)
    plain = await make_client()
    guest_id = (await _register(plain, GUEST)).json()["user"]["id"]

    res = await client.patch(
        f"/api/admin/users/{guest_id}", json={"is_active": False}, headers=CSRF
    )
    assert res.status_code == 200 and res.json()["is_active"] is False
    # their existing session dies immediately (current_user checks is_active)...
    assert (await plain.get("/api/auth/me")).status_code == 401
    # ...and they can't log back in
    fresh = await make_client()
    assert (await fresh.post("/api/auth/login", json=GUEST, headers=CSRF)).status_code == 403


async def test_admin_delete_user_and_watch_guard(client, make_client, monkeypatch, db_session):
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
    await _register(client)
    plain = await make_client()
    guest_id = (await _register(plain, GUEST)).json()["user"]["id"]

    # give the guest a watch -> delete must refuse (their data anchors listings)
    from app.models import Categories, Items, Watches

    async with db_session() as s:
        cat = Categories(name="Consoles", slug="consoles")
        s.add(cat)
        await s.flush()
        item = Items(category_id=cat.id, name="PS3 Slim")
        s.add(item)
        await s.flush()
        s.add(Watches(user_id=guest_id, item_id=item.id))
        await s.commit()

    blocked = await client.delete(f"/api/admin/users/{guest_id}", headers=CSRF)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "user_has_items"

    # drop the watch -> delete goes through
    async with db_session() as s:
        from sqlalchemy import delete as sa_delete

        await s.execute(sa_delete(Watches).where(Watches.user_id == guest_id))
        await s.commit()
    assert (await client.delete(f"/api/admin/users/{guest_id}", headers=CSRF)).status_code == 204
    users = (await client.get("/api/admin/users")).json()["data"]
    assert [u["email"] for u in users] == [ADMIN["email"]]


async def test_deleting_a_user_degrades_their_runs_to_system(
    client, make_client, monkeypatch, db_session
):
    # runs don't block deletion the way watches do — ON DELETE SET NULL flips
    # them to system runs (user_id NULL) instead of breaking the hard delete
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
    await _register(client)
    plain = await make_client()
    guest_id = (await _register(plain, GUEST)).json()["user"]["id"]

    from app.models import AgentRuns

    async with db_session() as s:
        s.add(
            AgentRuns(
                user_id=guest_id, scope="global", scope_label="Everything", status="succeeded"
            )
        )
        await s.commit()

    assert (await client.delete(f"/api/admin/users/{guest_id}", headers=CSRF)).status_code == 204

    run = (await client.get("/api/runs")).json()["data"][0]
    assert run["user_id"] is None
