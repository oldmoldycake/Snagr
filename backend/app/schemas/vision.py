"""Vision / authenticity schemas — mirror the "Vision / authenticity" block
of types.ts.

The verdict language is asymmetric on purpose (D-V5): leans_fake means
"photos consistent with known fakes" — a strong signal; leans_real means
"photos match known-real references" — weak reassurance only, never
"verified authentic". Scam listings reuse stolen photos of genuine items.
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

AuthenticityVerdict = Literal["leans_real", "leans_fake", "inconclusive"]
ReferenceLabel = Literal["real", "fake"]
ReferenceProvenance = Literal["human", "upload", "auto"]
LlmAuthenticityRead = Literal["looks_authentic", "suspect", "unsure"]


class AuthenticityRead(BaseModel):
    verdict: AuthenticityVerdict
    fake_confidence: str | None  # 0–1 decimal string; null = library couldn't score it
    image_count: int
    checked_at: str


class ReviewQueueEntry(BaseModel):
    id: int
    item_id: int
    item_name: str
    image_url: str  # same-origin proxy path: /api/vision/images/{key}
    listing_url: str
    suggested_label: ReferenceLabel
    confidence: str  # 0–1 decimal string backing the suggestion
    llm_authenticity_read: LlmAuthenticityRead | None
    created_at: str


class ReviewConfirmRequest(BaseModel):
    # label is a plain str so the oracle's 422 validation_error envelope (with
    # a fields map) applies — a Literal here would produce FastAPI's own shape
    label: str
    variant_tag: str | None = None


class ReferenceImage(BaseModel):
    id: int
    item_id: int
    label: ReferenceLabel
    variant_tag: str | None
    provenance: ReferenceProvenance
    image_url: str
    source_listing_url: str | None  # null unless the viewer captured it or is admin
    revoked: bool
    created_at: str


class RevokeAutoResponse(BaseModel):
    revoked: int


# --- ORM-row -> schema serializers -------------------------------------------


def confidence_str(value) -> str | None:
    """A stored NUMERIC(5,4) as the contract's 2-decimal string ("0.85")."""
    return None if value is None else f"{Decimal(value):.2f}"


def reference_out(r, viewer) -> ReferenceImage:
    return ReferenceImage(
        id=r.id,
        item_id=r.item_id,
        label=r.label,
        variant_tag=r.variant_tag,
        provenance=r.provenance,
        image_url=f"/api/vision/images/{r.object_key}",
        # a reference's source listing is visible only to its capturer and admins (D-V11)
        source_listing_url=(
            r.source_listing_url if viewer.role == "admin" or r.captured_by == viewer.id else None
        ),
        revoked=r.revoked_at is not None,
        created_at=r.created_at.isoformat(),
    )


def queue_entry_out(image, scan, item_name: str) -> ReviewQueueEntry:
    # the queue shows the confidence BACKING the suggestion: the fake side for
    # fake suggestions, the real side (1 − fake) for real ones
    confidence = (
        Decimal(image.fake_confidence)
        if image.suggested_label == "fake"
        else Decimal(1) - Decimal(image.fake_confidence)
    )
    return ReviewQueueEntry(
        id=image.id,
        item_id=scan.item_id,
        item_name=item_name,
        image_url=f"/api/vision/images/{image.object_key}",
        listing_url=scan.listing_url,
        suggested_label=image.suggested_label,
        confidence=f"{confidence:.2f}",
        llm_authenticity_read=scan.llm_authenticity_read,
        created_at=image.created_at.isoformat(),
    )
