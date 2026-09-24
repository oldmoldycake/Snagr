"""Vision tools — the photo-authenticity review queue and reference library.
Tagged `vision`: the server hides them while the sidecar is unconfigured,
and the mutations answer `vision_unavailable` if called anyway."""

from fastmcp import FastMCP

from app.mcp.server import DESTRUCTIVE, READ_ONLY, WRITE, caller_session
from app.schemas.common import Paginated
from app.schemas.vision import (
    ReferenceImage,
    ReviewConfirmRequest,
    ReviewQueueEntry,
    reference_out,
)
from app.services import vision as vision_service


def register(mcp: FastMCP) -> None:
    """Define the vision tools on the shared server."""

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

    @mcp.tool(auth=WRITE, tags={"vision"})
    async def confirm_review_entry(
        entry_id: int, label: str, variant_tag: str | None = None
    ) -> ReferenceImage:
        """Give the human verdict on a queued photo: label it "real" or "fake"
        and it joins the item's reference library (provenance `human`); the
        item's stored verdicts are then rescored. `variant_tag` names a look
        that differs from the main one, e.g. "alternate art". Errors:
        `not_found` (unknown, or another user's capture), `already_reviewed`,
        `validation_error` for any other label."""
        async with caller_session() as (db, user):
            vision_service.require_vision()
            body = ReviewConfirmRequest(label=label, variant_tag=variant_tag)
            reference = await vision_service.confirm_review_entry(db, user, entry_id, body)
            # after the commit, on purpose: the confirmation stands even if
            # the rescore can't reach the sidecar (see services/vision.py)
            vision_service.schedule_rescore(reference.item_id)
            return reference_out(reference, user)

    @mcp.tool(auth=WRITE, tags={"vision"}, annotations=DESTRUCTIVE)
    async def discard_review_entry(entry_id: int) -> str:
        """Drop a queued photo without a verdict — it is neither real nor fake
        evidence, e.g. a packaging shot. Errors: `not_found` (unknown, another
        user's, or already reviewed)."""
        async with caller_session() as (db, user):
            vision_service.require_vision()
            item_id = await vision_service.discard_review_entry(db, user, entry_id)
            vision_service.schedule_rescore(item_id)
            return f"Discarded review entry {entry_id}"

    @mcp.tool(auth=WRITE, tags={"vision"}, annotations=DESTRUCTIVE)
    async def revoke_reference(reference_id: int) -> str:
        """Retire a reference photo from an item's library — scoring stops
        using it, the row stays for audit. Revoking again is a harmless
        no-op. `not_found` for a reference on an item you don't watch."""
        async with caller_session() as (db, user):
            vision_service.require_vision()
            item_id, changed = await vision_service.revoke_reference(db, user, reference_id)
            if changed:
                vision_service.schedule_rescore(item_id)
            return f"Revoked reference {reference_id}"
