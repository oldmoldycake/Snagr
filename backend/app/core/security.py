"""Password hashing + token minting. No DB, no FastAPI — so you can unit-test
every one of these in a python shell (the password pair is async: argon2 runs
on a thread pool, off the event loop).

Auth model:
  - access:  short-lived JWT (HS256, ACCESS_TTL_MIN) in the `snagr_access` cookie
  - refresh: opaque random token (REFRESH_TTL_DAYS), its sha256 stored in the
             `sessions` table, in the `snagr_refresh` cookie, rotated on refresh
Both cookies set httponly, samesite=lax, secure=settings.cookie_secure by the
auth router.
"""

import asyncio
import hashlib
import hmac
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import settings

_ph = PasswordHasher()
_ALGO = "HS256"

# pg_advisory_xact_lock key that serializes creating a user who might be the
# first: without it two sign-ups (password or SSO) on an empty instance both
# count zero users and both become admin
FIRST_USER_LOCK = 0x736E_6167_7200  # "snagr\0"


# --- passwords --------------------------------------------------------------

# the frontend's minLength on every new-password input; the server holds the
# same line, since a script never sees that form
MIN_PASSWORD_LENGTH = 8

# argon2 is slow on purpose (tens of ms of CPU and 64 MiB per call), so it
# never runs on the event loop, where one hash stalls every other request.
# Each hash already spreads over `parallelism` threads of its own, so a worker
# per that many CPUs keeps them all busy; more would only fight over the cores
# (the event loop's included), each holding its 64 MiB.
_argon2_pool = ThreadPoolExecutor(
    max_workers=max(1, (os.process_cpu_count() or 1) // _ph.parallelism),
    thread_name_prefix="argon2",
)

# what an email with no password is checked against, so a login for an
# unknown account costs what a wrong password costs and the response time
# doesn't tell which emails exist
_NO_PASSWORD_HASH = _ph.hash(secrets.token_urlsafe(16))


def password_error(plain: str) -> str | None:
    """Why `plain` can't be a new password, or None when it can."""
    if len(plain) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
    return None


async def hash_password(plain: str) -> str:
    """Argon2 hash to store in users.password_hash."""
    return await asyncio.get_running_loop().run_in_executor(_argon2_pool, _ph.hash, plain)


async def verify_password(plain: str, hashed: str | None) -> bool:
    """True if `plain` matches the stored hash; False on any mismatch/bad hash.

    A None hash (no such user, or an SSO-only account) is still worked
    through in full and is always False."""
    return await asyncio.get_running_loop().run_in_executor(_argon2_pool, _verify, plain, hashed)


def _verify(plain: str, hashed: str | None) -> bool:
    """The blocking half of verify_password, run on the argon2 pool."""
    try:
        if hashed is None:
            _ph.verify(_NO_PASSWORD_HASH, plain)
            return False
        return _ph.verify(hashed, plain)
    except VerifyMismatchError, InvalidHashError:
        return False


# --- access token (JWT) -----------------------------------------------------


def make_access_jwt(user_id: int, role: str, family_id: UUID) -> str:
    """Short-lived signed token for the snagr_access cookie. `sid` names the
    sign-in (sessions.family_id) it was issued to."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "sid": str(family_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TTL_MIN),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=_ALGO)


def decode_access_jwt(token: str) -> dict:
    """Decode + verify signature/expiry. Raises jwt.ExpiredSignatureError or
    jwt.InvalidTokenError — the caller (deps.current_user) maps that to 401."""
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[_ALGO])


# --- refresh token ----------------------------------------------------------


def new_refresh_token() -> tuple[str, str]:
    """Return (raw_token_for_cookie, sha256_hash_for_sessions_table).
    Store only the hash; the raw value lives solely in the httpOnly cookie."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh(raw)


def hash_refresh(raw: str) -> str:
    """sha256 of a raw refresh token — used to look the session row up on refresh."""
    return hashlib.sha256(raw.encode()).hexdigest()


# --- API tokens -------------------------------------------------------------

API_TOKEN_PREFIX = "snagr_pat_"  # so humans and secret scanners recognise one on sight


def new_api_token() -> tuple[str, str]:
    """Return (raw_token_shown_once, sha256_for_api_tokens.token_hash).
    The refresh-token scheme: only the hash is ever persisted."""
    raw = API_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_api_token(raw)


def hash_api_token(raw: str) -> str:
    """sha256 of a raw API token — the lookup key into api_tokens.token_hash.

    A fast hash on purpose (not argon2 like passwords): the token is 256
    random bits, not something a person chose, so there is nothing to
    brute-force — and every request finds its row by this digest, the
    sessions.refresh_hash scheme."""
    return hashlib.sha256(raw.encode()).hexdigest()


# --- password reset links ---------------------------------------------------


def new_reset_token() -> tuple[str, str]:
    """Return (raw_token_for_the_link, sha256_for_password_resets.token_hash).
    The refresh-token scheme: only the hash is ever persisted."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_reset_token(raw)


def hash_reset_token(raw: str) -> str:
    """sha256 of a raw reset token — the lookup key into password_resets.token_hash.
    A fast hash for the reason hash_api_token gives: 256 random bits."""
    return hashlib.sha256(raw.encode()).hexdigest()


# --- webhook signing --------------------------------------------------------


def new_channel_secret() -> str:
    """Signing key for a webhook notification channel. Stored recoverable
    (every delivery re-signs with it) — a deliberate departure from the hashed
    refresh tokens above."""
    return secrets.token_urlsafe(32)


def sign_webhook(secret: str, timestamp: str, body: bytes) -> str:
    """X-Snagr-Signature value: 'sha256=' + hex HMAC-SHA256 over the literal
    timestamp header value, a dot, and the exact body bytes on the wire."""
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"
