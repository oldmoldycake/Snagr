"""Orientation tools — what this instance is and who the token is."""

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token

from app.mcp.schemas import Whoami
from app.mcp.server import READ_ONLY, caller_session
from app.routers.instance import get_instance as instance_info
from app.schemas.auth import InstanceInfo, user_out


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def get_instance() -> InstanceInfo:
        """What this Snagr instance has switched on: its version, whether photo
        authenticity checks (vision) are configured, and whether a ntfy server
        exists for notifications. Call it once to learn which tools apply."""
        async with caller_session() as (db, _user):
            # the router's function is plain Python over a session — no HTTP in it
            return await instance_info(db)

    @mcp.tool(annotations=READ_ONLY)
    async def whoami() -> Whoami:
        """The account this token acts as, and the scopes it carries (read,
        write, jobs). Tools you lack the scope for are simply not listed."""
        async with caller_session() as (_db, user):
            return Whoami(user=user_out(user), scopes=list(get_access_token().scopes))
