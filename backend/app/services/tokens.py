"""API-token authentication — the one lookup both bearer surfaces share:
`core/deps.current_user` (REST) and the MCP endpoint's token verifier.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_api_token
from app.models import ApiTokens, User

# last_used_at is a coarse "is this still in use?" hint for the Settings page,
# not an audit log — stamping it on every request would turn every GET into a
# write, so a token is re-stamped at most once a minute.
LAST_USED_GRANULARITY = timedelta(minutes=1)


async def authenticate_token(db: AsyncSession, raw: str) -> tuple[User, ApiTokens] | None:
    """Resolve a raw bearer token to (owner, token row), or None when the token
    is unknown or expired, or its owner has been deactivated."""
    token = await db.scalar(select(ApiTokens).where(ApiTokens.token_hash == hash_api_token(raw)))
    if token is None:
        return None
    now = datetime.now(UTC)
    if token.expires_at is not None and token.expires_at <= now:
        return None
    user = await db.get(User, token.user_id)
    if user is None or not user.is_active:
        return None
    if token.last_used_at is None or now - token.last_used_at >= LAST_USED_GRANULARITY:
        token.last_used_at = now
        await db.commit()
    return user, token
