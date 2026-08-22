"""The daily GC (D-V12): retention prune on rows, reconciliation on bytes —
driven directly against the session and the storage stub."""

from datetime import UTC, datetime, timedelta

from db import SessionLocal, VisionListingImages, VisionReferences, VisionScans
from sqlalchemy import select
from sweep import prune_stale_captures, reconcile_bucket

from tests.conftest import FakeStorage, vec

NOW = datetime.now(UTC)
OLD = NOW - timedelta(days=120)  # past the 90-day retention window


def _scan(session, graph, url):
    scan = VisionScans(
        item_id=graph.item_id,
        watch_id=graph.watch_id,
        listing_url=url,
        verdict="inconclusive",
        scored_at=OLD,
    )
    session.add(scan)
    session.flush()
    return scan


def _image(session, scan, key, review_state="none", created_at=OLD):
    session.add(
        VisionListingImages(
            scan_id=scan.id,
            image_url=f"https://cdn.test/{key}.jpg",
            object_key=key,
            embedding=vec(0),
            model_name="test-model",
            review_state=review_state,
            created_at=created_at,
        )
    )


def test_retention_prunes_unreviewed_captures_and_empty_scans(graph):
    with SessionLocal() as session:
        keep = _scan(session, graph, "https://market.test/keep")
        _image(session, keep, "stale-none")
        _image(session, keep, "stale-suggested", review_state="suggested")
        _image(session, keep, "old-confirmed", review_state="confirmed")
        _image(session, keep, "fresh-none", created_at=NOW)
        drop = _scan(session, graph, "https://market.test/drop")
        _image(session, drop, "drop-only-image")
        session.commit()

        assert prune_stale_captures(session, now=NOW) == 3

    with SessionLocal() as session:
        remaining = {i.object_key for i in session.scalars(select(VisionListingImages))}
        # confirmed rows are library provenance and never age out; fresh rows wait
        assert remaining == {"old-confirmed", "fresh-none"}
        scans = {s.listing_url for s in session.scalars(select(VisionScans))}
        assert scans == {"https://market.test/keep"}  # imageless scan went too


def test_reconcile_deletes_only_unreferenced_objects(graph):
    store = FakeStorage()
    store.put("ref-key", b"r", "image/jpeg")
    store.put("img-key", b"i", "image/jpeg")
    store.put("orphan-key", b"o", "image/jpeg")
    with SessionLocal() as session:
        session.add(
            VisionReferences(
                item_id=graph.item_id,
                label="real",
                provenance="human",
                embedding=vec(0),
                model_name="test-model",
                object_key="ref-key",
            )
        )
        scan = _scan(session, graph, "https://market.test/l")
        _image(session, scan, "img-key")
        session.commit()

        assert reconcile_bucket(session, store) == 1

    assert store.exists("ref-key")
    assert store.exists("img-key")
    assert not store.exists("orphan-key")
