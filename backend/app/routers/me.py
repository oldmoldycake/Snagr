"""Current-user self-service — /api/me  (Phase 2). All require auth + CSRF."""

from decimal import Decimal, InvalidOperation

import httpx
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import csrf_guard, current_user
from app.core.errors import err
from app.core.security import hash_password, verify_password
from app.database import get_db
from app.models import User as UserModel
from app.schemas.auth import MeUpdateRequest, PasswordChangeRequest, User, user_out

router = APIRouter(prefix="/api/me", tags=["me"], dependencies=[Depends(csrf_guard)])

_THRESHOLD_FIELDS = (
    "vision_auto_reject_fake",
    "vision_auto_promote_real",
    "vision_auto_promote_fake",
)


@router.patch("", response_model=User)
async def update_me(
    body: MeUpdateRequest, user=Depends(current_user), db: AsyncSession = Depends(get_db)
):
    # vision thresholds: contract bounds 0.50–1.00; stored resolved (never null)
    fields: dict[str, str] = {}
    thresholds: dict[str, Decimal] = {}
    for field in _THRESHOLD_FIELDS:
        if field not in body.model_fields_set:
            continue
        try:
            value = Decimal(getattr(body, field))
        except InvalidOperation, TypeError:
            fields[field] = "Must be between 0.50 and 1.00"
            continue
        if not Decimal("0.50") <= value <= Decimal("1.00"):
            fields[field] = "Must be between 0.50 and 1.00"
        else:
            thresholds[field] = value.quantize(Decimal("0.01"))
    if fields:
        raise err(
            422, "validation_error", "Thresholds must be between 0.50 and 1.00", fields=fields
        )

    # PATCH semantics: only touch fields the client actually sent — that's what
    # model_fields_set tracks. ntfy_topic can be sent as null to clear it.
    if "email" in body.model_fields_set and body.email is not None and body.email != user.email:
        if await db.scalar(select(UserModel).where(UserModel.email == body.email)):
            raise err(
                422,
                "validation_error",
                "An account with this email already exists",
                fields={"email": "An account with this email already exists"},
            )
        user.email = body.email
    if "ntfy_topic" in body.model_fields_set:
        user.ntfy_topic = body.ntfy_topic or None
    for field, value in thresholds.items():
        setattr(user, field, value)
    await db.commit()
    return user_out(user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChangeRequest, user=Depends(current_user), db: AsyncSession = Depends(get_db)
):
    if user.password_hash is None:  # SSO-provisioned account — no password to change
        raise err(
            422,
            "invalid_password",
            "This account signs in with SSO",
            fields={"current_password": "This account signs in with SSO"},
        )
    if not verify_password(body.current_password, user.password_hash):
        raise err(
            422,
            "invalid_password",
            "Current password is incorrect",
            fields={"current_password": "Current password is incorrect"},
        )
    user.password_hash = hash_password(body.new_password)
    await db.commit()


@router.post("/ntfy/test", status_code=status.HTTP_204_NO_CONTENT)
async def send_test_notification(user=Depends(current_user)):
    if not user.ntfy_topic:
        raise err(422, "no_topic", "Set a ntfy topic before sending a test notification")
    if not settings.NTFY_SERVER_URL:
        raise err(422, "no_server", "This instance has no ntfy server configured")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(
                f"{settings.NTFY_SERVER_URL.rstrip('/')}/{user.ntfy_topic}",
                content="Snagr test notification — you're all set!",
                headers={"Title": "Snagr", "Tags": "tada"},
            )
            resp.raise_for_status()
    except httpx.HTTPError as e:
        raise err(502, "ntfy_failed", "Could not reach the ntfy server") from e
