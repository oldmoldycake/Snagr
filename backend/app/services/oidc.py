"""OIDC login (Authentik or any OIDC provider) — the whole IdP conversation.

Spec: docs/superpowers/specs/2026-07-10-authentik-oidc-design.md

  /api/auth/oidc/login    -> new_flow() + build_authorize_url() -> 302 to IdP
  /api/auth/oidc/callback -> unpack_flow() -> exchange_code()
                             -> validate_id_token() -> resolve_oidc_user()

Every failure raises OidcError; the router maps them all to one redirect
(/login?error=sso_failed) and logs the detail server-side.
"""

import base64
import json
import secrets
from urllib.parse import urlencode

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.jose import JsonWebKey, JsonWebToken
from authlib.jose.errors import JoseError
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import User


class OidcError(Exception):
    """Any OIDC failure; the callback maps every one to the same redirect."""


# --- provider metadata (lazy, cached — the app must boot while the IdP is down) --

_metadata: dict | None = None
_keyset = None            # JWKS, cached by Task 5's validate_id_token


async def _discovery() -> dict:
    global _metadata
    if _metadata is None:
        url = settings.OIDC_ISSUER.rstrip("/") + "/.well-known/openid-configuration"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                _metadata = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OidcError(f"OIDC discovery failed: {exc}")
    return _metadata


# --- one login attempt's short-lived secrets (live in the flow cookie) ----------

def new_flow() -> dict:
    return {
        "state": secrets.token_urlsafe(24),     # CSRF binding for the redirect flow
        "nonce": secrets.token_urlsafe(24),     # binds the ID token to this attempt
        "verifier": secrets.token_urlsafe(48),  # PKCE
    }


def pack_flow(flow: dict) -> str:
    """Cookie-safe encoding — JSON's quotes/braces are hostile to cookie values."""
    return base64.urlsafe_b64encode(json.dumps(flow).encode()).decode()


def unpack_flow(raw: str) -> dict:
    try:
        return json.loads(base64.urlsafe_b64decode(raw.encode()))
    except (ValueError, UnicodeDecodeError):
        raise OidcError("unreadable flow cookie")


async def build_authorize_url(redirect_uri: str, flow: dict) -> str:
    meta = await _discovery()
    if "authorization_endpoint" not in meta:
        raise OidcError("discovery document has no authorization_endpoint")
    return meta["authorization_endpoint"] + "?" + urlencode({
        "response_type": "code",
        "client_id": settings.OIDC_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": "openid email profile",
        "state": flow["state"],
        "nonce": flow["nonce"],
        "code_challenge": create_s256_code_challenge(flow["verifier"]),
        "code_challenge_method": "S256",
    })


async def _jwks():
    global _keyset
    if _keyset is None:
        meta = await _discovery()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(meta["jwks_uri"])
                resp.raise_for_status()
                _keyset = JsonWebKey.import_key_set(resp.json())
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise OidcError(f"JWKS fetch failed: {exc}")
    return _keyset


async def exchange_code(code: str, redirect_uri: str, verifier: str) -> dict:
    """Swap the authorization code for tokens at the IdP's token endpoint."""
    meta = await _discovery()
    try:
        async with AsyncOAuth2Client(
            client_id=settings.OIDC_CLIENT_ID,
            client_secret=settings.OIDC_CLIENT_SECRET,
            redirect_uri=redirect_uri,
        ) as client:
            token = await client.fetch_token(
                meta["token_endpoint"],
                grant_type="authorization_code",
                code=code,
                code_verifier=verifier,
            )
    except Exception as exc:   # authlib raises a small zoo; every one means "failed"
        raise OidcError(f"code exchange failed: {exc}")
    if "id_token" not in token:
        raise OidcError("token response has no id_token")
    return token


async def validate_id_token(id_token: str, nonce: str) -> dict:
    """Verify signature (JWKS), issuer, audience, expiry, nonce -> claims."""
    global _keyset
    meta = await _discovery()
    try:
        claims = JsonWebToken(["RS256", "ES256"]).decode(
            id_token, await _jwks(),
            claims_options={
                "iss": {"essential": True, "value": meta["issuer"]},
                "aud": {"essential": True, "value": settings.OIDC_CLIENT_ID},
            },
        )
        claims.validate()
    except JoseError as exc:
        _keyset = None      # maybe the IdP rotated keys — refetch on the next attempt
        raise OidcError(f"id_token validation failed: {exc}")
    if claims.get("nonce") != nonce:
        raise OidcError("nonce mismatch")
    return dict(claims)


# --- account linking ----------------------------------------------------------

async def resolve_oidc_user(db: AsyncSession, claims: dict) -> User:
    """ID-token claims -> local User. Sub-first, marry-by-verified-email
    second, auto-create third (spec decision: Authentik is the access gate).
    Raises OidcError for inactive users or unusable claims. Caller commits."""
    sub = claims.get("sub")
    if not sub:
        raise OidcError("ID token has no sub")
    email = claims.get("email")
    email_ok = claims.get("email_verified") is True and bool(email)

    # 1. the stable link — survives email changes at the IdP
    user = await db.scalar(select(User).where(User.oidc_sub == sub))

    # 2. the marriage: claim an existing local account, once. Only a VERIFIED
    #    email may do this — an unverified one could hijack someone's account.
    if user is None and email_ok:
        user = await db.scalar(select(User).where(User.email == email))
        if user is not None:
            user.oidc_sub = sub

    # 3. unknown at the IdP-approved door -> provision a fresh account
    if user is None:
        if not email_ok:
            raise OidcError("IdP did not supply a verified email")
        user = User(email=email, email_verified=True, role="user",
                    is_active=True, oidc_sub=sub)
        db.add(user)
        await db.flush()          # assign user.id for _start_session

    if not user.is_active:
        raise OidcError(f"account {user.id} is disabled")
    return user
