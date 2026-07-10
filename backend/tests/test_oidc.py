"""OIDC/SSO login — config, service logic, and the two auth routes.

The IdP itself never exists in these tests: protocol helpers are
monkeypatched at the service boundary, so everything from the routes down to
the DB is covered without a network.
"""

import pytest

from app.config import settings
from app.core.security import hash_password
from app.models import User
from app.services import oidc


@pytest.fixture(autouse=True)
def _oidc_settings(monkeypatch):
    """Every test in this file runs with SSO configured (individual tests
    un-set pieces to probe the disabled state)."""
    monkeypatch.setattr(settings, "OIDC_ISSUER", "https://idp.test/application/o/snagr/")
    monkeypatch.setattr(settings, "OIDC_CLIENT_ID", "snagr-client")
    monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", "s3cret")
    monkeypatch.setattr(settings, "OIDC_PROVIDER_NAME", "Authentik")


# --- config -------------------------------------------------------------------

def test_oidc_enabled_requires_all_three(monkeypatch):
    assert settings.oidc_enabled is True          # fixture set all three
    monkeypatch.setattr(settings, "OIDC_CLIENT_SECRET", None)
    assert settings.oidc_enabled is False


# --- instance contract ----------------------------------------------------------

async def test_instance_reports_oidc(client, monkeypatch):
    res = await client.get("/api/instance")
    assert res.json()["oidc_provider_name"] == "Authentik"
    monkeypatch.setattr(settings, "OIDC_ISSUER", None)   # disable -> null
    res = await client.get("/api/instance")
    assert res.json()["oidc_provider_name"] is None


# --- resolve_oidc_user: sub-first, marry-by-verified-email, auto-create ---------

CLAIMS = {"sub": "authentik-sub-1", "email": "sso@example.com", "email_verified": True}


async def _seed_user(db_session, email, **kw):
    async with db_session() as s:
        u = User(email=email, email_verified=True, **kw)
        s.add(u)
        await s.commit()
        return u.id


async def test_resolve_matches_by_sub(db_session):
    uid = await _seed_user(db_session, "someone@else.com", oidc_sub="authentik-sub-1")
    async with db_session() as s:
        user = await oidc.resolve_oidc_user(s, CLAIMS)
    assert user.id == uid            # sub wins even though the email differs


async def test_resolve_marries_verified_email(db_session):
    uid = await _seed_user(db_session, "sso@example.com",
                           password_hash=hash_password("pw12345678"))
    async with db_session() as s:
        user = await oidc.resolve_oidc_user(s, CLAIMS)
        await s.commit()
    assert user.id == uid
    async with db_session() as s:
        assert (await s.get(User, uid)).oidc_sub == "authentik-sub-1"   # married


async def test_resolve_refuses_unverified_email(db_session):
    uid = await _seed_user(db_session, "sso@example.com")
    async with db_session() as s:
        with pytest.raises(oidc.OidcError):
            await oidc.resolve_oidc_user(s, {**CLAIMS, "email_verified": False})
    async with db_session() as s:
        assert (await s.get(User, uid)).oidc_sub is None                # NOT married


async def test_resolve_autocreates_unknown_user(db_session):
    async with db_session() as s:
        user = await oidc.resolve_oidc_user(s, CLAIMS)
        await s.commit()
    assert user.role == "user"
    assert user.oidc_sub == "authentik-sub-1"
    assert user.password_hash is None


async def test_resolve_rejects_inactive_user(db_session):
    await _seed_user(db_session, "sso@example.com",
                     oidc_sub="authentik-sub-1", is_active=False)
    async with db_session() as s:
        with pytest.raises(oidc.OidcError):
            await oidc.resolve_oidc_user(s, CLAIMS)


# --- GET /api/auth/oidc/login ---------------------------------------------------

FAKE_METADATA = {
    "issuer": "https://idp.test/application/o/snagr/",
    "authorization_endpoint": "https://idp.test/authorize",
    "token_endpoint": "https://idp.test/token",
    "jwks_uri": "https://idp.test/jwks",
}


async def test_oidc_login_redirects_to_idp(client, monkeypatch):
    monkeypatch.setattr(oidc, "_metadata", FAKE_METADATA)   # skip discovery HTTP
    res = await client.get("/api/auth/oidc/login")
    assert res.status_code == 302
    loc = res.headers["location"]
    assert loc.startswith("https://idp.test/authorize?")
    assert "client_id=snagr-client" in loc
    assert "code_challenge_method=S256" in loc
    assert "state=" in loc and "nonce=" in loc
    assert "snagr_oidc_flow" in res.cookies                 # flow cookie stashed


async def test_oidc_login_404_when_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "OIDC_ISSUER", None)
    res = await client.get("/api/auth/oidc/login")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


# --- GET /api/auth/oidc/callback -------------------------------------------------

def _stub_idp(monkeypatch, claims):
    """Replace the two network-touching service fns; the rest runs for real."""
    async def fake_exchange(code, redirect_uri, verifier):
        return {"id_token": "stub-id-token"}
    async def fake_validate(id_token, nonce):
        return claims
    monkeypatch.setattr(oidc, "exchange_code", fake_exchange)
    monkeypatch.setattr(oidc, "validate_id_token", fake_validate)


def _set_flow_cookie(client, flow):
    # No `domain=` here: httpx's stdlib-cookiejar-backed jar never matches an
    # explicit domain against a single-label test host ("test") for version-0
    # cookies (eff_request_host appends ".local" specifically to defeat that
    # match) -- the cookie would silently never be sent. Leaving domain unset
    # makes it a match-any-domain cookie, fine for a client with exactly one host.
    client.cookies.set("snagr_oidc_flow", oidc.pack_flow(flow),
                       path="/api/auth/oidc")


async def _sso_login(client, monkeypatch, claims=CLAIMS):
    """Drive a full (stubbed-IdP) SSO sign-in on `client`; returns the response."""
    _stub_idp(monkeypatch, claims)
    flow = {"state": "st-1", "nonce": "n-1", "verifier": "v-1"}
    _set_flow_cookie(client, flow)
    return await client.get("/api/auth/oidc/callback",
                            params={"code": "c-1", "state": "st-1"})


async def test_callback_signs_in_and_creates_user(client, monkeypatch):
    res = await _sso_login(client, monkeypatch)
    assert res.status_code == 302
    assert res.headers["location"] == "/"
    assert "snagr_access" in res.cookies and "snagr_refresh" in res.cookies
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "sso@example.com"


async def test_callback_marries_existing_account(client, monkeypatch):
    # a password user registers first...
    reg = await client.post("/api/auth/register",
                            json={"email": "sso@example.com", "password": "hunter2hunter2"},
                            headers={"X-Snagr-Csrf": "1"})
    uid = reg.json()["user"]["id"]
    await client.post("/api/auth/logout", headers={"X-Snagr-Csrf": "1"})
    # ...then signs in via SSO with the same (verified) email -> same account
    await _sso_login(client, monkeypatch)
    me = await client.get("/api/auth/me")
    assert me.json()["id"] == uid


async def test_callback_rejects_state_mismatch(client, monkeypatch):
    _stub_idp(monkeypatch, CLAIMS)
    _set_flow_cookie(client, {"state": "st-1", "nonce": "n-1", "verifier": "v-1"})
    res = await client.get("/api/auth/oidc/callback",
                           params={"code": "c-1", "state": "EVIL"})
    assert res.status_code == 302
    assert res.headers["location"] == "/login?error=sso_failed"
    assert "snagr_access" not in res.cookies


async def test_callback_rejects_missing_flow_cookie(client, monkeypatch):
    _stub_idp(monkeypatch, CLAIMS)
    res = await client.get("/api/auth/oidc/callback",
                           params={"code": "c-1", "state": "st-1"})
    assert res.headers["location"] == "/login?error=sso_failed"


async def test_callback_rejects_idp_error_param(client, monkeypatch):
    _stub_idp(monkeypatch, CLAIMS)
    _set_flow_cookie(client, {"state": "st-1", "nonce": "n-1", "verifier": "v-1"})
    res = await client.get("/api/auth/oidc/callback",
                           params={"error": "access_denied", "state": "st-1", "code": "x"})
    assert res.headers["location"] == "/login?error=sso_failed"
