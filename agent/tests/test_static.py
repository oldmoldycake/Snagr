"""The browserless rung: one GET, one locator, nothing inferred.

The HTML fixtures are the structured-data half of the real captures in
tests/fixtures/ (see its README), wrapped in a minimal document — which is
the honest shape for this module, because the raw HTML is precisely where the
rendered DOM is missing.

Nothing here reaches the network: httpx.AsyncClient is replaced by a
transport that answers from a script, so every status code, redirect and
timeout under test is exact.
"""

import asyncio
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import static
from locators import Locator
from static import extract, fetch, probe, read

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://www.adafruit.com/product/3055"
SITE = "https://www.adafruit.com"
JSONLD = Locator("jsonld", "offers.price")
META = Locator("meta", "product:price:amount")


def html(name: str) -> str:
    return (FIXTURES / f"static_{name}.html").read_text()


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def served(monkeypatch):
    """Answer every GET from a script, and record what was requested.

    Returns the state dict: set `served["response"]` to the response (or the
    exception) the next fetch should see, and read `served["requests"]` and
    `served["kwargs"]` back.
    """
    state = {"response": httpx.Response(200, text=html("jsonld")), "requests": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        response = state["response"]
        if isinstance(response, Exception):
            raise response
        return response

    original = httpx.AsyncClient

    def client(**kwargs):
        state["kwargs"] = kwargs
        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(static.httpx, "AsyncClient", client)
    return state


class TestExtract:
    def test_json_ld_blocks_and_meta_tags_are_found(self):
        found = extract(html("jsonld"))

        assert len(found["jsonld"]) == 2
        assert found["meta"]["product:price:amount"] == "35.00"

    def test_a_page_with_only_meta_tags_yields_only_those(self):
        found = extract(html("meta_only"))

        assert found["jsonld"] == []
        assert found["meta"]["product:price:amount"] == "35.00"

    def test_a_page_stating_nothing_yields_nothing(self):
        assert extract(html("neither")) == {"jsonld": [], "meta": {}}

    def test_a_challenge_page_states_no_price(self):
        found = extract(html("challenge"))

        assert found["jsonld"] == []
        assert "product:price:amount" not in found["meta"]

    def test_malformed_markup_still_yields_the_good_block(self):
        # one unparseable JSON-LD block and an unclosed tag do not cost the
        # block beside them; read_with skips what will not parse
        found = extract(html("malformed"))

        assert len(found["jsonld"]) == 2
        assert found["meta"]["product:price:amount"] == "550.00"

    def test_a_script_that_is_not_json_ld_is_not_collected(self):
        page = '<script>var price = "9.99";</script><script type="application/ld+json">{}</script>'

        assert extract(page)["jsonld"] == ["{}"]

    def test_the_first_meta_wins(self):
        page = (
            '<meta property="og:price:amount" content="10">'
            '<meta property="og:price:amount" content="99">'
        )

        assert extract(page)["meta"]["og:price:amount"] == "10"


class TestFetch:
    def test_a_plain_200_is_returned(self, served):
        assert "Raspberry Pi" in run(fetch(URL, SITE))

    def test_the_request_looks_like_a_browser(self, served):
        run(fetch(URL, SITE))

        (request,) = served["requests"]
        assert "Mozilla/5.0" in request.headers["user-agent"]
        assert request.headers["accept-language"].startswith("en-US")

    def test_redirects_are_never_followed(self, served):
        # a listing that moved is a change in availability, and only the
        # browser gets to decide that (decision 14)
        run(fetch(URL, SITE))

        assert served["kwargs"]["follow_redirects"] is False

    @pytest.mark.parametrize("status", [301, 302, 403, 404, 410, 429, 500])
    def test_anything_but_200_falls_through(self, served, status):
        served["response"] = httpx.Response(status, text="<html></html>")

        assert run(fetch(URL, SITE)) is None

    def test_a_transport_failure_falls_through(self, served):
        served["response"] = httpx.ConnectTimeout("timed out")

        assert run(fetch(URL, SITE)) is None

    def test_an_enormous_body_falls_through(self, served, monkeypatch):
        monkeypatch.setattr(static, "MAX_BYTES", 100)
        served["response"] = httpx.Response(200, text="x" * 500)

        assert run(fetch(URL, SITE)) is None

    @pytest.mark.parametrize(
        "url",
        ["http://vision:8100/rescore", "http://127.0.0.1:8000/", "https://evil.test/p/1"],
    )
    def test_a_guarded_url_is_refused_before_any_request_is_made(self, served, url):
        # S2 applies to this GET exactly as it does to a navigation
        assert run(fetch(url, SITE)) is None
        assert served["requests"] == []


class TestRead:
    def test_a_json_ld_locator_reads_the_raw_html(self, served):
        assert run(read(URL, SITE, JSONLD)) == "35.0000"

    def test_a_meta_locator_reads_the_raw_html(self, served):
        served["response"] = httpx.Response(200, text=html("meta_only"))

        assert run(read(URL, SITE, META)) == "35.00"

    @pytest.mark.parametrize("name", ["neither", "challenge"])
    def test_a_page_stating_nothing_reads_nothing(self, served, name):
        served["response"] = httpx.Response(200, text=html(name))

        assert run(read(URL, SITE, JSONLD)) is None

    @pytest.mark.parametrize("kind,locator", [("css", "span.price"), ("microdata", "[itemprop]")])
    def test_an_element_path_is_never_replayed_here(self, served, kind, locator):
        # Python has no DOM; guessing one out of raw HTML is how the wrong
        # number gets recorded
        assert run(read(URL, SITE, Locator(kind, locator))) is None
        assert served["requests"] == []

    def test_static_fetch_off_skips_the_rung_entirely(self, served, monkeypatch):
        monkeypatch.setattr(static, "STATIC_FETCH", False)

        assert run(read(URL, SITE, JSONLD)) is None
        assert served["requests"] == []


class TestProbe:
    def test_an_exact_match_earns_the_browserless_recheck(self, served):
        assert run(probe(URL, SITE, JSONLD, Decimal("35.00"))) is True

    def test_a_different_number_in_the_raw_html_keeps_the_browser(self, served):
        # the rendered page is the truth when the two disagree
        assert run(probe(URL, SITE, JSONLD, Decimal("29.99"))) is False

    def test_a_page_that_states_no_price_keeps_the_browser(self, served):
        served["response"] = httpx.Response(200, text=html("neither"))

        assert run(probe(URL, SITE, JSONLD, Decimal("35.00"))) is False

    def test_a_blocked_fetch_keeps_the_browser(self, served):
        served["response"] = httpx.Response(403, text="denied")

        assert run(probe(URL, SITE, JSONLD, Decimal("35.00"))) is False

    def test_an_element_path_is_never_probed(self, served):
        assert run(probe(URL, SITE, Locator("css", "span.price"), Decimal("35.00"))) is False
