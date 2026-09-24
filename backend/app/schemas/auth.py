"""Instance + auth/identity + admin schemas — mirror the "Instance / auth" and
"Settings / admin" blocks of types.ts.

EmailStr requires the `email-validator` package (in requirements.txt).
"""

from typing import Literal

from pydantic import BaseModel, EmailStr

UserRole = Literal["admin", "user"]


# --- instance ---------------------------------------------------------------


class InstanceInfo(BaseModel):
    """GET /api/instance — what the operator configured, read before anyone logs in."""

    version: str
    ntfy_server_url: str | None
    registration_open: bool
    oidc_provider_name: str | None  # null = SSO not configured
    vision_enabled: bool  # true iff the operator set VISION_SIDECAR_URL
    mcp_enabled: bool  # false = the operator turned agent access off (MCP_ENABLED)
    recheck_interval_default: int  # RECHECK_INTERVAL_MINUTES — the item form's placeholder
    hunt_enabled: bool  # false = the operator switched hunting off (HUNT_ENABLED)


# --- auth / identity --------------------------------------------------------


class User(BaseModel):
    """The signed-in user — GET /api/auth/me, PATCH /api/me, and inside UserEnvelope."""

    id: int
    email: str
    role: UserRole
    # per-user vision thresholds: 0–1 decimal strings, always resolved — never null
    vision_auto_reject_fake: str
    vision_auto_promote_real: str
    vision_auto_promote_fake: str
    created_at: str


class UserEnvelope(BaseModel):
    """login / register / accept-invite responses: {"user": User}."""

    user: User


class LoginRequest(BaseModel):
    """POST /api/auth/login body."""

    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    """POST /api/auth/register body."""

    email: EmailStr
    password: str


class InviteValidation(BaseModel):
    """GET /api/auth/invites/{token} — 404 invalid, 410 expired/used."""

    email: str | None
    expires_at: str


class InviteAcceptRequest(BaseModel):
    """POST /api/auth/invites/{token}/accept body; an invite pinned to an email ignores this one."""

    email: EmailStr
    password: str


# --- me ---------------------------------------------------------------------


class MeUpdateRequest(BaseModel):
    """PATCH /api/me body; omitted fields are left unchanged."""

    email: EmailStr | None = None
    # plain strs so the 422 validation_error envelope (with a fields map)
    # applies — routers/me.py validates the 0.50–1.00 bounds itself
    vision_auto_reject_fake: str | None = None
    vision_auto_promote_real: str | None = None
    vision_auto_promote_fake: str | None = None


class PasswordChangeRequest(BaseModel):
    """POST /api/me/password body."""

    current_password: str
    new_password: str


# --- admin ------------------------------------------------------------------


class AdminUser(BaseModel):
    """One row of GET /api/admin/users; `item_count` is the user's watch count."""

    id: int
    email: str
    role: UserRole
    is_active: bool
    created_at: str
    item_count: int


class AdminUserUpdateRequest(BaseModel):
    """PATCH /api/admin/users/{id} body; omitted fields are left unchanged."""

    is_active: bool | None = None
    role: UserRole | None = None


class Invite(BaseModel):
    """A pending invite — GET/POST /api/admin/invites. A null `email` lets anyone accept it."""

    id: int
    token: str
    email: str | None
    expires_at: str
    created_at: str


class InviteCreateRequest(BaseModel):
    """POST /api/admin/invites body; no email makes an invite anyone can accept."""

    email: EmailStr | None = None


# --- ORM-row -> schema serializers -------------------------------------------
# (timestamps must go out as ISO-8601 strings, so plain model_validate won't do)


def user_out(u) -> User:
    """Serialize a users row, rendering the thresholds as 2-decimal strings."""
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
    """Serialize a users row for the admin list, with its watch count."""
    return AdminUser(
        id=u.id,
        email=u.email,
        role=u.role,
        is_active=u.is_active,
        created_at=u.created_at.isoformat(),
        item_count=item_count,
    )


def invite_out(i) -> Invite:
    """Serialize an invites row."""
    return Invite(
        id=i.id,
        token=i.token,
        email=i.email,
        expires_at=i.expires_at.isoformat(),
        created_at=i.created_at.isoformat(),
    )
