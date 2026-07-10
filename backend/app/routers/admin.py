"""Admin — /api/admin/*  (Phase 4). Every route requires admin (require_admin
depends on current_user, so it covers auth too)."""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import csrf_guard, require_admin
from app.core.errors import err
from app.database import get_db
from app.models import Invites, Sessions, User, Watches
from app.schemas.auth import (
    AdminUser,
    AdminUserUpdateRequest,
    Invite,
    InviteCreateRequest,
    admin_user_out,
    invite_out,
)
from app.schemas.common import DataList

INVITE_TTL_DAYS = 7

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


async def _get_user(db: AsyncSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise err(404, "not_found", f"User {user_id} does not exist")
    return user


async def _item_counts(db: AsyncSession) -> dict[int, int]:
    """user_id -> number of watches (the API calls a user's watches 'items')."""
    rows = await db.execute(select(Watches.user_id, func.count()).group_by(Watches.user_id))
    return dict(rows.all())


@router.get("/users", response_model=DataList[AdminUser])
async def list_users(db: AsyncSession = Depends(get_db)):
    users = (await db.scalars(select(User).order_by(User.id))).all()
    counts = await _item_counts(db)
    return DataList(data=[admin_user_out(u, counts.get(u.id, 0)) for u in users])


@router.patch("/users/{user_id}", response_model=AdminUser, dependencies=[Depends(csrf_guard)])
async def update_user(user_id: int, body: AdminUserUpdateRequest,
                      db: AsyncSession = Depends(get_db)):
    user = await _get_user(db, user_id)
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.role is not None:
        user.role = body.role
    await db.commit()
    counts = await _item_counts(db)
    return admin_user_out(user, counts.get(user.id, 0))


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(csrf_guard)])
async def delete_user(user_id: int, admin=Depends(require_admin),
                      db: AsyncSession = Depends(get_db)):
    if user_id == admin.id:
        raise err(422, "cannot_delete_self", "You cannot delete your own account")
    user = await _get_user(db, user_id)

    # a user's watches anchor real data (listings, price history) — refuse
    # rather than cascade-delete it. Deactivating keeps the data and locks them out.
    watch_count = await db.scalar(
        select(func.count()).select_from(Watches).where(Watches.user_id == user_id))
    if watch_count:
        raise err(409, "user_has_items",
                  "This user still has tracked items — deactivate the account instead")

    # their sessions and issued invites go with them (FKs would block otherwise)
    await db.execute(delete(Sessions).where(Sessions.user_id == user_id))
    await db.execute(delete(Invites).where(Invites.created_by == user_id))
    await db.delete(user)
    await db.commit()


@router.get("/invites", response_model=DataList[Invite])
async def list_invites(db: AsyncSession = Depends(get_db)):
    # pending only: unused and unexpired, like the mock
    now = datetime.now(timezone.utc)
    invites = (await db.scalars(
        select(Invites)
        .where(Invites.used_at.is_(None), Invites.expires_at > now)
        .order_by(Invites.id)
    )).all()
    return DataList(data=[invite_out(i) for i in invites])


@router.post("/invites", response_model=Invite, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(csrf_guard)])
async def create_invite(body: InviteCreateRequest, admin=Depends(require_admin),
                        db: AsyncSession = Depends(get_db)):
    invite = Invites(
        token=secrets.token_urlsafe(24),
        email=body.email or None,
        role="user",
        expires_at=datetime.now(timezone.utc) + timedelta(days=INVITE_TTL_DAYS),
        created_by=admin.id,
    )
    db.add(invite)
    await db.flush()
    await db.refresh(invite)
    await db.commit()
    return invite_out(invite)


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(csrf_guard)])
async def revoke_invite(invite_id: int, db: AsyncSession = Depends(get_db)):
    invite = await db.get(Invites, invite_id)
    if invite is None:
        raise err(404, "not_found", f"Invite {invite_id} does not exist")
    await db.delete(invite)
    await db.commit()
