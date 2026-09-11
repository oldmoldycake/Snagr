"""Vision tools — the photo-authenticity review queue and reference library.
Tagged `vision`: the server hides them while the sidecar is unconfigured."""

from fastmcp import FastMCP

from app.mcp.server import READ_ONLY, caller_session
from app.schemas.common import Paginated
from app.schemas.vision import ReferenceImage, ReviewQueueEntry
from app.services import vision as vision_service


def register(mcp: FastMCP) -> None:
    @mcp.tool(annotations=READ_ONLY, tags={"vision"})
    async def list_review_queue(
        item: int | None = None, page: int = 1, per_page: int = 25
    ) -> Paginated[ReviewQueueEntry]:
        """Listing photos the agent captured on this user's hunts that look
        like a known real or fake and await a human verdict, newest first —
        each with the suggested label and confidence. Optionally one item's."""
        async with caller_session() as (db, user):
            return await vision_service.list_review_queue(db, user, item, page, per_page)

    @mcp.tool(annotations=READ_ONLY, tags={"vision"})
    async def list_references(item: int) -> list[ReferenceImage]:
        """An item's reference library: the confirmed real and fake photos its
        listings are compared against, newest first, with label, variant tag
        and provenance (human | upload | auto). Shared by everyone who watches
        the item; `not_found` unless you watch it."""
        async with caller_session() as (db, user):
            return await vision_service.list_references(db, user, item)
