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
    oidc_provider_name: str | None  # null = SSO not configured
    vision_enabled: bool  # true iff the operator set VISION_SIDECAR_URL


# --- auth / identity --------------------------------------------------------


class User(BaseModel):
    id: int
    email: str
    role: UserRole
    # vision thresholds (D-V9): 0–1 decimal strings, always resolved — never null
    vision_auto_reject_fake: str
    vision_auto_promote_real: str
    vision_auto_promote_fake: str
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
    # plain strs so the 422 validation_error envelope (with a fields map)
    # applies — routers/me.py validates the 0.50–1.00 bounds itself
    vision_auto_reject_fake: str | None = None
    vision_auto_promote_real: str | None = None
    vision_auto_promote_fake: str | None = None


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
        vision_auto_reject_fake=f"{u.vision_auto_reject_fake:.2f}",
        vision_auto_promote_real=f"{u.vision_auto_promote_real:.2f}",
        vision_auto_promote_fake=f"{u.vision_auto_promote_fake:.2f}",
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
