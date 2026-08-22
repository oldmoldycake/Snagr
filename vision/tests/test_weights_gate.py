"""The D-V1 weights gate: absent gated weights degrade the service loudly —
health says so, scoring endpoints answer with the license/token
instructions, and everything that needs no model keeps working."""

import embedder
import pytest
from app import app
from fastapi.testclient import TestClient


def test_health_reports_degraded(degraded_client):
    body = degraded_client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["weights_present"] is False
    assert body["dim"] is None


def test_health_reports_ok_when_loaded(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["dim"] == 384
    assert body["weights_present"] is True


def test_check_images_refuses_with_instructions(degraded_client):
    res = degraded_client.post(
        "/check-images",
        json={
            "watch_id": 1,
            "item_id": 1,
            "listing_url": "https://market.test/l",
            "image_urls": [],
            "llm_authenticity_read": "unsure",
        },
    )
    assert res.status_code == 503
    detail = res.json()["detail"]
    assert "HF_TOKEN" in detail
    assert "huggingface.co" in detail


def test_reference_upload_refuses_with_instructions(degraded_client):
    res = degraded_client.post(
        "/references",
        files={"file": ("photo.png", b"not-really-a-png", "image/png")},
        data={"item_id": "1", "label": "real", "user_id": "1"},
    )
    assert res.status_code == 503
    assert "HF_TOKEN" in res.json()["detail"]


def test_stored_images_still_served_while_degraded(degraded_client, fake_store):
    fake_store.put("abc123", b"jpeg-bytes", "image/jpeg")
    res = degraded_client.get("/images/abc123")
    assert res.status_code == 200
    assert res.content == b"jpeg-bytes"
    assert res.headers["content-type"].startswith("image/jpeg")

    assert degraded_client.get("/images/missing").status_code == 404


def test_dim_mismatch_refuses_to_start(fake_store, monkeypatch):
    # a wrong-width model must never write into vector(384) columns
    monkeypatch.setattr(embedder, "load", lambda: 768)
    with pytest.raises(RuntimeError, match="vector\\(384\\)"), TestClient(app):
        pass
