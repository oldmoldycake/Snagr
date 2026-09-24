"""The check_images tool: errors come back as strings (never raised, never
blocking: a sidecar outage must never stop a hunt), the REJECT directive is explicit,
and the payload matches the sidecar's /check-images contract. The sidecar
itself is faked at the HTTP layer via httpx.MockTransport."""

import asyncio

import httpx
import pytest
import tools
from conftest import unit_runtime

SIDECAR = "http://vision.test"

# what the orchestrator binds per unit vs. what the model passes
UNIT = {"watch_id": 7, "item_id": 3, "site_id": 2, "site_base_url": "https://market.test"}
ARGS = {
    "listing_url": "https://market.test/listing/1",
    "image_urls": ["https://cdn.test/a.jpg", "https://cdn.test/b.jpg"],
    "llm_authenticity_read": "suspect",
}


def _check(**overrides) -> str:
    return asyncio.run(tools.check_images(**{**ARGS, **overrides}, runtime=unit_runtime(**UNIT)))


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
    result = _check()
    assert isinstance(result, str)
    assert result.startswith("No verdict")


def test_timeout_returns_a_string(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("sidecar wedged")

    _install_sidecar(monkeypatch, handler)
    result = _check()
    assert result.startswith("No verdict")


def test_degraded_sidecar_503_returns_a_string(monkeypatch):
    def handler(request):
        return httpx.Response(503, json={"detail": "no weights"})

    _install_sidecar(monkeypatch, handler)
    result = _check()
    assert result.startswith("No verdict")


def test_payload_matches_the_sidecar_contract(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["json"] = request.read()
        return httpx.Response(200, json=_report())

    _install_sidecar(monkeypatch, handler)
    _check()

    import json

    assert seen["url"] == f"{SIDECAR}/check-images"
    assert json.loads(seen["json"]) == {"watch_id": 7, "item_id": 3, **ARGS}


def test_auto_reject_returns_the_reject_directive(monkeypatch):
    _install_sidecar(
        monkeypatch,
        _respond(_report(verdict="leans_fake", fake_confidence=0.94, auto_reject=True)),
    )
    result = _check()
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
    result = _check()
    assert "leans_fake" in result
    assert "consistent with known fakes" in result
    assert "https://cdn.test/a.jpg: fake confidence 0.7" in result


def test_leans_real_is_framed_as_weak_reassurance(monkeypatch):
    _install_sidecar(monkeypatch, _respond(_report(verdict="leans_real", fake_confidence=0.02)))
    result = _check()
    assert "leans_real" in result
    assert "reassurance ONLY" in result
    assert "verified authentic" in result  # the "never say" instruction


def test_skipped_fetches_are_reported(monkeypatch):
    _install_sidecar(monkeypatch, _respond(_report(skipped=["https://cdn.test/b.jpg"])))
    result = _check()
    assert "Skipped (could not fetch): https://cdn.test/b.jpg" in result
    assert "rely entirely on" in result  # inconclusive → trust your own screening


def _counting_sidecar(monkeypatch) -> list:
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_report())

    _install_sidecar(monkeypatch, handler)
    return calls


def test_an_empty_image_list_is_refused_before_the_sidecar_is_called(monkeypatch):
    calls = _counting_sidecar(monkeypatch)
    result = _check(image_urls=[])
    assert result.startswith("Error:")
    assert "skip check_images" in result
    assert calls == []


@pytest.mark.parametrize(
    "field, value",
    [
        ("listing_url", "market.test/listing/1"),
        ("image_urls", ["ftp://cdn.test/a.jpg"]),
        ("image_urls", ["http://vision:8100/a.jpg"]),
        ("llm_authenticity_read", "definitely_real"),
    ],
)
def test_malformed_arguments_are_refused_before_the_sidecar_is_called(monkeypatch, field, value):
    calls = _counting_sidecar(monkeypatch)
    result = _check(**{field: value})
    assert result.startswith("Error:")
    assert field in result
    assert calls == []


def test_an_off_site_listing_url_is_refused(monkeypatch):
    # the listing page must be on the site this hunt is for
    calls = _counting_sidecar(monkeypatch)
    result = _check(listing_url="https://elsewhere.test/listing/1")

    assert result.startswith("Error: listing_url must be a listing page on this site")
    assert calls == []


def test_photos_on_the_sites_cdn_are_fine(monkeypatch):
    # marketplace images live on a separate domain (i.ebayimg.com,
    # static.mercdn.net), so image URLs get the private-address rule only
    calls = _counting_sidecar(monkeypatch)
    _check(image_urls=["https://cdn.elsewhere.test/a.jpg"])

    assert len(calls) == 1
