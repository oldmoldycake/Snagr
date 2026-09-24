"""Vision surfaces: review queue, reference library, image proxy —
/api/vision/* and /api/items/{id}/references*. Auth required everywhere; flows
live in services/vision.py.

prefix is /api because the router spans both of those trees.

Off-mode: with the sidecar unconfigured the two GET list routes
return empty data, and everything that needs the sidecar or its stores —
every mutation plus the image proxy — answers 503 vision_unavailable.
"""

from typing import Annotated

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, Form, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from app.config import settings
from app.core.deps import csrf_guard, current_user
from app.core.errors import err
from app.database import get_db
from app.models import (
    VisionListingImages,
    VisionReferences,
    VisionScans,
    Watches,
)
from app.schemas.common import DataList, Paginated
from app.schemas.vision import (
    ReferenceImage,
    ReviewConfirmRequest,
    ReviewQueueEntry,
    RevokeAutoResponse,
    reference_out,
)
from app.services import vision as vision_service

router = APIRouter(prefix="/api", tags=["vision"], dependencies=[Depends(csrf_guard)])


@router.get("/vision/review-queue", response_model=Paginated[ReviewQueueEntry])
async def list_review_queue(
    item_id: int | None = None,
    page: int = 1,
    per_page: int = 25,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Captured photos awaiting the caller's review, newest first; only what the
    caller's own watches captured, admins included."""
    return await vision_service.list_review_queue(db, user, item_id, page, per_page)


@router.post(
    "/vision/review-queue/{entry_id}/confirm",
    response_model=ReferenceImage,
    status_code=status.HTTP_201_CREATED,
)
async def confirm_review_entry(
    entry_id: int,
    body: ReviewConfirmRequest,
    background: BackgroundTasks,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Confirm a queue entry as a real/fake reference, then rescore the item.

    404 for another user's entry; 409 already_reviewed once handled."""
    vision_service.require_vision()
    reference = await vision_service.confirm_review_entry(db, user, entry_id, body)
    # after the commit, on purpose: the confirmation stands even if the
    # rescore can't reach the sidecar (see services/vision.py)
    background.add_task(vision_service.fire_rescore, reference.item_id)
    return reference_out(reference, user)


@router.delete("/vision/review-queue/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def discard_review_entry(
    entry_id: int,
    background: BackgroundTasks,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Drop a queue entry without keeping it as a reference, then rescore the item."""
    vision_service.require_vision()
    item_id = await vision_service.discard_review_entry(db, user, entry_id)
    background.add_task(vision_service.fire_rescore, item_id)


@router.get("/items/{item_id}/references", response_model=DataList[ReferenceImage])
async def list_references(
    item_id: int, user=Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """An item's shared reference library, newest first; 404 when unwatched."""
    return DataList(data=await vision_service.list_references(db, user, item_id))


@router.post(
    "/items/{item_id}/references",
    response_model=ReferenceImage,
    status_code=status.HTTP_201_CREATED,
)
async def upload_reference(
    item_id: int,
    file: UploadFile,
    label: Annotated[str, Form()],
    background: BackgroundTasks,
    variant_tag: Annotated[str | None, Form()] = None,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a photo as a real/fake reference for a watched item, then rescore it.

    422 validation_error for a bad label, a non-image, or a file over 10 MB; 503
    vision_unavailable when the sidecar can't be reached."""
    vision_service.require_vision()
    await vision_service.require_watched_item(db, user, item_id)
    if label not in ("real", "fake"):
        raise err(
            422, "validation_error", "Invalid label", fields={"label": "Must be 'real' or 'fake'"}
        )
    if not (file.content_type or "").startswith("image/"):
        raise err(
            422,
            "validation_error",
            "Upload must be an image file",
            fields={"file": "Must be an image file"},
        )
    data = await file.read()
    if len(data) > vision_service.MAX_UPLOAD_BYTES:
        raise err(
            422,
            "validation_error",
            "Image must be 10 MB or smaller",
            fields={"file": "Must be 10 MB or smaller"},
        )

    row = await vision_service.forward_upload(
        item_id=item_id,
        label=label,
        variant_tag=(variant_tag or "").strip() or None,
        user_id=user.id,
        filename=file.filename or "upload",
        data=data,
        content_type=file.content_type or "application/octet-stream",
    )
    background.add_task(vision_service.fire_rescore, item_id)
    # the sidecar owns the write; its response row is the source for the shape
    return ReferenceImage(
        id=row["id"],
        item_id=row["item_id"],
        label=row["label"],
        variant_tag=row["variant_tag"],
        provenance=row["provenance"],
        image_url=f"/api/vision/images/{row['object_key']}",
        source_listing_url=None,  # uploads have no source listing
        revoked=False,
        created_at=row["created_at"],
    )


@router.delete("/vision/references/{ref_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_reference(
    ref_id: int,
    background: BackgroundTasks,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke a reference of an item the caller watches; revoking twice is a no-op."""
    vision_service.require_vision()
    item_id, changed = await vision_service.revoke_reference(db, user, ref_id)
    if changed:
        background.add_task(vision_service.fire_rescore, item_id)


@router.post("/items/{item_id}/references/revoke-auto", response_model=RevokeAutoResponse)
async def revoke_auto_references(
    item_id: int,
    background: BackgroundTasks,
    user=Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke every live auto-promoted reference of an item — the way out when
    the library has drifted. Returns how many were revoked."""
    vision_service.require_vision()
    revoked = await vision_service.revoke_auto_references(db, user, item_id)
    if revoked:
        background.add_task(vision_service.fire_rescore, item_id)
    return RevokeAutoResponse(revoked=revoked)


@router.get("/vision/images/{object_key}")
async def get_image(
    object_key: str, user=Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """Stream stored bytes from the sidecar — the browser never talks to the
    object store. Entitlement: the key backs a live reference of an
    item the viewer watches, or one of the viewer's own captures, or the
    viewer is admin; anything else 404s like an unknown key."""
    vision_service.require_vision()
    if user.role != "admin":
        own_capture = (
            select(VisionListingImages.id)
            .join(VisionScans, VisionScans.id == VisionListingImages.scan_id)
            .join(Watches, Watches.id == VisionScans.watch_id)
            .where(VisionListingImages.object_key == object_key)
            .where(Watches.user_id == user.id)
        )
        communal_reference = (
            select(VisionReferences.id)
            .join(Watches, Watches.item_id == VisionReferences.item_id)
            .where(VisionReferences.object_key == object_key)
            .where(VisionReferences.revoked_at.is_(None))
            .where(Watches.user_id == user.id)
        )
        allowed = await db.scalar(select(or_(own_capture.exists(), communal_reference.exists())))
        if not allowed:
            raise err(404, "not_found", "No such image")

    client = httpx.AsyncClient(timeout=vision_service.SIDECAR_TIMEOUT_SECONDS)
    try:
        request = client.build_request("GET", f"{settings.VISION_SIDECAR_URL}/images/{object_key}")
        upstream = await client.send(request, stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        raise err(503, "vision_unavailable", "The vision service is unavailable") from e
    if upstream.status_code != 200:
        await upstream.aclose()
        await client.aclose()
        raise err(404, "not_found", "No such image")

    async def _close() -> None:
        await upstream.aclose()
        await client.aclose()

    return StreamingResponse(
        upstream.aiter_bytes(),
        media_type=upstream.headers.get("content-type", "application/octet-stream"),
        background=BackgroundTask(_close),
    )
