"""Schema semantics of the vision tables (migration 009).

conftest builds the test schema from Base.metadata.create_all and `alembic
check` keeps the models and the migration in agreement, so these tests pin
what both builds must share: threshold defaults land on every user row,
one scan per (watch, listing_url), and the D-V12 row-side cascades — a
watch delete drops that watch's captures, an item delete drops its whole
library. (Byte-side cleanup is the vision sidecar's GC sweep, not the DB.)
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from app.models import VisionListingImages, VisionReferences, VisionScans
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

NOW = datetime.now(UTC)

# any 384-wide vector will do — these tests pin schema, not scoring
EMBEDDING = [0.1] * 384


def _scan(watch, item, url="https://example.test/candidate", **overrides) -> VisionScans:
    fields = {
        "item_id": item.id,
        "watch_id": watch.id,
        "listing_url": url,
        "verdict": "inconclusive",
        "scored_at": NOW,
        **overrides,
    }
    return VisionScans(**fields)


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def test_new_users_get_default_thresholds(sc):
    user = await sc.user()
    await sc.commit()

    assert user.vision_auto_reject_fake == Decimal("0.85")
    assert user.vision_auto_promote_real == Decimal("0.90")
    assert user.vision_auto_promote_fake == Decimal("0.90")


async def test_one_scan_per_watch_and_listing_url(sc):
    item, watch = await sc.tracked()
    sc.db.add(_scan(watch, item))
    await sc.db.flush()

    sc.db.add(_scan(watch, item))
    with pytest.raises(IntegrityError):
        await sc.db.flush()
    await sc.db.rollback()


async def test_watch_delete_drops_captures_and_item_delete_drops_library(sc):
    item, watch = await sc.tracked()
    scan = _scan(watch, item)
    sc.db.add(scan)
    await sc.db.flush()
    sc.db.add(
        VisionListingImages(
            scan_id=scan.id,
            image_url="https://example.test/photo.jpg",
            object_key="a" * 64,
            embedding=EMBEDDING,
            model_name="test-model",
        )
    )
    sc.db.add(
        VisionReferences(
            item_id=item.id,
            label="real",
            provenance="human",
            embedding=EMBEDDING,
            model_name="test-model",
            object_key="b" * 64,
        )
    )
    await sc.commit()

    # a watch delete takes that watch's captures with it — the communal
    # reference library is per-item and must survive (D-V11/D-V12)
    await sc.db.delete(watch)
    await sc.commit()
    assert await _count(sc.db, VisionScans) == 0
    assert await _count(sc.db, VisionListingImages) == 0
    assert await _count(sc.db, VisionReferences) == 1

    # deleting the catalog item deletes its entire library
    await sc.db.delete(item)
    await sc.commit()
    assert await _count(sc.db, VisionReferences) == 0
