"""Current-user self-service — /api/me  (Phase 2; notification channels later).
All require auth + CSRF."""

import re
from decimal import Decimal, InvalidOperation

import httpx
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import csrf_guard, current_user
from app.core.errors import err
from app.core.security import hash_password, new_channel_secret, verify_password
from app.database import get_db
from app.models import NotificationChannels
from app.models import User as UserModel
from app.schemas.auth import MeUpdateRequest, PasswordChangeRequest, User, user_out
from app.schemas.common import DataList
from app.schemas.notifications import (
    KNOWN_EVENTS,
    NotificationChannel,
    NotificationChannelCreated,
    NotificationChannelCreateRequest,
    NotificationChannelUpdateRequest,
    channel_created_out,
    channel_out,
)
from app.services import notifications as notifications_service

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
    # model_fields_set tracks.
    if "email" in body.model_fields_set and body.email is not None and body.email != user.email:
        if await db.scalar(select(UserModel).where(UserModel.email == body.email)):
            raise err(
                422,
                "validation_error",
                "An account with this email already exists",
                fields={"email": "An account with this email already exists"},
            )
        user.email = body.email
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


def _channel_fields(
    kind: str,
    body: NotificationChannelCreateRequest | NotificationChannelUpdateRequest,
    existing: NotificationChannels | None = None,
) -> dict:
    """Normalize + validate the fields shared by channel create/update — mock
    parity with handlers.ts validateChannel. `existing` supplies defaults on
    PATCH; kind is immutable, so there it always comes from the existing row.
    events must be a subset of the known events; empty/full set → None
    ("every event"), the site_ids convention."""
    sent = body.model_fields_set

    raw_name = body.name if "name" in sent else (existing.name if existing is not None else None)
    name = (raw_name or "").strip()
    if not name:
        raise err(422, "validation_error", "Name is required", fields={"name": "Name is required"})

    if "url" in sent:
        url = (body.url or "").strip() or None
    else:
        url = existing.url if existing is not None else None
    if "topic" in sent:
        topic = (body.topic or "").strip() or None
    else:
        topic = existing.topic if existing is not None else None

    if kind == "ntfy":
        url = None
        if not topic:
            raise err(
                422, "validation_error", "Topic is required", fields={"topic": "Topic is required"}
            )
    else:
        topic = None
        if not url or not re.match(r"^https?://", url):
            raise err(
                422,
                "validation_error",
                "A valid URL is required",
                fields={"url": "Must be an http(s) URL"},
            )
        if kind == "discord" and not re.match(
            r"^https://(discord|discordapp)\.com/api/webhooks/", url
        ):
            raise err(
                422,
                "validation_error",
                "Not a Discord webhook URL",
                fields={"url": "Must be a Discord incoming-webhook URL"},
            )

    events = (
        body.events if "events" in sent else (existing.events if existing is not None else None)
    )
    if events is not None:
        if any(e not in KNOWN_EVENTS for e in events):
            raise err(
                422,
                "validation_error",
                "events must be a subset of the known events",
                fields={"events": "Unknown event"},
            )
        # empty or the full set means "every event"
        if len(events) == 0 or len(events) == len(KNOWN_EVENTS):
            events = None

    return {"name": name, "url": url, "topic": topic, "events": events}


async def _own_channel(channel_id: int, user, db: AsyncSession) -> NotificationChannels:
    """Fetch one of the caller's channels; another user's channel 404s the
    same as a missing one (hidden ≡ nonexistent, the runs-privacy rule)."""
    try:
        channel = await db.get(NotificationChannels, channel_id)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e
    if channel is None or channel.user_id != user.id:
        raise err(404, "not_found", f"Channel {channel_id} does not exist")
    return channel


@router.get("/channels", response_model=DataList[NotificationChannel])
async def list_channels(user=Depends(current_user), db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(
            select(NotificationChannels)
            .where(NotificationChannels.user_id == user.id)
            .order_by(NotificationChannels.id)
        )
        return DataList(data=[channel_out(c) for c in result.scalars()])
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.post(
    "/channels", response_model=NotificationChannelCreated, status_code=status.HTTP_201_CREATED
)
async def create_channel(
    body: NotificationChannelCreateRequest,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.kind not in ("ntfy", "webhook", "discord"):
        raise err(
            422, "validation_error", "Unknown channel kind", fields={"kind": "Unknown channel kind"}
        )
    if body.kind == "ntfy" and not settings.NTFY_SERVER_URL:
        raise err(422, "no_server", "This instance has no ntfy server configured")
    fields = _channel_fields(body.kind, body)
    secret = new_channel_secret() if body.kind == "webhook" else None
    try:
        channel = NotificationChannels(
            user_id=user.id, kind=body.kind, secret=secret, enabled=body.enabled, **fields
        )
        db.add(channel)
        await db.flush()
        await db.refresh(channel)  # created_at/enabled come back from server defaults
        await db.commit()
        # the one response the signing secret ever rides in
        return channel_created_out(channel, secret)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.patch("/channels/{channel_id}", response_model=NotificationChannel)
async def update_channel(
    channel_id: int,
    body: NotificationChannelUpdateRequest,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    channel = await _own_channel(channel_id, user, db)
    fields = _channel_fields(channel.kind, body, existing=channel)
    try:
        for key, value in fields.items():
            setattr(channel, key, value)
        if body.enabled is not None:
            channel.enabled = body.enabled
        await db.commit()
        return channel_out(channel)
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e


@router.delete("/channels/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(
    channel_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)
):
    channel = await _own_channel(channel_id, user, db)
    try:
        # pending deliveries go with it (FK ON DELETE CASCADE)
        await db.delete(channel)
        await db.commit()
    except SQLAlchemyError as e:
        raise err(503, "db_unavailable", "Could not reach the database") from e
    return None


@router.post("/channels/{channel_id}/test", status_code=status.HTTP_204_NO_CONTENT)
async def test_channel(
    channel_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)
):
    channel = await _own_channel(channel_id, user, db)
    try:
        await notifications_service.send_test(channel)
    except RuntimeError as e:  # ntfy kind while the instance has no server
        raise err(422, "no_server", "This instance has no ntfy server configured") from e
    except httpx.HTTPError as e:
        raise err(502, "channel_failed", "Could not reach the channel destination") from e
