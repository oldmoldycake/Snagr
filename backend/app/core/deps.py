"""Reusable FastAPI dependencies for auth + CSRF.

    current_user  -> the signed-in User (401 if no/expired access cookie)
    require_admin -> current_user but 403 unless role == 'admin'
    csrf_guard    -> 403 unless the X-Snagr-Csrf header is present (non-GET only)

Apply csrf_guard on mutating routers; current_user on everything behind
AuthGuard in the frontend.
"""

import jwt
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cookies import ACCESS_COOKIE
from app.core.errors import err
from app.core.security import decode_access_jwt
from app.database import get_db
from app.models import User


async def csrf_guard(request: Request) -> None:
    """Reject mutations lacking the custom header the frontend always sends."""
    if request.method != "GET" and "x-snagr-csrf" not in request.headers:
        raise err(403, "csrf", "Missing CSRF header")


async def current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    """Resolve the caller from the snagr_access cookie, or raise 401."""
    # 1. the browser auto-sent the access cookie; pull the token out of it
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise err(401, "unauthenticated", "Not signed in")
    # 2. verify the signature + expiry (no DB hit — it's all inside the token)
    try:
        claims = decode_access_jwt(token)
    except jwt.InvalidTokenError:  # bad signature OR expired
        raise err(401, "unauthenticated", "Session expired")
    # 3. load the actual user row (so a deactivated user is rejected immediately)
    user = await db.get(User, int(claims["sub"]))
    if user is None or not user.is_active:
        raise err(401, "unauthenticated", "Not signed in")
    return user


async def require_admin(user=Depends(current_user)):
    """current_user, but 403 for non-admins."""
    if user.role != "admin":
        raise err(403, "forbidden", "Admin access required")
    return user
