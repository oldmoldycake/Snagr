"""OIDC login (Authentik or any OIDC provider) — the whole IdP conversation.

Spec: docs/superpowers/specs/2026-07-10-authentik-oidc-design.md

  /api/auth/oidc/login    -> new_flow() + build_authorize_url() -> 302 to IdP
  /api/auth/oidc/callback -> unpack_flow() -> exchange_code()
                             -> validate_id_token() -> resolve_oidc_user()

Every failure raises OidcError; the router maps them all to one redirect
(/login?error=sso_failed) and logs the detail server-side.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


class OidcError(Exception):
    """Any OIDC failure; the callback maps every one to the same redirect."""


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
