"""Instance + auth/identity + admin schemas — mirror the "Instance / auth" and
"Settings / admin" blocks of types.ts.

EmailStr requires the `email-validator` package (in requirements.txt).
"""

from typing import Literal

from pydantic import BaseModel, EmailStr

UserRole = Literal["admin", "user"]


# --- instance ---------------------------------------------------------------

class InstanceInfo(BaseModel):
    version: str
    ntfy_server_url: str | None
    registration_open: bool


# --- auth / identity --------------------------------------------------------

class User(BaseModel):
    id: int
    email: str
    role: UserRole
    ntfy_topic: str | None
    created_at: str


class UserEnvelope(BaseModel):
    """login / register / accept-invite responses: {"user": User}."""
    user: User


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class InviteValidation(BaseModel):
    """GET /api/auth/invites/{token} — 404 invalid, 410 expired/used."""
    email: str | None
    expires_at: str


class InviteAcceptRequest(BaseModel):
    email: EmailStr
    password: str


# --- me ---------------------------------------------------------------------

class MeUpdateRequest(BaseModel):
    email: EmailStr | None = None
    ntfy_topic: str | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


# --- admin ------------------------------------------------------------------

class AdminUser(BaseModel):
    id: int
    email: str
    role: UserRole
    is_active: bool
    created_at: str
    item_count: int


class AdminUserUpdateRequest(BaseModel):
    is_active: bool | None = None
    role: UserRole | None = None


class Invite(BaseModel):
    id: int
    token: str
    email: str | None
    expires_at: str
    created_at: str


class InviteCreateRequest(BaseModel):
    email: EmailStr | None = None


# --- ORM-row -> schema serializers -------------------------------------------
# (timestamps must go out as ISO-8601 strings, so plain model_validate won't do)

def user_out(u) -> User:
    return User(
        id=u.id,
        email=u.email,
        role=u.role,
        ntfy_topic=u.ntfy_topic,
        created_at=u.created_at.isoformat(),
    )


def admin_user_out(u, item_count: int) -> AdminUser:
    return AdminUser(
        id=u.id,
        email=u.email,
        role=u.role,
        is_active=u.is_active,
        created_at=u.created_at.isoformat(),
        item_count=item_count,
    )


def invite_out(i) -> Invite:
    return Invite(
        id=i.id,
        token=i.token,
        email=i.email,
        expires_at=i.expires_at.isoformat(),
        created_at=i.created_at.isoformat(),
    )
