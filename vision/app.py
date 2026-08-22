"""FastAPI app for the vision sidecar — the fourth Snagr component (D-V1).

Owns everything vision: weights, embedding, image fetching/storage, scoring,
promotion, GC. The agent and backend are clients only. Handlers are sync
`def` on purpose: embedding is CPU-bound and FastAPI's threadpool is the
boring right tool — the async-everywhere rule is a request-path rule for
backend/, not here.

LAN-internal and unauthenticated in v1 (D-V1) — never expose publicly.
"""

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from io import BytesIO
from typing import Annotated

import embedder
import fetcher
import promotion
import scoring
import storage
import sweep
from config import EMBEDDING_DIM, VISION_MODEL
from db import (
    SessionLocal,
    Users,
    VisionListingImages,
    VisionReferences,
    VisionScans,
    Watches,
)
from fastapi import FastAPI, Form, HTTPException, Response, UploadFile
from PIL import Image
from pydantic import BaseModel
from sqlalchemy import delete, func, select


@asynccontextmanager
async def lifespan(_: FastAPI):
    dim = embedder.load()
    if dim is not None and dim != EMBEDDING_DIM:
        raise RuntimeError(
            f"{VISION_MODEL} embeds at dim {dim}, but the schema stores "
            f"vector({EMBEDDING_DIM}) (migration 009). Refusing to start — a mismatched "
            f"model would write garbage. Point VISION_MODEL at a dim-{EMBEDDING_DIM} "
            f"checkpoint, or migrate the embedding columns deliberately first."
        )
    storage.store.ensure_bucket()
    sweep.start_daily(storage.store)
    yield


app = FastAPI(title="Snagr vision sidecar", lifespan=lifespan)


class CheckImagesRequest(BaseModel):
    watch_id: int
    item_id: int
    listing_url: str
    image_urls: list[str]
    llm_authenticity_read: str | None = None  # looks_authentic | suspect | unsure


def _live_reference_embeddings(session, item_id: int) -> tuple[list, list]:
    """The item's live gold library as (real, fake) embedding lists."""
    rows = session.execute(
        select(VisionReferences.label, VisionReferences.embedding)
        .where(VisionReferences.item_id == item_id)
        .where(VisionReferences.revoked_at.is_(None))
    ).all()
    real = [embedding for label, embedding in rows if label == "real"]
    fake = [embedding for label, embedding in rows if label == "fake"]
    return real, fake


def _vouched_gold_counts(session, item_id: int) -> dict[str, int]:
    """Live human/upload reference counts per label — the min-gold guardrail
    input; provenance 'auto' rows deliberately don't count (D-V7)."""
    rows = session.execute(
        select(VisionReferences.label, func.count())
        .where(VisionReferences.item_id == item_id)
        .where(VisionReferences.revoked_at.is_(None))
        .where(VisionReferences.provenance.in_(("human", "upload")))
        .group_by(VisionReferences.label)
    ).all()
    counts = {"real": 0, "fake": 0}
    counts.update(dict(rows))
    return counts


def _stored_embedding(session, object_key: str):
    """A previously computed embedding for these exact bytes under the current
    model, or None — embed once, score anywhere (D-V8)."""
    for column_owner in (VisionListingImages, VisionReferences):
        embedding = session.scalars(
            select(column_owner.embedding)
            .where(column_owner.object_key == object_key)
            .where(column_owner.model_name == VISION_MODEL)
            .limit(1)
        ).first()
        if embedding is not None:
            return embedding
    return None


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


@app.post("/check-images")
def check_images(req: CheckImagesRequest):
    """Fetch, embed, persist, and score a candidate listing's photos against
    the item's gold library. Persistence never depends on the listing being
    saved — rejected listings are where fake reference candidates come from
    (D-V2)."""
    if not embedder.loaded():
        raise HTTPException(status_code=503, detail=embedder.LICENSE_HELP)

    with SessionLocal() as session:
        owner = session.execute(
            select(Users)
            .join(Watches, Watches.user_id == Users.id)
            .where(Watches.id == req.watch_id)
        ).scalar_one_or_none()
        if owner is None:
            raise HTTPException(status_code=404, detail=f"watch {req.watch_id} not found")

        real_refs, fake_refs = _live_reference_embeddings(session, req.item_id)
        vouched = _vouched_gold_counts(session, req.item_id)

        captures: list[tuple[str, str, object, scoring.ImageScore]] = []
        skipped: list[str] = []
        embedded_now: dict[str, object] = {}  # same hash twice in one call embeds once
        for url in dict.fromkeys(req.image_urls):
            fetched = fetcher.fetch_image(url, referer=req.listing_url)
            if fetched is None:
                skipped.append(url)
                continue
            data, content_type = fetched
            key = hashlib.sha256(data).hexdigest()
            embedding = embedded_now.get(key)
            if embedding is None:
                embedding = _stored_embedding(session, key)
            if embedding is None:
                embedding = embedder.embed([data])[0]
            if not storage.store.exists(key):
                storage.store.put(key, data, content_type)
            embedded_now[key] = embedding
            captures.append(
                (url, key, embedding, scoring.score_image(embedding, real_refs, fake_refs))
            )

        verdict, listing_confidence = scoring.rollup([score for _, _, _, score in captures])
        auto_reject = listing_confidence is not None and listing_confidence >= float(
            owner.vision_auto_reject_fake
        )

        # one scan per (watch, listing_url): a rediscovered listing refreshes —
        # images are replaced and the verdict (auto_reject included: this IS
        # scan time) is restamped
        scan = session.execute(
            select(VisionScans)
            .where(VisionScans.watch_id == req.watch_id)
            .where(VisionScans.listing_url == req.listing_url)
        ).scalar_one_or_none()
        if scan is None:
            scan = VisionScans(watch_id=req.watch_id, listing_url=req.listing_url)
            session.add(scan)
        else:
            session.execute(
                delete(VisionListingImages).where(VisionListingImages.scan_id == scan.id)
            )
        scan.item_id = req.item_id
        scan.llm_authenticity_read = req.llm_authenticity_read
        scan.verdict = verdict
        scan.fake_confidence = _round(listing_confidence)
        scan.auto_reject = auto_reject
        scan.scored_at = datetime.now(UTC)
        session.flush()

        images_out = []
        for url, key, embedding, score in captures:
            image_row = VisionListingImages(
                scan_id=scan.id,
                image_url=url,
                object_key=key,
                embedding=embedding,
                model_name=VISION_MODEL,
                real_similarity=_round(score.real_similarity),
                fake_similarity=_round(score.fake_similarity),
                fake_confidence=_round(score.fake_confidence),
            )
            suggestion = promotion.suggest_label(score)
            image_row.suggested_label = suggestion
            image_row.review_state = "suggested" if suggestion else "none"
            if suggestion and promotion.auto_promotable(
                suggestion,
                score,
                req.llm_authenticity_read,
                vouched[suggestion],
                float(owner.vision_auto_promote_real),
                float(owner.vision_auto_promote_fake),
            ):
                reference = VisionReferences(
                    item_id=req.item_id,
                    label=suggestion,
                    provenance="auto",
                    embedding=embedding,
                    model_name=VISION_MODEL,
                    object_key=key,
                    source_listing_url=req.listing_url,
                    captured_by=owner.id,
                    confirmed_by=None,
                )
                session.add(reference)
                session.flush()
                # promoted images leave the queue; the reference's provenance
                # 'auto' is what marks nobody vouched for it
                image_row.reference_id = reference.id
                image_row.review_state = "confirmed"
            session.add(image_row)
            images_out.append(
                {
                    "image_url": url,
                    "fake_confidence": _round(score.fake_confidence),
                    "suggested_label": suggestion,
                }
            )
        session.commit()

    return {
        "verdict": verdict,
        "fake_confidence": _round(listing_confidence),
        "auto_reject": auto_reject,
        "images": images_out,
        "skipped": skipped,
    }


@app.post("/rescore/{item_id}")
def rescore_item(item_id: int):
    """Recompute every stored scan for an item from stored vectors — no
    model needed, so this works even degraded (D-V8: embed once, score
    anywhere). Updates verdicts, confidences, and queue suggestions only:
    never auto_reject, never promotion (D-V8 boundaries)."""
    with SessionLocal() as session:
        real_refs, fake_refs = _live_reference_embeddings(session, item_id)
        scans = session.scalars(select(VisionScans).where(VisionScans.item_id == item_id)).all()
        for scan in scans:
            images = session.scalars(
                select(VisionListingImages).where(VisionListingImages.scan_id == scan.id)
            ).all()
            scores = []
            for image_row in images:
                score = scoring.score_image(image_row.embedding, real_refs, fake_refs)
                image_row.real_similarity = _round(score.real_similarity)
                image_row.fake_similarity = _round(score.fake_similarity)
                image_row.fake_confidence = _round(score.fake_confidence)
                suggestion = promotion.suggest_label(score)
                image_row.suggested_label = suggestion
                # only none ↔ suggested may flip; confirmed/discarded are settled
                if image_row.review_state == "none" and suggestion:
                    image_row.review_state = "suggested"
                elif image_row.review_state == "suggested" and not suggestion:
                    image_row.review_state = "none"
                scores.append(score)
            verdict, listing_confidence = scoring.rollup(scores)
            scan.verdict = verdict
            scan.fake_confidence = _round(listing_confidence)
        session.commit()
    return {"rescored": len(scans)}


@app.post("/references", status_code=201)
def upload_reference(
    file: UploadFile,
    item_id: Annotated[int, Form()],
    label: Annotated[str, Form()],
    user_id: Annotated[int, Form()],
    variant_tag: Annotated[str | None, Form()] = None,
):
    """Embed and store a manually uploaded photo as a gold reference —
    communal from the start, provenance 'upload' (D-V7)."""
    if not embedder.loaded():
        raise HTTPException(status_code=503, detail=embedder.LICENSE_HELP)
    if label not in ("real", "fake"):
        raise HTTPException(status_code=422, detail="label must be 'real' or 'fake'")
    data = file.file.read()
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
            content_type = Image.MIME.get(image.format, "application/octet-stream")
    except Exception as exc:
        raise HTTPException(status_code=422, detail="file is not a decodable image") from exc

    key = hashlib.sha256(data).hexdigest()
    embedding = embedder.embed([data])[0]
    with SessionLocal() as session:
        if not storage.store.exists(key):
            storage.store.put(key, data, content_type)
        reference = VisionReferences(
            item_id=item_id,
            label=label,
            variant_tag=variant_tag or None,
            provenance="upload",
            embedding=embedding,
            model_name=VISION_MODEL,
            object_key=key,
            source_listing_url=None,
            captured_by=user_id,
            confirmed_by=user_id,
        )
        session.add(reference)
        session.commit()
        return {
            "id": reference.id,
            "item_id": reference.item_id,
            "label": reference.label,
            "variant_tag": reference.variant_tag,
            "provenance": reference.provenance,
            "object_key": reference.object_key,
            "created_at": reference.created_at.isoformat(),
        }


@app.get("/images/{object_key}")
def get_image(object_key: str):
    """Stream stored bytes — the upstream of the backend's same-origin image
    proxy (D-V3); the browser never sees the object store."""
    stored = storage.store.get(object_key)
    if stored is None:
        raise HTTPException(status_code=404, detail="no such image")
    data, content_type = stored
    return Response(content=data, media_type=content_type)


@app.get("/health")
def health():
    return {
        "status": "ok" if embedder.loaded() else "degraded",
        "model": VISION_MODEL,
        "dim": EMBEDDING_DIM if embedder.loaded() else None,
        "weights_present": embedder.loaded(),
    }
