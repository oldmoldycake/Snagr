"""Password hashing + token minting. Pure functions — no DB, no FastAPI — so
you can unit-test every one of these in a python shell.

Auth model (plan Decision D4):
  - access:  short-lived JWT (HS256, ACCESS_TTL_MIN) in the `snagr_access` cookie
  - refresh: opaque random token (REFRESH_TTL_DAYS), its sha256 stored in the
             `sessions` table, in the `snagr_refresh` cookie, rotated on refresh
Both cookies set httponly, samesite=lax, secure=settings.cookie_secure by the
auth router.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import settings

_ph = PasswordHasher()
_ALGO = "HS256"


# --- passwords --------------------------------------------------------------

def hash_password(plain: str) -> str:
    """Argon2 hash to store in users.password_hash."""
    return _ph.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """True if `plain` matches the stored hash; False on any mismatch/bad hash."""
    try:
        return _ph.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False


# --- access token (JWT) -----------------------------------------------------

def make_access_jwt(user_id: int, role: str) -> str:
    """Short-lived signed token for the snagr_access cookie."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
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
