"""Catalog tools — categories and the sites that get searched.

Reads are open to every token; writes are admin-only, like REST, because the
catalog is shared: one user's delete_category takes every user's watches and
price history in that category with it."""

from fastmcp import FastMCP

from app.mcp.refs import Ref, resolve_category, resolve_site
from app.mcp.server import DESTRUCTIVE, READ_ONLY, WRITE, caller_session, require_admin
from app.schemas.catalog import Category, Site
from app.services import catalog as catalog_service
from app.services.catalog import build_category


def register(mcp: FastMCP) -> None:
    """Define the catalog tools on the shared server."""

    @mcp.tool(annotations=READ_ONLY)
    async def list_categories() -> list[Category]:
        """Every category (video games, trading cards, …) with its slug, the
        ids of the sites linked to it, how many items it holds, and how many of
        those YOU are currently watching at or below your target ("snagged").
        The catalog itself is shared by every user of the instance."""
        async with caller_session() as (db, user):
            return await catalog_service.list_categories(db, user.id)

    @mcp.tool(annotations=READ_ONLY)
    async def list_sites() -> list[Site]:
        """Every marketplace the agent can search, with its base URL, the
        categories it is linked to, its active listing count, and when a
        listing on it was last checked. Sites are shared by every user."""
        async with caller_session() as (db, _user):
            return await catalog_service.list_sites(db)

    @mcp.tool(auth=WRITE)
    async def create_category(name: str) -> Category:
        """Add a category, e.g. "Game Boy games". The name is trimmed and the
        slug derived from it; a blank name is a `validation_error` and one
        already in use (case-insensitive) is a `duplicate`. Link sites to it
        afterwards with update_category. Admins only (`forbidden` otherwise)."""
        async with caller_session() as (db, user):
            require_admin(user)
            return await catalog_service.create_category(db, name)

    @mcp.tool(auth=WRITE)
    async def update_category(
        category: Ref, name: str | None = None, site_ids: list[Ref] | None = None
    ) -> Category:
        """Rename a category and/or replace the set of sites it is searched on —
        one call for what the REST API splits in two. `category` is an id or
        slug; `site_ids` are ids or names and REPLACE the current set (an empty
        list unlinks every site). Arguments you leave out are left alone.
        Admins only (`forbidden` otherwise)."""
        async with caller_session() as (db, user):
            require_admin(user)
            cat = await resolve_category(db, category)
            if name is not None:
                await catalog_service.update_category(db, cat.id, name, user.id)
            if site_ids is not None:
                ids = [(await resolve_site(db, ref)).id for ref in site_ids]
                await catalog_service.set_category_sites(db, cat.id, ids, user.id)
            return await build_category(db, cat, user.id)

    @mcp.tool(auth=WRITE, annotations=DESTRUCTIVE)
    async def delete_category(category: Ref) -> str:
        """Delete a category AND everything under it: its items, every user's
        watches on them, their listings and price history. There is no undo —
        confirm with the user before calling this. Admins only (`forbidden`
        otherwise)."""
        async with caller_session() as (db, user):
            require_admin(user)
            cat = await resolve_category(db, category)
            await catalog_service.delete_category(db, cat.id)
            return f"Deleted category {cat.name!r} (id {cat.id}) and everything under it"

    @mcp.tool(auth=WRITE)
    async def create_site(name: str, base_url: str) -> Site:
        """Add a marketplace the agent can search, e.g. name "eBay",
        base_url "https://www.ebay.com". Both are trimmed and one trailing
        slash is dropped; blanks are a `validation_error`. Link it to
        categories with update_category — an unlinked site is never searched.
        Admins only (`forbidden` otherwise)."""
        async with caller_session() as (db, user):
            require_admin(user)
            return await catalog_service.create_site(db, name, base_url)

    @mcp.tool(auth=WRITE)
    async def update_site(site: Ref, name: str | None = None, base_url: str | None = None) -> Site:
        """Rename a site or change its base URL (`site` is an id or name).
        Arguments you leave out — or pass empty — are left alone. Admins only
        (`forbidden` otherwise)."""
        async with caller_session() as (db, user):
            require_admin(user)
            resolved = await resolve_site(db, site)
            return await catalog_service.update_site(db, resolved.id, name, base_url)

    @mcp.tool(auth=WRITE, annotations=DESTRUCTIVE)
    async def delete_site(site: Ref) -> str:
        """Delete a site (id or name). A site that still has listings or is
        linked to a category can't be deleted yet — unlink it first with
        update_category and let its listings go. No undo. Admins only
        (`forbidden` otherwise)."""
        async with caller_session() as (db, user):
            require_admin(user)
            resolved = await resolve_site(db, site)
            await catalog_service.delete_site(db, resolved.id)
            return f"Deleted site {resolved.name!r} (id {resolved.id})"
