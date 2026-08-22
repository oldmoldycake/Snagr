"""POST /rescore/{item_id}: confirms/revocations re-verdict stored vectors
with no re-inference — and respect the D-V8 boundaries (never auto_reject,
never promotion)."""

from datetime import UTC, datetime

import embedder
from db import SessionLocal, VisionListingImages, VisionReferences, VisionScans
from sqlalchemy import select, update

from tests.conftest import vec

LISTING = "https://market.test/listing/1"


def _capture(client, graph, fake_embedder, fetches):
    """One scanned photo at 40° — leans_real against a real-only library
    (s_real ≈ 0.766: below the 0.80 suggestion bar, so review_state 'none')."""
    fetches["https://cdn.test/p.jpg"] = (b"photo", "image/jpeg")
    fake_embedder.registry[b"photo"] = vec(40)
    res = client.post(
        "/check-images",
        json={
            "watch_id": graph.watch_id,
            "item_id": graph.item_id,
            "listing_url": LISTING,
            "image_urls": ["https://cdn.test/p.jpg"],
            "llm_authenticity_read": "suspect",
        },
    )
    assert res.status_code == 200
    assert res.json()["verdict"] == "leans_real"


def _scan(graph):
    with SessionLocal() as session:
        return session.execute(
            select(VisionScans).where(VisionScans.item_id == graph.item_id)
        ).scalar_one()


def _image(graph):
    with SessionLocal() as session:
        return session.execute(select(VisionListingImages)).scalar_one()


def _revoke_fakes(item_id):
    with SessionLocal() as session:
        session.execute(
            update(VisionReferences)
            .where(VisionReferences.item_id == item_id)
            .where(VisionReferences.label == "fake")
            .values(revoked_at=datetime.now(UTC))
        )
        session.commit()


def test_confirmations_and_revocations_flip_verdicts_from_stored_vectors(
    client, graph, add_reference, fake_embedder, fetches
):
    add_reference(graph.item_id, "real", vec(0))
    _capture(client, graph, fake_embedder, fetches)
    assert _scan(graph).auto_reject is False

    # a human confirms fakes that sit exactly where the photo does — three of
    # them, so every capture-time promotion guardrail WOULD pass
    for i in range(3):
        add_reference(graph.item_id, "fake", vec(40), object_key=f"fk{i}")
    res = client.post(f"/rescore/{graph.item_id}")
    assert res.status_code == 200
    assert res.json() == {"rescored": 1}

    scan = _scan(graph)
    assert scan.verdict == "leans_fake"
    assert float(scan.fake_confidence) == 1.0
    assert scan.auto_reject is False  # stamped at scan time only, never here
    image = _image(graph)
    assert image.suggested_label == "fake"
    assert image.review_state == "suggested"  # entered the queue
    with SessionLocal() as session:  # …but was NOT promoted (rescore never does)
        autos = session.scalars(
            select(VisionReferences).where(VisionReferences.provenance == "auto")
        ).all()
    assert autos == []

    # revoking the fakes swings it back, and clears the queue entry
    _revoke_fakes(graph.item_id)
    client.post(f"/rescore/{graph.item_id}")
    scan = _scan(graph)
    assert scan.verdict == "leans_real"
    image = _image(graph)
    assert image.suggested_label is None
    assert image.review_state == "none"


def test_rescore_needs_no_model(client, graph, add_reference, fake_embedder, fetches, monkeypatch):
    # scoring stored vectors is pure math (D-V8) — it must keep working after
    # the weights go away, unlike /check-images
    add_reference(graph.item_id, "real", vec(0))
    _capture(client, graph, fake_embedder, fetches)

    monkeypatch.setattr(embedder, "_dim", None)  # weights gone mid-flight
    assert client.post(f"/rescore/{graph.item_id}").json() == {"rescored": 1}
    assert (
        client.post(
            "/check-images",
            json={
                "watch_id": graph.watch_id,
                "item_id": graph.item_id,
                "listing_url": LISTING,
                "image_urls": [],
                "llm_authenticity_read": None,
            },
        ).status_code
        == 503
    )
