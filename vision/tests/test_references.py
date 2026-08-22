"""POST /references: manual uploads become communal gold immediately,
provenance 'upload' (D-V7)."""

import hashlib
from io import BytesIO

from db import SessionLocal, VisionReferences
from PIL import Image
from sqlalchemy import select

from tests.conftest import vec


def _png() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _upload(client, graph, data: bytes, label="real", variant_tag=None):
    form = {"item_id": str(graph.item_id), "label": label, "user_id": str(graph.user_id)}
    if variant_tag is not None:
        form["variant_tag"] = variant_tag
    return client.post("/references", files={"file": ("unit.png", data, "image/png")}, data=form)


def test_upload_becomes_gold_immediately(client, graph, fake_embedder, fake_store):
    data = _png()
    fake_embedder.registry[data] = vec(0)

    res = _upload(client, graph, data, variant_tag="alternate art")
    assert res.status_code == 201
    body = res.json()
    key = hashlib.sha256(data).hexdigest()
    assert body["provenance"] == "upload"
    assert body["label"] == "real"
    assert body["variant_tag"] == "alternate art"
    assert body["object_key"] == key

    with SessionLocal() as session:
        reference = session.execute(select(VisionReferences)).scalar_one()
    assert reference.confirmed_by == graph.user_id  # the uploader vouched
    assert reference.source_listing_url is None
    assert fake_store.exists(key)


def test_bad_label_422s(client, graph, fake_embedder):
    data = _png()
    fake_embedder.registry[data] = vec(0)
    assert _upload(client, graph, data, label="genuine").status_code == 422


def test_non_image_file_422s(client, graph):
    res = _upload(client, graph, b"<html>definitely not a photo</html>")
    assert res.status_code == 422
