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
