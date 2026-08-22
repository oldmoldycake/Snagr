"""POST /check-images: capture, dedup, scoring, auto-reject, suggestions,
and the auto-promotion guardrails — each one individually blocking."""

import hashlib

from db import SessionLocal, Users, VisionListingImages, VisionReferences, VisionScans
from sqlalchemy import select

from tests.conftest import vec

LISTING = "https://market.test/listing/1"


def _post(client, graph, urls, llm_read="unsure", listing=LISTING):
    return client.post(
        "/check-images",
        json={
            "watch_id": graph.watch_id,
            "item_id": graph.item_id,
            "listing_url": listing,
            "image_urls": urls,
            "llm_authenticity_read": llm_read,
        },
    )


def _rows(model):
    with SessionLocal() as session:
        return session.scalars(select(model)).all()


def _set_thresholds(user_id, **values):
    with SessionLocal() as session:
        user = session.get(Users, user_id)
        for field, value in values.items():
            setattr(user, field, value)
        session.commit()


def test_persists_scan_and_images_without_any_listing_save(
    client, graph, add_reference, fake_embedder, fetches, fake_store
):
    add_reference(graph.item_id, "real", vec(0))
    fetches["https://cdn.test/a.jpg"] = (b"photo-a", "image/jpeg")
    fake_embedder.registry[b"photo-a"] = vec(10)

    res = _post(client, graph, ["https://cdn.test/a.jpg"])
    assert res.status_code == 200
    body = res.json()
    assert body["verdict"] == "leans_real"
    assert body["skipped"] == []

    # persisted regardless of whether the listing itself ever gets saved (D-V2)
    (scan,) = _rows(VisionScans)
    assert (scan.watch_id, scan.listing_url) == (graph.watch_id, LISTING)
    (image,) = _rows(VisionListingImages)
    key = hashlib.sha256(b"photo-a").hexdigest()
    assert image.object_key == key
    assert fake_store.exists(key)


def test_content_hash_dedup_embeds_once(client, graph, fake_embedder, fetches, fake_store):
    fetches["https://cdn.test/a.jpg"] = (b"same-bytes", "image/jpeg")
    fetches["https://cdn.test/b.jpg"] = (b"same-bytes", "image/jpeg")
    fake_embedder.registry[b"same-bytes"] = vec(10)

    res = _post(client, graph, ["https://cdn.test/a.jpg", "https://cdn.test/b.jpg"])
    assert res.status_code == 200
    assert fake_embedder.calls == 1  # same hash in one call embeds once
    assert len(fake_store.objects) == 1

    # …and a later scan of the same pixels reuses the stored vector (D-V8)
    res = _post(client, graph, ["https://cdn.test/a.jpg"], listing="https://market.test/other")
    assert res.status_code == 200
    assert fake_embedder.calls == 1


def test_fetch_failure_skips_that_image_never_the_call(client, graph, fake_embedder, fetches):
    fetches["https://cdn.test/ok.jpg"] = (b"ok", "image/jpeg")
    fake_embedder.registry[b"ok"] = vec(10)

    res = _post(client, graph, ["https://cdn.test/ok.jpg", "https://cdn.test/blocked.jpg"])
    assert res.status_code == 200
    assert res.json()["skipped"] == ["https://cdn.test/blocked.jpg"]
    assert len(_rows(VisionListingImages)) == 1


def test_every_fetch_failing_still_records_an_inconclusive_scan(client, graph, fetches):
    res = _post(client, graph, ["https://cdn.test/blocked.jpg"])
    assert res.status_code == 200
    body = res.json()
    assert body["verdict"] == "inconclusive"
    assert body["fake_confidence"] is None
    assert body["auto_reject"] is False
    assert len(_rows(VisionScans)) == 1


def test_unknown_watch_404s(client, graph):
    res = client.post(
        "/check-images",
        json={
            "watch_id": 99999,
            "item_id": graph.item_id,
            "listing_url": LISTING,
            "image_urls": [],
            "llm_authenticity_read": "unsure",
        },
    )
    assert res.status_code == 404


def test_auto_reject_applies_the_owning_users_threshold(
    client, graph, add_reference, fake_embedder, fetches
):
    add_reference(graph.item_id, "fake", vec(90))
    fetches["https://cdn.test/f.jpg"] = (b"fakeish", "image/jpeg")
    fake_embedder.registry[b"fakeish"] = vec(36.9)  # fake-only conf ≈ 0.667

    res = _post(client, graph, ["https://cdn.test/f.jpg"])
    assert res.json()["verdict"] == "leans_fake"
    assert res.json()["auto_reject"] is False  # 0.667 < default 0.85

    _set_thresholds(graph.user_id, vision_auto_reject_fake="0.60")
    res = _post(client, graph, ["https://cdn.test/f.jpg"], listing="https://market.test/l2")
    assert res.json()["auto_reject"] is True
    scan = next(s for s in _rows(VisionScans) if s.listing_url == "https://market.test/l2")
    assert scan.auto_reject is True


def test_rediscovered_listing_refreshes_in_place(client, graph, fake_embedder, fetches):
    fetches["https://cdn.test/a.jpg"] = (b"first", "image/jpeg")
    fetches["https://cdn.test/b.jpg"] = (b"second", "image/jpeg")
    fake_embedder.registry[b"first"] = vec(10)
    fake_embedder.registry[b"second"] = vec(80)

    _post(client, graph, ["https://cdn.test/a.jpg"])
    (scan,) = _rows(VisionScans)
    first_id = scan.id

    _post(client, graph, ["https://cdn.test/b.jpg"])
    (scan,) = _rows(VisionScans)
    assert scan.id == first_id  # same (watch, listing_url) row, restamped
    (image,) = _rows(VisionListingImages)  # images replaced, not appended
    assert image.object_key == hashlib.sha256(b"second").hexdigest()


def test_variant_tagged_reals_count_toward_the_real_cluster(
    client, graph, add_reference, fake_embedder, fetches
):
    add_reference(graph.item_id, "real", vec(0), variant_tag="alternate art")
    fetches["https://cdn.test/v.jpg"] = (b"variant", "image/jpeg")
    fake_embedder.registry[b"variant"] = vec(10)

    res = _post(client, graph, ["https://cdn.test/v.jpg"])
    assert res.json()["verdict"] == "leans_real"


def test_suggestion_thresholds(client, graph, add_reference, fake_embedder, fetches):
    add_reference(graph.item_id, "real", vec(0))
    add_reference(graph.item_id, "fake", vec(90))
    fetches["https://cdn.test/f.jpg"] = (b"f", "image/jpeg")
    fetches["https://cdn.test/r.jpg"] = (b"r", "image/jpeg")
    fetches["https://cdn.test/m.jpg"] = (b"m", "image/jpeg")
    fake_embedder.registry[b"f"] = vec(80)  # conf 1.0
    fake_embedder.registry[b"r"] = vec(10)  # conf 0.0, s_real ≈ 0.985
    fake_embedder.registry[b"m"] = vec(45)  # conf 0.5

    res = _post(client, graph, [f"https://cdn.test/{n}.jpg" for n in ("f", "r", "m")])
    by_url = {img["image_url"]: img["suggested_label"] for img in res.json()["images"]}
    assert by_url["https://cdn.test/f.jpg"] == "fake"
    assert by_url["https://cdn.test/r.jpg"] == "real"
    assert by_url["https://cdn.test/m.jpg"] is None


def test_weak_reassurance_never_suggests_real(client, graph, add_reference, fake_embedder, fetches):
    # leans_real on margin alone, but s_real < 0.80 — must NOT grow the real
    # cluster (D-V5: weak reassurance)
    add_reference(graph.item_id, "real", vec(0))
    fetches["https://cdn.test/w.jpg"] = (b"weak", "image/jpeg")
    fake_embedder.registry[b"weak"] = vec(40)  # s_real ≈ 0.766

    res = _post(client, graph, ["https://cdn.test/w.jpg"])
    (image,) = res.json()["images"]
    assert res.json()["verdict"] == "leans_real"
    assert image["suggested_label"] is None
    (row,) = _rows(VisionListingImages)
    assert row.review_state == "none"


def _seed_fake_gold(add_reference, item_id, count, provenance="human"):
    for i in range(count):
        add_reference(
            item_id, "fake", vec(90), provenance=provenance, object_key=f"g{provenance}{i}"
        )


def _references(item_id):
    with SessionLocal() as session:
        return session.scalars(
            select(VisionReferences).where(VisionReferences.item_id == item_id)
        ).all()


def test_auto_promotes_only_when_every_guardrail_passes(
    client, graph, add_reference, fake_embedder, fetches
):
    _seed_fake_gold(add_reference, graph.item_id, 3)
    fetches["https://cdn.test/f.jpg"] = (b"very-fake", "image/jpeg")
    fake_embedder.registry[b"very-fake"] = vec(80)  # conf 1.0 ≥ default 0.90

    res = _post(client, graph, ["https://cdn.test/f.jpg"], llm_read="suspect")
    assert res.status_code == 200

    autos = [r for r in _references(graph.item_id) if r.provenance == "auto"]
    (auto,) = autos
    assert auto.label == "fake"
    assert auto.source_listing_url == LISTING
    assert auto.captured_by == graph.user_id
    assert auto.confirmed_by is None
    (image,) = _rows(VisionListingImages)
    assert image.reference_id == auto.id
    assert image.review_state == "confirmed"  # promoted images leave the queue


def test_min_gold_prerequisite_blocks_auto_promotion(
    client, graph, add_reference, fake_embedder, fetches
):
    _seed_fake_gold(add_reference, graph.item_id, 2)  # one short of 3
    fetches["https://cdn.test/f.jpg"] = (b"very-fake", "image/jpeg")
    fake_embedder.registry[b"very-fake"] = vec(80)

    _post(client, graph, ["https://cdn.test/f.jpg"], llm_read="suspect")
    assert all(r.provenance != "auto" for r in _references(graph.item_id))
    (image,) = _rows(VisionListingImages)
    assert image.review_state == "suggested"


def test_auto_references_never_count_toward_min_gold(
    client, graph, add_reference, fake_embedder, fetches
):
    # 2 vouched + 3 machine-promoted: still short — promotions must not
    # bootstrap further promotions (risk 3)
    _seed_fake_gold(add_reference, graph.item_id, 2)
    _seed_fake_gold(add_reference, graph.item_id, 3, provenance="auto")
    fetches["https://cdn.test/f.jpg"] = (b"very-fake", "image/jpeg")
    fake_embedder.registry[b"very-fake"] = vec(80)

    _post(client, graph, ["https://cdn.test/f.jpg"], llm_read="suspect")
    autos = [r for r in _references(graph.item_id) if r.provenance == "auto"]
    assert len(autos) == 3  # only the seeded ones


def test_confidence_threshold_blocks_auto_promotion(
    client, graph, add_reference, fake_embedder, fetches
):
    _seed_fake_gold(add_reference, graph.item_id, 3)
    fetches["https://cdn.test/f.jpg"] = (b"fairly-fake", "image/jpeg")
    fake_embedder.registry[b"fairly-fake"] = vec(40.9)  # conf ≈ 0.85: suggested, < 0.90

    _post(client, graph, ["https://cdn.test/f.jpg"], llm_read="suspect")
    assert all(r.provenance != "auto" for r in _references(graph.item_id))
    (image,) = _rows(VisionListingImages)
    assert image.review_state == "suggested"


def test_llm_corroboration_blocks_auto_promotion(
    client, graph, add_reference, fake_embedder, fetches
):
    _seed_fake_gold(add_reference, graph.item_id, 3)
    fetches["https://cdn.test/f.jpg"] = (b"very-fake", "image/jpeg")
    fake_embedder.registry[b"very-fake"] = vec(80)

    for read in ("unsure", "looks_authentic", None):
        _post(client, graph, ["https://cdn.test/f.jpg"], llm_read=read)
        assert all(r.provenance != "auto" for r in _references(graph.item_id))


def test_real_side_promotion_corroborates_on_looks_authentic(
    client, graph, add_reference, fake_embedder, fetches
):
    for i in range(3):
        add_reference(graph.item_id, "real", vec(0), object_key=f"real{i}")
    fetches["https://cdn.test/r.jpg"] = (b"very-real", "image/jpeg")
    fake_embedder.registry[b"very-real"] = vec(5)  # conf 0 → real confidence 1.0

    _post(client, graph, ["https://cdn.test/r.jpg"], llm_read="looks_authentic")
    autos = [r for r in _references(graph.item_id) if r.provenance == "auto"]
    (auto,) = autos
    assert auto.label == "real"
