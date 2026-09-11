"""Catalog tools — categories and the sites that get searched."""

from fastmcp import FastMCP

from app.mcp.server import READ_ONLY, caller_session
from app.schemas.catalog import Category, Site
from app.services import catalog as catalog_service


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=READ_ONLY)
    async def list_categories() -> list[Category]:
        """Every category (video games, trading cards, …) with its slug, the
        ids of the sites linked to it, how many items it holds, and how many of
        those are currently at or below their target ("snagged"). The catalog
        is shared by every user of the instance."""
        async with caller_session() as (db, _user):
            return await catalog_service.list_categories(db)

    @mcp.tool(annotations=READ_ONLY)
    async def list_sites() -> list[Site]:
        """Every marketplace the agent can search, with its base URL, the
        categories it is linked to, its active listing count, and when a
        listing on it was last checked. Sites are shared by every user."""
        async with caller_session() as (db, _user):
            return await catalog_service.list_sites(db)
