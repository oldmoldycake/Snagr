"""Instance metadata — the first call the frontend makes on boot.

    GET /api/instance -> InstanceInfo   (endpoints.ts -> getInstance)

Implemented (plan Task 0): registration_open when the REGISTRATION_OPEN toggle
is on, or while the instance has zero users (so the first-ever user bootstraps
as admin). Public — no auth.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User
from app.schemas.auth import InstanceInfo

router = APIRouter(prefix="/api", tags=["instance"])


@router.get("/instance", response_model=InstanceInfo)
async def get_instance(db: AsyncSession = Depends(get_db)) -> InstanceInfo:
    user_count = await db.scalar(select(func.count()).select_from(User))
    return InstanceInfo(
        version=settings.APP_VERSION,
        ntfy_server_url=settings.NTFY_SERVER_URL or None,
        registration_open=settings.REGISTRATION_OPEN or (user_count or 0) == 0,
        oidc_provider_name=settings.OIDC_PROVIDER_NAME if settings.oidc_enabled else None,
        vision_enabled=settings.vision_enabled,
    )
