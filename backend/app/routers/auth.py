"""Authentication, SSO and invite signup — /api/auth/*. Public except /me.

THE WHOLE LOGIN FLOW, in one file. Read it top-to-bottom once and it'll click:

  register  first user ever -> create them as admin, hand out cookies
  login     check email+password -> hand out cookies
  (a request) browser auto-sends the access cookie -> deps.current_user reads it
  refresh   access cookie expired? swap the refresh cookie for a fresh pair
  logout    revoke the refresh token + delete both cookies

Two cookies do two jobs:
  - snagr_access  : a signed JWT that says "I am user 7, role admin, sign-in X",
                    expires in 15 min. Honoured only while sign-in X still has an
                    unrevoked row in `sessions` (deps.current_user checks).
  - snagr_refresh : a random string, good for 30 days, whose hash we store in the
                    `sessions` table. It can ONLY do one thing: get you a new
                    access token. Because it's in the DB we can revoke it (logout).

Why two? The access token is short-lived so a stolen one is useless fast; the
refresh token is revocable so logout actually works. Best of both.

A sign-in is a token family (sessions.family_id): every refresh token rotated
out of one login shares it. Revoking a family ends that sign-in everywhere —
a password change does it to every other sign-in, and presenting a refresh
token that was already rotated away does it to its own (someone else has a
copy).

These paths return 401 DIRECTLY on bad creds. client.ts never refreshes-and-retries
the credential routes (login, register, refresh, logout, invites), so a refused
login is not silently replayed; /me does refresh, since a 401 there on a fresh page
load usually just means the access cookie expired.
"""

import hmac
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core import ratelimit
from app.core.cookies import (
    REFRESH_COOKIE,
    clear_auth_cookies,
    set_access_cookie,
    set_refresh_cookie,
)
from app.core.deps import csrf_guard, current_user, reject_bearer
from app.core.errors import ApiError, err
from app.core.security import (
    FIRST_USER_LOCK,
    hash_password,
    hash_refresh,
    make_access_jwt,
    new_refresh_token,
    password_error,
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

_UNIQUE_VIOLATION = "23505"

# how long a rotated-away refresh token is refused without revoking its family.
# Two tabs that wake together both refresh with the same cookie; the loser is
# the same browser, not a thief, and its next request carries the new cookie.
_REUSE_GRACE = timedelta(seconds=10)


# --- helpers ----------------------------------------------------------------


async def _start_session(
    db: AsyncSession, response: Response, user: User, family_id: UUID | None = None
) -> None:
    """Mint a fresh access+refresh pair for `user` and put both on the response.
    Called by register, login, and refresh — the one place cookies are issued.
    Refresh passes the sign-in it is continuing; everyone else starts a new one."""
    family_id = family_id or uuid4()
    set_access_cookie(response, make_access_jwt(user.id, user.role, family_id))
    # refresh token: keep only the hash server-side; the raw value goes in the cookie
    raw, digest = new_refresh_token()
    db.add(
        Sessions(
            user_id=user.id,
            family_id=family_id,
            refresh_hash=digest,
            expires_at=datetime.now(UTC) + timedelta(days=settings.REFRESH_TTL_DAYS),
        )
    )
    set_refresh_cookie(response, raw)


def _check_new_password(plain: str) -> None:
    """422 validation_error for a password too weak to sign up with."""
    if problem := password_error(plain):
        raise err(422, "validation_error", problem, fields={"password": problem})


def _email_taken() -> ApiError:
    """The 422 for signing up with an email that already has an account."""
    return err(
        422,
        "validation_error",
        "An account with this email already exists",
        fields={"email": "An account with this email already exists"},
    )


async def _insert_user(db: AsyncSession, user: User) -> None:
    """INSERT a new password user now, so user.id and created_at exist.

    The routes check the email is free first, but a concurrent sign-up can
    take it between that check and this INSERT; the unique index is the real
    guard. users.email is the only unique column a new password user fills."""
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        if getattr(exc.orig, "pgcode", None) == _UNIQUE_VIOLATION:
            raise _email_taken() from exc
        raise
    await db.refresh(user)  # load DB-filled columns (created_at)


# --- SSO (OIDC) ---------------------------------------------------------------

log = logging.getLogger(__name__)

FLOW_COOKIE = "snagr_oidc_flow"  # state+nonce+PKCE verifier+return path, between the two hops
FLOW_PATH = "/api/auth/oidc"


def _redirect_uri(request: Request) -> str:
    # behind a proxy the request-derived host can be wrong — the setting overrides
    return settings.OIDC_REDIRECT_URI or str(request.url_for("oidc_callback"))


def _return_path(path: object) -> str:
    """The page SSO was started from (the login page's `next`), else the
    dashboard. Only an in-app path is honoured: a browser reads `//host` and
    `/\\host` alike as another site, so either would send the newly signed-in
    visitor off-site."""
    if isinstance(path, str) and path.startswith("/") and not path.startswith(("//", "/\\")):
        return path
    return "/"


def _sso_failed() -> RedirectResponse:
    """Every failure looks the same to the browser; details go to the log."""
    response = RedirectResponse("/login?error=sso_failed", status_code=302)
    response.delete_cookie(FLOW_COOKIE, path=FLOW_PATH)
    return response


@router.get("/oidc/login")
async def oidc_login(request: Request):
    """Kick off SSO: stash the flow secrets and the page to come back to
    (`?next=`) in a cookie, bounce to the IdP."""
    if not settings.oidc_enabled:
        raise err(404, "not_found", "SSO is not configured")
    flow = oidc.new_flow()
    flow["next"] = request.query_params.get("next")
    try:
        url = await oidc.build_authorize_url(_redirect_uri(request), flow)
    except oidc.OidcError as exc:
        log.warning("OIDC login redirect failed: %s", exc)
        return _sso_failed()
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        FLOW_COOKIE,
        oidc.pack_flow(flow),
        max_age=600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path=FLOW_PATH,
    )
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
    # Checked here rather than at /oidc/login: the cookie came back from the browser.
    response = RedirectResponse(_return_path(flow.get("next")), status_code=302)
    response.delete_cookie(FLOW_COOKIE, path=FLOW_PATH)
    await _start_session(db, response, user)
    await db.commit()
    return response


# --- register / login -------------------------------------------------------


@router.post(
    "/register",
    response_model=UserEnvelope,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(csrf_guard)],
)
async def register(body: RegisterRequest, response: Response, db: AsyncSession = Depends(get_db)):
    """Self-signup; the first user ever becomes admin. Starts a session.

    403 registration_closed once someone exists and REGISTRATION_OPEN is off —
    people then join by invite. 422 validation_error for an email already taken
    or a password under 8 characters."""
    # the very first user can always register (and becomes admin). After that,
    # self-signup is only open while the REGISTRATION_OPEN toggle is on —
    # otherwise people join via an admin invite.
    await db.execute(select(func.pg_advisory_xact_lock(FIRST_USER_LOCK)))
    user_count = await db.scalar(select(func.count()).select_from(User))
    is_first_user = (user_count or 0) == 0
    if not is_first_user and not settings.REGISTRATION_OPEN:
        raise err(
            403, "registration_closed", "Registration is closed — ask your admin for an invite"
        )
    _check_new_password(body.password)

    if await db.scalar(select(User).where(func.lower(User.email) == body.email)):
        raise _email_taken()

    user = User(
        email=body.email,
        password_hash=await hash_password(body.password),
        role="admin" if is_first_user else "user",
        is_active=True,
        # a typed-in address is unconfirmed, so SSO won't link to it
        # (services/oidc.py) — except the first user's: they own the instance
        email_verified=is_first_user,
    )
    await _insert_user(db, user)
    await _start_session(db, response, user)
    await db.commit()
    return UserEnvelope(user=user_out(user))


@router.post("/login", response_model=UserEnvelope, dependencies=[Depends(csrf_guard)])
async def login(
    body: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)
):
    """Check email and password and start a session.

    401 invalid_credentials for an unknown email and a wrong password alike;
    403 forbidden for a deactivated account; 429 rate_limited once the client
    address or the account has made too many attempts (core/ratelimit.py)."""
    address = request.client.host if request.client else ""
    account = body.email
    if wait := max(
        ratelimit.by_address.retry_after(address), ratelimit.by_account.retry_after(account)
    ):
        raise ratelimit.rate_limited(wait)
    ratelimit.by_address.record(address)
    ratelimit.by_account.record(account)

    user = await db.scalar(select(User).where(func.lower(User.email) == body.email))
    # hand the connection back while argon2 works: a queue of logins holding
    # the whole pool would stall every other request as surely as hashing on
    # the event loop did
    await db.commit()
    # same generic error whether the email is unknown or the password is wrong —
    # never tell an attacker which half they got right, not even by how long
    # the answer took: an unknown email is checked against a stand-in hash.
    password_ok = await verify_password(body.password, user.password_hash if user else None)
    if user is None or not password_ok:
        raise err(401, "invalid_credentials", "Email or password is incorrect")
    if not user.is_active:
        raise err(403, "forbidden", "This account is disabled")
    await _start_session(db, response, user)
    await db.commit()
    return UserEnvelope(user=user_out(user))


# --- session lifecycle ------------------------------------------------------


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(csrf_guard)])
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Revoke the refresh token behind this cookie and clear both auth cookies."""
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
    """Swap a live refresh cookie for a new access+refresh pair, burning the old one.

    401 unauthenticated when the refresh cookie is missing, revoked, expired, or
    belongs to a deactivated user. Presenting a token that was already rotated
    away also signs its whole family out."""
    # the frontend calls this automatically when a request 401s on an expired access token
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise err(401, "unauthenticated", "Refresh token missing")

    # ROTATE: burn the old refresh token and issue a brand-new pair, in one
    # statement — concurrent refreshes with the same cookie queue on the row
    # lock and only the first finds it unrevoked, so one token mints one pair
    digest = hash_refresh(raw)
    now = datetime.now(UTC)
    burned = (
        await db.execute(
            update(Sessions)
            .where(
                Sessions.refresh_hash == digest,
                Sessions.revoked_at.is_(None),
                Sessions.expires_at >= now,
            )
            .values(revoked_at=now)
            .returning(Sessions.user_id, Sessions.family_id)
        )
    ).one_or_none()
    if burned is None:
        await _revoke_reused_family(db, digest, now)
        raise err(401, "unauthenticated", "Refresh token expired")

    user = await db.get(User, burned.user_id)
    if user is None or not user.is_active:
        raise err(401, "unauthenticated", "Not signed in")

    await _start_session(db, response, user, burned.family_id)
    await db.commit()


async def _revoke_reused_family(db: AsyncSession, digest: str, now: datetime) -> None:
    """A refresh token is single-use, so one presented again after it was
    revoked is a copy: whoever rotated it first may be the thief. Neither can
    be told apart, so the whole sign-in ends and the owner logs in again."""
    session = await db.scalar(select(Sessions).where(Sessions.refresh_hash == digest))
    if session is None or session.revoked_at is None or now - session.revoked_at < _REUSE_GRACE:
        return
    await db.execute(
        update(Sessions)
        .where(Sessions.family_id == session.family_id, Sessions.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await db.commit()


@router.get("/me", response_model=UserSchema, dependencies=[Depends(reject_bearer)])
async def get_me(user: User = Depends(current_user)):
    """The signed-in user. Cookie sessions only — an API token gets 403."""
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
    """Check an invite link before showing the signup form.

    404 not_found for an unknown token; 410 invite_expired once used or expired."""
    invite = await _live_invite(db, token)
    return InviteValidation(email=invite.email, expires_at=invite.expires_at.isoformat())


@router.post(
    "/invites/{token}/accept",
    response_model=UserEnvelope,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(csrf_guard)],
)
async def accept_invite(
    token: str, body: InviteAcceptRequest, response: Response, db: AsyncSession = Depends(get_db)
):
    """Create an account from an invite and start a session.

    An invite pinned to an email overrides the submitted one. 404/410 as for
    validating the invite; 422 validation_error for an email already taken or a
    password under 8 characters."""
    invite = await _live_invite(db, token)
    _check_new_password(body.password)
    # single-use: burn it in one statement. Concurrent accepts queue on the row
    # lock and find used_at set once the winner commits; if the winner fails
    # instead, its rollback un-burns the invite for the next in line.
    burned = await db.scalar(
        update(Invites)
        .where(Invites.id == invite.id, Invites.used_at.is_(None))
        .values(used_at=datetime.now(UTC))
        .returning(Invites.id)
    )
    if burned is None:
        raise err(410, "invite_expired", "This invite has expired or was already used")
    # an invite pinned to an email wins over whatever the form submitted
    email = (invite.email or body.email).lower()
    if await db.scalar(select(User).where(func.lower(User.email) == email)):
        raise _email_taken()

    user = User(
        email=email,
        password_hash=await hash_password(body.password),
        role=invite.role,
        is_active=True,
        # the admin vouched for a pinned email; one typed into the form is
        # unconfirmed, so SSO won't link to it (services/oidc.py)
        email_verified=invite.email is not None,
    )
    await _insert_user(db, user)
    await _start_session(db, response, user)
    await db.commit()
    return UserEnvelope(user=user_out(user))
