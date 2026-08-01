"""Authentication & invites — /api/auth/*  (Phase 2).

THE WHOLE LOGIN FLOW, in one file. Read it top-to-bottom once and it'll click:

  register  first user ever -> create them as admin, hand out cookies
  login     check email+password -> hand out cookies
  (a request) browser auto-sends the access cookie -> deps.current_user reads it
  refresh   access cookie expired? swap the refresh cookie for a fresh pair
  logout    revoke the refresh token + delete both cookies

Two cookies do two jobs:
  - snagr_access  : a signed JWT that says "I am user 7, role admin", expires in
                    15 min. Stateless — we trust it because of the signature, no
                    DB lookup needed to validate it.
  - snagr_refresh : a random string, good for 30 days, whose hash we store in the
                    `sessions` table. It can ONLY do one thing: get you a new
                    access token. Because it's in the DB we can revoke it (logout).

Why two? The access token is short-lived so a stolen one is useless fast; the
refresh token is revocable so logout actually works. Best of both.

These paths return 401 DIRECTLY on bad creds — they must not trip the client's
refresh-retry loop (client.ts skips retry for /api/auth/*).
"""

import hmac
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.cookies import (
    REFRESH_COOKIE,
    clear_auth_cookies,
    set_access_cookie,
    set_refresh_cookie,
)
from app.core.deps import csrf_guard, current_user
from app.core.errors import err
from app.core.security import (
    hash_password,
    hash_refresh,
    make_access_jwt,
    new_refresh_token,
    verify_password,
)
from app.database import get_db
from app.models import Invites, Sessions, User
from app.schemas.auth import (
    InviteAcceptRequest,
    InviteValidation,
    LoginRequest,
    RegisterRequest,
    UserEnvelope,
    user_out,
)
from app.schemas.auth import User as UserSchema
from app.services import oidc

router = APIRouter(prefix="/api/auth", tags=["auth"])


# --- helpers ----------------------------------------------------------------

async def _start_session(db: AsyncSession, response: Response, user: User) -> None:
    """Mint a fresh access+refresh pair for `user` and put both on the response.
    Called by register, login, and refresh — the one place cookies are issued."""
    # access token: stateless JWT, straight into the cookie
    set_access_cookie(response, make_access_jwt(user.id, user.role))
    # refresh token: keep only the hash server-side; the raw value goes in the cookie
    raw, digest = new_refresh_token()
    db.add(Sessions(
        user_id=user.id,
        refresh_hash=digest,
        expires_at=datetime.now(UTC) + timedelta(days=settings.REFRESH_TTL_DAYS),
    ))
    set_refresh_cookie(response, raw)


# --- SSO (OIDC) ---------------------------------------------------------------

log = logging.getLogger(__name__)

FLOW_COOKIE = "snagr_oidc_flow"   # carries state+nonce+PKCE verifier between the two hops
FLOW_PATH = "/api/auth/oidc"


def _redirect_uri(request: Request) -> str:
    # behind a proxy the request-derived host can be wrong — the setting overrides
    return settings.OIDC_REDIRECT_URI or str(request.url_for("oidc_callback"))


def _sso_failed() -> RedirectResponse:
    """Every failure looks the same to the browser; details go to the log."""
    response = RedirectResponse("/login?error=sso_failed", status_code=302)
    response.delete_cookie(FLOW_COOKIE, path=FLOW_PATH)
    return response


@router.get("/oidc/login")
async def oidc_login(request: Request):
    """Kick off SSO: stash the flow secrets in a cookie, bounce to the IdP."""
    if not settings.oidc_enabled:
        raise err(404, "not_found", "SSO is not configured")
    flow = oidc.new_flow()
    try:
        url = await oidc.build_authorize_url(_redirect_uri(request), flow)
    except oidc.OidcError as exc:
        log.warning("OIDC login redirect failed: %s", exc)
        return _sso_failed()
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(FLOW_COOKIE, oidc.pack_flow(flow), max_age=600, httponly=True,
                        samesite="lax", secure=settings.cookie_secure, path=FLOW_PATH)
    return response


@router.get("/oidc/callback", name="oidc_callback")
async def oidc_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """The IdP sent the browser back: verify state, trade the code for an ID
    token, resolve the local user, and start a completely normal session."""
    if not settings.oidc_enabled:
        return _sso_failed()
    raw = request.cookies.get(FLOW_COOKIE)
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not raw or not code or not state or request.query_params.get("error"):
        return _sso_failed()
    try:
        flow = oidc.unpack_flow(raw)
        if not hmac.compare_digest(state.encode(), str(flow.get("state", "")).encode()):
            raise oidc.OidcError("state mismatch")
        token = await oidc.exchange_code(code, _redirect_uri(request), flow["verifier"])
        claims = await oidc.validate_id_token(token["id_token"], flow["nonce"])
        user = await oidc.resolve_oidc_user(db, claims)
    except (oidc.OidcError, KeyError) as exc:
        log.warning("OIDC callback failed: %s", exc)
        return _sso_failed()
    response = RedirectResponse("/", status_code=302)
    response.delete_cookie(FLOW_COOKIE, path=FLOW_PATH)
    await _start_session(db, response, user)
    await db.commit()
    return response


# --- register / login -------------------------------------------------------

@router.post("/register", response_model=UserEnvelope, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(csrf_guard)])
async def register(body: RegisterRequest, response: Response, db: AsyncSession = Depends(get_db)):
    # the very first user can always register (and becomes admin). After that,
    # self-signup is only open while the REGISTRATION_OPEN toggle is on —
    # otherwise people join via an admin invite.
    user_count = await db.scalar(select(func.count()).select_from(User))
    is_first_user = (user_count or 0) == 0
    if not is_first_user and not settings.REGISTRATION_OPEN:
        raise err(403, "registration_closed", "Registration is closed — ask your admin for an invite")

    if await db.scalar(select(User).where(User.email == body.email)):
        raise err(422, "validation_error", "An account with this email already exists",
                  fields={"email": "An account with this email already exists"})

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        role="admin" if is_first_user else "user",
        is_active=True,
        email_verified=True,
    )
    db.add(user)
    await db.flush()          # INSERT now, so user.id exists
    await db.refresh(user)    # load DB-filled columns (created_at)
    await _start_session(db, response, user)
    await db.commit()
    return UserEnvelope(user=user_out(user))


@router.post("/login", response_model=UserEnvelope, dependencies=[Depends(csrf_guard)])
async def login(body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == body.email))
    # same generic error whether the email is unknown or the password is wrong —
    # never tell an attacker which half they got right.
    if user is None or user.password_hash is None or not verify_password(body.password, user.password_hash):
        raise err(401, "invalid_credentials", "Email or password is incorrect")
    if not user.is_active:
        raise err(403, "forbidden", "This account is disabled")
    await _start_session(db, response, user)
    await db.commit()
    return UserEnvelope(user=user_out(user))


# --- session lifecycle ------------------------------------------------------

@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(csrf_guard)])
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        # revoke this refresh token so it can't be used again, even if the cookie leaks
        await db.execute(
            update(Sessions)
            .where(Sessions.refresh_hash == hash_refresh(raw), Sessions.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await db.commit()
    clear_auth_cookies(response)


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(csrf_guard)])
async def refresh(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    # the frontend calls this automatically when a request 401s on an expired access token
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise err(401, "unauthenticated", "Refresh token missing")

    session = await db.scalar(select(Sessions).where(Sessions.refresh_hash == hash_refresh(raw)))
    now = datetime.now(UTC)
    if session is None or session.revoked_at is not None or session.expires_at < now:
        raise err(401, "unauthenticated", "Refresh token expired")

    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise err(401, "unauthenticated", "Not signed in")

    # ROTATE: burn the old refresh token and issue a brand-new pair. A refresh
    # token is single-use, so a stolen one stops working the moment you use yours.
    session.revoked_at = now
    await _start_session(db, response, user)
    await db.commit()


@router.get("/me", response_model=UserSchema)
async def get_me(user: User = Depends(current_user)):
    # current_user already did all the work; just shape the row for the API
    return user_out(user)


# --- invites (admin-issued signup) -------------------------------------------

async def _live_invite(db: AsyncSession, token: str) -> Invites:
    """Look up an invite token, or raise the contract's 404/410."""
    invite = await db.scalar(select(Invites).where(Invites.token == token))
    if invite is None:
        raise err(404, "not_found", "This invite link is not valid")
    if invite.used_at is not None or invite.expires_at < datetime.now(UTC):
        raise err(410, "invite_expired", "This invite has expired or was already used")
    return invite


@router.get("/invites/{token}", response_model=InviteValidation)
async def validate_invite(token: str, db: AsyncSession = Depends(get_db)):
    invite = await _live_invite(db, token)
    return InviteValidation(email=invite.email, expires_at=invite.expires_at.isoformat())


@router.post("/invites/{token}/accept", response_model=UserEnvelope,
             status_code=status.HTTP_201_CREATED, dependencies=[Depends(csrf_guard)])
async def accept_invite(token: str, body: InviteAcceptRequest, response: Response,
                        db: AsyncSession = Depends(get_db)):
    invite = await _live_invite(db, token)
    # an invite pinned to an email wins over whatever the form submitted
    email = invite.email or body.email
    if await db.scalar(select(User).where(User.email == email)):
        raise err(422, "validation_error", "An account with this email already exists",
                  fields={"email": "An account with this email already exists"})

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        role=invite.role,
        is_active=True,
        email_verified=True,
    )
    db.add(user)
    invite.used_at = datetime.now(UTC)   # single-use: burn it
    await db.flush()
    await db.refresh(user)
    await _start_session(db, response, user)
    await db.commit()
    return UserEnvelope(user=user_out(user))
