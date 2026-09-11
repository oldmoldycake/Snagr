"""The FastMCP server: bearer auth, the error envelope, and the app factory.

Auth is bearer only — cookies are ignored on this endpoint, so the CSRF
header is irrelevant here and a browser can never be tricked into calling it.
The verifier is services.tokens.authenticate_token, the same lookup REST
bearer auth uses; the token's scopes gate tools (`auth=require_scopes(...)`
on a tool hides it from tokens that lack the scope).

An ApiError raised anywhere inside a tool leaves as a tool error whose text
is the REST envelope, {"error": {code, message, fields?}} — an agent reads
`validation_error` / `not_found` exactly as the frontend does. The conversion
lives in caller_session(), the context every tool body runs in: fastmcp has
already wrapped a tool's exception in its own generic error by the time a
middleware sees it, so a middleware is the wrong place.
"""

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from mcp_types import ToolAnnotations
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.applications import Starlette

from app.config import settings
from app.core.errors import ApiError, err
from app.database import _sessionmaker
from app.models import User
from app.services.tokens import authenticate_token

MCP_PATH = "/api/mcp"

READ_ONLY = ToolAnnotations(read_only_hint=True)
DESTRUCTIVE = ToolAnnotations(destructive_hint=True)

INSTRUCTIONS = """\
Snagr is a self-hosted price tracker: the user watches items (a shared catalog
entry plus their own target price, criteria and site subset), an agent finds
and re-checks marketplace listings for them, and notifications fire when a
listing crosses the target.

Conventions: every price is a decimal string ("549.99", never a number) and
every timestamp is ISO-8601 UTC. Categories can be addressed by id or slug and
sites by id or name; items only by id (list_items finds them). Anything you
can't see with this token doesn't exist — a missing item, run or listing is a
`not_found` error, never a hint. Read tools are safe to call freely; write
tools change the user's real data, and trigger_run starts a paid agent run.
"""


class SnagrTokenVerifier(TokenVerifier):
    """Bearer auth for /api/mcp — the api_tokens lookup REST uses, so a token
    revoked in Settings stops working here in the same instant."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if not settings.MCP_ENABLED:
            return None
        async with _sessionmaker()() as db:
            hit = await authenticate_token(db, token)
        if hit is None:
            return None
        user, row = hit
        return AccessToken(
            token=token,
            client_id="snagr-api-token",
            scopes=list(row.scopes),
            subject=str(user.id),
            claims={"user_id": user.id},
        )


def _envelope(code: str, message: str, **extra) -> str:
    """The REST error envelope as tool-error text — routers/core/errors.py's
    JSON body, byte for byte."""
    return json.dumps({"error": {"code": code, "message": message, **extra}})


class VisionGate(Middleware):
    """Hide the vision tools while the sidecar is unconfigured — the tool-list
    twin of InstanceInfo.vision_enabled hiding the UI. Checked per request,
    not at startup, so it follows the setting (and the tests' monkeypatch)."""

    async def on_list_tools(self, context: MiddlewareContext, call_next: CallNext) -> Sequence:
        tools = await call_next(context)
        if settings.vision_enabled:
            return tools
        return [tool for tool in tools if "vision" not in (tool.tags or set())]


mcp = FastMCP(
    "Snagr",
    instructions=INSTRUCTIONS,
    auth=SnagrTokenVerifier(),
    middleware=[VisionGate()],
)


@asynccontextmanager
async def caller_session() -> AsyncIterator[tuple[AsyncSession, User]]:
    """A session for one tool call plus the token's owner. The endpoint is
    gated by the bearer middleware, so a token is always present here; the
    owner is re-read so a deactivation between verify and call still bites."""
    token = get_access_token()
    async with _sessionmaker()() as db:
        try:
            user = await db.get(User, token.claims["user_id"])
            if user is None or not user.is_active:
                raise err(401, "unauthenticated", "This token's account is no longer active")
            yield db, user
        except ApiError as e:
            raise ToolError(_envelope(e.code, e.message, **e.extra)) from e
        except SQLAlchemyError as e:
            raise ToolError(_envelope("db_unavailable", "Could not reach the database")) from e


def build_mcp_app() -> Starlette:
    """The ASGI app main.py registers at MCP_PATH. Streamable HTTP, stateless
    (no session affinity needed under several workers) and JSON responses
    (no SSE for a proxy to buffer). Host/origin protection is off: the app
    sits behind the operator's proxy, so the Host header is whatever they
    chose — the bearer token is the auth."""
    from app.mcp import tools  # here, not at module top: tools import `mcp` from this module

    tools.register(mcp)
    return mcp.http_app(
        path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        host_origin_protection=False,
    )
