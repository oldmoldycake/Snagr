"""API tokens — mirror the token block of types.ts (Phase: MCP layer)."""

from typing import Literal

from pydantic import BaseModel

ApiTokenScope = Literal["read", "write", "runs"]
# canonical order — scopes are stored sorted this way so the UI's preset
# detection (read / read+write / all three) is a plain list comparison
KNOWN_SCOPES: tuple[str, ...] = ("read", "write", "runs")


class ApiToken(BaseModel):
    id: int
    name: str
    scopes: list[ApiTokenScope]
    expires_at: str | None  # None = never
    last_used_at: str | None  # None = never used
    created_at: str


class ApiTokenCreated(ApiToken):
    """POST /api/me/tokens response — the one time the raw token is shown."""

    token: str


# name/scopes are loose here: the mock's 422 validation_error envelope
# (fields.name / fields.scopes / fields.expires_in_days) is the contract, so the
# router validates them itself instead of letting Pydantic answer with FastAPI's
# default detail shape (same reasoning as the channel requests).
class ApiTokenCreateRequest(BaseModel):
    name: str | None = None
    scopes: list[str] | None = None
    expires_in_days: int | None = None  # None = never expires


# --- ORM-row -> schema serializers -------------------------------------------
# (timestamps must go out as ISO-8601 strings, so plain model_validate won't do)


def token_out(t) -> ApiToken:
    return ApiToken(
        id=t.id,
        name=t.name,
        scopes=t.scopes,
        expires_at=t.expires_at.isoformat() if t.expires_at is not None else None,
        last_used_at=t.last_used_at.isoformat() if t.last_used_at is not None else None,
        created_at=t.created_at.isoformat(),
    )


def token_created_out(t, raw: str) -> ApiTokenCreated:
    return ApiTokenCreated(**token_out(t).model_dump(), token=raw)
