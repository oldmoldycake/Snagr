"""Reusable FastAPI dependencies for auth + CSRF.

    current_user  -> the signed-in User, from the access cookie or an API token
                     sent as `Authorization: Bearer` (401 if neither is valid)
    reject_bearer -> 403 when the caller is an API token: the account routes
                     (/api/auth/me, /api/me/*, /api/admin/*) are cookie-only
    require_admin -> current_user but 403 unless role == 'admin'
    require_scope -> 403 unless the caller's token carries the scope; cookie
                     sessions always pass (a signed-in browser IS the account)
    csrf_guard    -> 403 unless the X-Snagr-Csrf header is present (non-GET only)

Apply csrf_guard on mutating routers; current_user on everything behind
AuthGuard in the frontend.

Bearer rules: the header wins over the cookie when
both are present; a bearer request carries no ambient credential, so it is
exempt from the CSRF header; every GET needs the `read` scope and every other
method `write`, and the job routes additionally ask for `jobs`. The whole
bearer surface is off when the operator sets MCP_ENABLED=false.
"""

import jwt
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.cookies import ACCESS_COOKIE
from app.core.errors import err
from app.core.security import decode_access_jwt
from app.database import get_db
from app.models import User
from app.services.tokens import authenticate_token

_READ_METHODS = frozenset({"GET", "HEAD"})


def _bearer(request: Request) -> str | None:
    """The raw token from an `Authorization: Bearer …` header, or None."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


async def csrf_guard(request: Request) -> None:
    """Reject mutations lacking the custom header the frontend always sends.
    A custom header is the defence: a cross-site form or <img> can't set one,
    so its presence proves the request came from our own JS, not from a page
    riding the browser's auto-attached cookie. A bearer caller is exempt —
    a browser can't be tricked into attaching an Authorization header the way
    it auto-attaches cookies."""
    if (
        request.method != "GET"
        and _bearer(request) is None
        and "x-snagr-csrf" not in request.headers
    ):
        raise err(403, "csrf", "Missing CSRF header")


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Resolve the caller from a bearer API token or the snagr_access cookie, or raise 401."""
    raw = _bearer(request)
    if raw is not None:
        hit = await authenticate_token(db, raw) if settings.MCP_ENABLED else None
        if hit is None:
            raise err(401, "unauthenticated", "Invalid API token")
        user, token = hit
        needed = "read" if request.method in _READ_METHODS else "write"
        if needed not in token.scopes:
            raise err(403, "insufficient_scope", f"This token lacks the {needed} scope")
        request.state.api_token = token  # require_scope reads it
        return user
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise err(401, "unauthenticated", "Not signed in")
    # verify the signature + expiry (no DB hit — it's all inside the token)
    try:
        claims = decode_access_jwt(token)
    except jwt.InvalidTokenError:  # bad signature OR expired
        raise err(401, "unauthenticated", "Session expired") from None
    # load the actual user row (so a deactivated user is rejected immediately)
    user = await db.get(User, int(claims["sub"]))
    if user is None or not user.is_active:
        raise err(401, "unauthenticated", "Not signed in")
    return user


async def reject_bearer(request: Request) -> None:
    """Account management is cookie-only: an API token acts on the domain
    (items, sites, jobs…), never on the account that owns it — so a leaked
    token can't mint more tokens, change the password, or reach admin routes."""
    if _bearer(request) is not None:
        raise err(403, "forbidden", "API tokens can't manage the account")


def require_scope(scope: str):
    """Dependency factory: 403 unless the caller's API token carries `scope`.
    Cookie sessions pass untouched."""

    async def _check(request: Request, user: User = Depends(current_user)) -> User:
        token = getattr(request.state, "api_token", None)
        if token is not None and scope not in token.scopes:
            raise err(403, "insufficient_scope", f"This token lacks the {scope} scope")
        return user

    return _check


async def require_admin(user=Depends(current_user)):
    """current_user, but 403 for non-admins."""
    if user.role != "admin":
        raise err(403, "forbidden", "Admin access required")
    return user
