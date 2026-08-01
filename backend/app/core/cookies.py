"""The cookie mechanics, in one place. A "login flow" is really just:
set these cookies when you log in, read them on each request, clear them on
logout. This module owns the two cookie names + how they're set.

Why httpOnly: JavaScript CANNOT read these cookies (no `document.cookie`
access), so a XSS bug can't steal the token. The browser still sends them
automatically on every request to the same origin — which is why the frontend
never has to attach a token by hand (see frontend/src/api/client.ts).
"""

from fastapi import Response

from app.config import settings

ACCESS_COOKIE = "snagr_access"  # short-lived JWT — proves who you are
REFRESH_COOKIE = "snagr_refresh"  # long-lived opaque token — gets you a new access token


def _set(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,  # JS can't read it
        samesite="lax",  # not sent on cross-site requests -> CSRF defense
        secure=settings.cookie_secure,  # HTTPS-only in prod
        path="/",
    )


def set_access_cookie(response: Response, token: str) -> None:
    _set(response, ACCESS_COOKIE, token, settings.ACCESS_TTL_MIN * 60)


def set_refresh_cookie(response: Response, raw: str) -> None:
    _set(response, REFRESH_COOKIE, raw, settings.REFRESH_TTL_DAYS * 86400)


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")
