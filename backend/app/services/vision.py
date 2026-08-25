"""Vision flows — the sixth service, for logic that's more than one query:
the review/library mutations, the authenticity batch lookup that listing
serialization reads, the sidecar upload forwarding, and the post-mutation
rescore.

The rescore is fire-and-forget by design (the grounding pre-pass isolation
contract): the row mutation is the source of truth and is already
committed, so a sidecar hiccup logs a warning and the user's action still
succeeds — stored verdicts catch up on the next successful rescore or scan.
Routers schedule it via BackgroundTasks AFTER the commit.
"""

import logging

import httpx
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import err
from app.models import (
    User,
    VisionListingImages,
    VisionReferences,
    VisionScans,
    Watches,
)
from app.schemas.vision import AuthenticityRead, ReviewConfirmRequest, confidence_str

log = logging.getLogger(__name__)

SIDECAR_TIMEOUT_SECONDS = 30
UPLOAD_TIMEOUT_SECONDS = 120  # embedding a fresh upload includes model inference
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


async def fire_rescore(item_id: int) -> None:
    """Ask the sidecar to re-verdict the item's stored scans (D-V8)."""
    try:
        async with httpx.AsyncClient(timeout=SIDECAR_TIMEOUT_SECONDS) as client:
            resp = await client.post(f"{settings.VISION_SIDECAR_URL}/rescore/{item_id}")
            resp.raise_for_status()
    except Exception as e:
        log.warning(f"Rescore for item {item_id} failed (verdicts catch up next scan): {e}")


async def authenticity_for_listings(
    db: AsyncSession, watch_id: int, urls: list[str]
) -> dict[str, AuthenticityRead]:
    """Authenticity reads for a watch's listings, keyed by listing URL.

    A listing's read is computed, not stored on listings (house pattern #2):
    it joins vision_scans on (watch_id, url). Absent url = never scanned.
    """
    if not settings.vision_enabled or not urls:
        return {}
    rows = (
        await db.execute(
            select(VisionScans, func.count(VisionListingImages.id))
            .outerjoin(VisionListingImages, VisionListingImages.scan_id == VisionScans.id)
            .where(VisionScans.watch_id == watch_id)
            .where(VisionScans.listing_url.in_(urls))
            .group_by(VisionScans.id)
        )
    ).all()
    return {
        scan.listing_url: AuthenticityRead(
            verdict=scan.verdict,
            fake_confidence=confidence_str(scan.fake_confidence),
            image_count=image_count,
            checked_at=scan.scored_at.isoformat(),
        )
        for scan, image_count in rows
    }


async def _own_queue_entry(db: AsyncSession, user: User, entry_id: int):
    """The (image, scan) pair for one of the viewer's own queue entries, or a
    404 — a foreign entry is indistinguishable from an unknown id (D-V11)."""
    row = (
        await db.execute(
            select(VisionListingImages, VisionScans)
            .join(VisionScans, VisionScans.id == VisionListingImages.scan_id)
            .join(Watches, Watches.id == VisionScans.watch_id)
            .where(VisionListingImages.id == entry_id)
            .where(Watches.user_id == user.id)
        )
    ).first()
    if row is None:
        raise err(404, "not_found", f"Review entry {entry_id} does not exist")
    return row


async def confirm_review_entry(
    db: AsyncSession, user: User, entry_id: int, body: ReviewConfirmRequest
) -> VisionReferences:
    """Turn a queue entry into a gold reference (provenance 'human'); the
    committed reference row. The label may flip the suggestion."""
    image, scan = await _own_queue_entry(db, user, entry_id)
    if body.label not in ("real", "fake"):
        raise err(
            422, "validation_error", "Invalid label", fields={"label": "Must be 'real' or 'fake'"}
        )
    if image.review_state != "suggested":
        raise err(409, "already_reviewed", "This entry has already been reviewed")

    reference = VisionReferences(
        item_id=scan.item_id,
        label=body.label,
        variant_tag=(body.variant_tag or "").strip() or None,
        provenance="human",
        embedding=image.embedding,
        model_name=image.model_name,
        object_key=image.object_key,
        source_listing_url=scan.listing_url,
        captured_by=user.id,
        confirmed_by=user.id,
    )
    db.add(reference)
    await db.flush()
    image.review_state = "confirmed"
    image.reference_id = reference.id
    await db.commit()
    return reference


async def discard_review_entry(db: AsyncSession, user: User, entry_id: int) -> int:
    """Delete a queue entry's row (bytes are reclaimed by the sidecar's GC
    sweep); the scan's item_id. An already-reviewed entry has left the queue,
    so it 404s like an unknown id."""
    image, scan = await _own_queue_entry(db, user, entry_id)
    if image.review_state != "suggested":
        raise err(404, "not_found", f"Review entry {entry_id} does not exist")
    await db.execute(delete(VisionListingImages).where(VisionListingImages.id == image.id))
    await db.commit()
    return scan.item_id


async def require_watched_item(db: AsyncSession, user: User, item_id: int) -> None:
    """404 unless the viewer watches the item — an API item IS the viewer's
    watch, so an unwatched item is indistinguishable from an unknown one."""
    watched = await db.scalar(
        select(Watches.id).where(Watches.item_id == item_id, Watches.user_id == user.id)
    )
    if watched is None:
        raise err(404, "not_found", f"Item {item_id} does not exist")


async def revoke_reference(db: AsyncSession, user: User, ref_id: int) -> tuple[int, bool]:
    """Soft-revoke one reference; (item_id, changed). Revoking an already-
    revoked reference is a harmless no-op. References are communal per item,
    so visibility = watching the item."""
    reference = (
        await db.execute(
            select(VisionReferences)
            .join(Watches, Watches.item_id == VisionReferences.item_id)
            .where(VisionReferences.id == ref_id)
            .where(Watches.user_id == user.id)
        )
    ).scalar_one_or_none()
    if reference is None:
        raise err(404, "not_found", f"Reference {ref_id} does not exist")
    if reference.revoked_at is not None:
        return reference.item_id, False
    reference.revoked_at = func.now()
    await db.commit()
    return reference.item_id, True


async def revoke_auto_references(db: AsyncSession, user: User, item_id: int) -> int:
    """Revoke every live auto-promoted reference of an item (D-V7's escape
    hatch for a drifted library); the revoked count."""
    await require_watched_item(db, user, item_id)
    result = await db.execute(
        update(VisionReferences)
        .where(VisionReferences.item_id == item_id)
        .where(VisionReferences.provenance == "auto")
        .where(VisionReferences.revoked_at.is_(None))
        .values(revoked_at=func.now())
    )
    await db.commit()
    return result.rowcount


async def forward_upload(
    item_id: int,
    label: str,
    variant_tag: str | None,
    user_id: int,
    filename: str,
    data: bytes,
    content_type: str,
) -> dict:
    """Hand an uploaded photo to the sidecar to embed + store as gold
    (provenance 'upload'); the sidecar's reference row as a dict. The sidecar
    owns the write — the backend never touches S3 or the model (D-V1/D-V3)."""
    form: dict[str, str] = {"item_id": str(item_id), "label": label, "user_id": str(user_id)}
    if variant_tag:
        form["variant_tag"] = variant_tag
    try:
        async with httpx.AsyncClient(timeout=UPLOAD_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.VISION_SIDECAR_URL}/references",
                data=form,
                files={"file": (filename, data, content_type)},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as e:
        raise err(503, "vision_unavailable", "The vision service is unavailable") from e
