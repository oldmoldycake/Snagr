"""OIDC/SSO login — config, service logic, and the two auth routes.

The IdP itself never exists in these tests: protocol helpers are
monkeypatched at the service boundary, so everything from the routes down to
the DB is covered without a network.
"""

import pytest

from app.config import settings


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
