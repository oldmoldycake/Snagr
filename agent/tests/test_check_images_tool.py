"""The check_images tool: errors come back as strings (never raised, never
blocking — the D-V2 isolation contract), the REJECT directive is explicit,
and the payload matches the sidecar's /check-images contract. The sidecar
itself is faked at the HTTP layer via httpx.MockTransport."""

import asyncio

import httpx
import pytest
import tools

SIDECAR = "http://vision.test"

ARGS = {
    "watch_id": 7,
    "item_id": 3,
    "listing_url": "https://market.test/listing/1",
    "image_urls": ["https://cdn.test/a.jpg", "https://cdn.test/b.jpg"],
    "llm_authenticity_read": "suspect",
}


@pytest.fixture(autouse=True)
def _sidecar_url(monkeypatch):
    monkeypatch.setattr(tools, "VISION_SIDECAR_URL", SIDECAR)


def _install_sidecar(monkeypatch, handler):
    """Route the tool's HTTP through a MockTransport handler."""
    real_client = httpx.AsyncClient

    def _factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


def _respond(payload: dict):
    def handler(request):
        return httpx.Response(200, json=payload)

    return handler


def _report(**overrides):
    payload = {
        "verdict": "inconclusive",
        "fake_confidence": None,
        "auto_reject": False,
        "images": [],
        "skipped": [],
        **overrides,
    }
    return payload


def test_unreachable_sidecar_returns_a_string_not_an_exception(monkeypatch):
    monkeypatch.setattr(tools, "VISION_SIDECAR_URL", "http://127.0.0.1:9")
    result = asyncio.run(tools.check_images(**ARGS))
    assert isinstance(result, str)
    assert result.startswith("No verdict")


def test_timeout_returns_a_string(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("sidecar wedged")

    _install_sidecar(monkeypatch, handler)
    result = asyncio.run(tools.check_images(**ARGS))
    assert result.startswith("No verdict")


def test_degraded_sidecar_503_returns_a_string(monkeypatch):
    def handler(request):
        return httpx.Response(503, json={"detail": "no weights"})

    _install_sidecar(monkeypatch, handler)
    result = asyncio.run(tools.check_images(**ARGS))
    assert result.startswith("No verdict")


def test_payload_matches_the_sidecar_contract(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["json"] = request.read()
        return httpx.Response(200, json=_report())

    _install_sidecar(monkeypatch, handler)
    asyncio.run(tools.check_images(**ARGS))

    import json

    assert seen["url"] == f"{SIDECAR}/check-images"
    assert json.loads(seen["json"]) == ARGS


def test_auto_reject_returns_the_reject_directive(monkeypatch):
    _install_sidecar(
        monkeypatch,
        _respond(_report(verdict="leans_fake", fake_confidence=0.94, auto_reject=True)),
    )
    result = asyncio.run(tools.check_images(**ARGS))
    assert result.startswith("REJECT: fake confidence 0.94")
    assert "log_listing_check" in result
    assert "'authenticity'" in result


def test_leans_fake_below_threshold_reports_the_concern(monkeypatch):
    _install_sidecar(
        monkeypatch,
        _respond(
            _report(
                verdict="leans_fake",
                fake_confidence=0.7,
                images=[
                    {
                        "image_url": "https://cdn.test/a.jpg",
                        "fake_confidence": 0.7,
                        "suggested_label": None,
                    }
                ],
            )
        ),
    )
    result = asyncio.run(tools.check_images(**ARGS))
    assert "leans_fake" in result
    assert "consistent with known fakes" in result
    assert "https://cdn.test/a.jpg: fake confidence 0.7" in result


def test_leans_real_is_framed_as_weak_reassurance(monkeypatch):
    _install_sidecar(monkeypatch, _respond(_report(verdict="leans_real", fake_confidence=0.02)))
    result = asyncio.run(tools.check_images(**ARGS))
    assert "leans_real" in result
    assert "reassurance ONLY" in result
    assert "verified authentic" in result  # the "never say" instruction


def test_skipped_fetches_are_reported(monkeypatch):
    _install_sidecar(monkeypatch, _respond(_report(skipped=["https://cdn.test/b.jpg"])))
    result = asyncio.run(tools.check_images(**ARGS))
    assert "Skipped (could not fetch): https://cdn.test/b.jpg" in result
    assert "rely entirely on" in result  # inconclusive → trust your own screening
