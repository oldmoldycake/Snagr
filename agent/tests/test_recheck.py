"""The deterministic recheck ladder: reading a tracked listing's price with
no model in the loop.

Driven by the real captured pages in tests/fixtures/, so "the ladder handles
an eBay listing that sold overnight" means the page eBay actually served. The
browser is a fake that hands back one of those payloads per navigation, and
the database seams are recorded rather than written — what is under test is
which rung answered and what it concluded, not SQL (that is
test_run_queue_db.py) and not the notification rules (test_observations.py).

The rule worth keeping in view while reading: every dead end must answer "not
handled" so the LLM gets the page, and the only mistakes that are expensive
are the confident ones — recording a wrong price, or untracking a live
listing.
"""

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import pytest
import recheck
import static
from locators import Locator

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://www.ebay.com/itm/127813671956"
SITE = "https://www.ebay.com"
EBAY_BIN_PRICE = Decimal("14390.00")


def page(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def run(coro):
    return asyncio.run(coro)


def row(**overrides) -> dict:
    """One get_listed_items row for a tracked eBay listing."""
    return {
        "listing_id": 1,
        "listing_url": URL,
        "site_base_url": SITE,
        "price_locator": None,
        "locator_kind": None,
        "locator_failures": 0,
        "static_ok": False,
        "watch_id": 1,
        "user_id": 1,
        "condition_hint": None,
        "site_id": 1,
        "site_name": "Ebay",
        "item_id": 1,
        "item_name": "Widget",
        **overrides,
    }


class FakeBrowser:
    """Hands back a scripted extractor payload per navigation."""

    def __init__(self, extract: dict | None = None, reachable: bool = True):
        self._extract = extract
        self._reachable = reachable
        self.visited: list[str] = []

    async def navigate(self, url: str) -> bool:
        self.visited.append(url)
        return self._reachable

    async def extract(self) -> dict | None:
        return self._extract


@pytest.fixture
def seams(monkeypatch):
    """Record every database and network effect instead of performing one.

    `context` is what get_price_context answers — the listing's believed last
    price and the item's market stats, which is what the bands are measured
    against.
    """
    seen = {
        "recorded": [],
        "disabled": [],
        "woken": [],
        "misses": [],
        "static_cleared": [],
        "consensus": None,
        "context": {"last_price": None, "unconfirmed_price": None, "market": None},
        "static_html": None,
    }

    async def fake_context(listing_id):
        return dict(seen["context"])

    async def fake_consensus(session, site_id):
        return seen["consensus"]

    async def fake_record(session, unit, **kwargs):
        seen["recorded"].append(kwargs)

    async def fake_disable(listing_id, reason):
        seen["disabled"].append((listing_id, reason))
        return True

    async def fake_wake(watch_id):
        seen["woken"].append(watch_id)
        seen["recorded_before_wake"] = len(seen["recorded"])
        return True

    async def fake_miss(listing_id, max_failures):
        seen["misses"].append(listing_id)
        return False

    async def fake_clear(listing_id):
        seen["static_cleared"].append(listing_id)
        return True

    async def fake_fetch(url, base_url):
        return seen["static_html"]

    monkeypatch.setattr(recheck, "get_price_context", fake_context)
    monkeypatch.setattr(recheck, "site_consensus", fake_consensus)
    monkeypatch.setattr(recheck, "record_price_check", fake_record)
    monkeypatch.setattr(recheck, "deactivate_listing", fake_disable)
    monkeypatch.setattr(recheck.job_queue, "wake_hunts", fake_wake)
    monkeypatch.setattr(recheck, "note_locator_failure", fake_miss)
    monkeypatch.setattr(recheck, "clear_static_ok", fake_clear)
    monkeypatch.setattr(static, "fetch", fake_fetch)
    return seen


class TestReading:
    def test_a_listing_with_no_locator_is_read_from_its_structured_data(self, seams):
        # the fallback rung: every schema.org page states offers.price, so a
        # listing that has never been learned is still read without a model
        outcome = run(recheck.recheck_deterministic(FakeBrowser(page("ebay_bin")), row()))

        assert (outcome.handled, outcome.method, outcome.transport) == (
            True,
            "jsonld",
            "browser",
        )
        assert seams["recorded"][0]["price"] == EBAY_BIN_PRICE

    def test_a_learned_locator_is_tried_first(self, seams):
        tracked = row(locator_kind="jsonld", price_locator="offers.price")

        outcome = run(recheck.recheck_deterministic(FakeBrowser(page("ebay_bin")), tracked))

        assert outcome.method == "jsonld"
        assert seams["misses"] == []

    def test_a_replayed_element_path_records_as_locator(self, seams):
        tracked = row(
            listing_url="https://www.example.test/l1",
            site_base_url="https://www.example.test",
            locator_kind="css",
            price_locator='[data-testid="price"]',
        )
        browser = FakeBrowser(page("hashed_classes"))

        outcome = run(recheck.recheck_deterministic(browser, tracked))

        assert outcome.method == "locator"
        assert seams["recorded"][0]["price"] == Decimal("74.50")

    def test_the_sites_consensus_is_tried_before_the_generic_fallbacks(self, seams):
        # one marketplace serves one page template: a listing that has never
        # been learned borrows what its neighbours agree on
        seams["consensus"] = Locator(
            "css", "span.x-price-primary__price:nth-of-type(1) > span.ux-textspans"
        )

        outcome = run(recheck.recheck_deterministic(FakeBrowser(page("ebay_bin")), row()))

        assert outcome.method == "locator"

    def test_the_currency_the_page_states_is_what_is_recorded(self, seams):
        # this listing is priced in EUR with a USD approximation beside it;
        # recording the EUR number as USD would be a silent 15% error
        tracked = row(
            locator_kind="css",
            price_locator="span.x-price-primary__price:nth-of-type(1) > span.ux-textspans",
        )

        run(recheck.recheck_deterministic(FakeBrowser(page("ebay_foreign_currency")), tracked))

        assert seams["recorded"][0]["currency"] == "EUR"
        assert seams["recorded"][0]["notifiable"] is False

    def test_a_listing_with_no_stock_is_recorded_as_such_and_stays_tracked(self, seams):
        # "out of stock" is not "sold": the seller may restock tomorrow, and
        # untracking it would lose the listing and its history
        outcome = run(recheck.recheck_deterministic(FakeBrowser(page("ebay_out_of_stock")), row()))

        assert outcome.handled is True
        assert seams["recorded"][0]["in_stock"] is False
        assert seams["disabled"] == []


class TestAvailability:
    def test_a_sold_listing_is_disabled(self, seams):
        outcome = run(recheck.recheck_deterministic(FakeBrowser(page("ebay_sold")), row()))

        assert seams["disabled"] == [(1, "sold")]
        assert seams["recorded"][0]["status"] == "sold"
        assert outcome.note == "sold"

    def test_a_listing_that_ended_wakes_its_watchs_hunts(self, seams):
        # the slot it held is open again, and a full watch has no hunt
        # waiting to notice — this is the only thing that will
        run(recheck.recheck_deterministic(FakeBrowser(page("ebay_sold")), row()))

        assert seams["woken"] == [row()["watch_id"]]

    def test_the_ending_is_recorded_before_the_hunts_are_woken(self, seams):
        # the wake is best-effort and the observation is not: a wake that
        # failed first would take the sold reading down with it
        run(recheck.recheck_deterministic(FakeBrowser(page("ebay_sold")), row()))

        assert seams["recorded_before_wake"] == 1

    def test_a_sold_page_records_no_price(self, seams):
        # the page still shows what it sold for; recording that as this
        # listing's current price would keep a dead listing on the board
        run(recheck.recheck_deterministic(FakeBrowser(page("ebay_sold")), row()))

        assert seams["recorded"][0]["price"] is None

    def test_an_auction_only_listing_is_disabled_without_a_price(self, seams):
        # eBay states the CURRENT BID as Offer.price; a bid is not payable
        outcome = run(recheck.recheck_deterministic(FakeBrowser(page("ebay_auction")), row()))

        assert seams["disabled"] == [(1, "auction")]
        assert seams["recorded"] == []
        assert outcome.note == "auction"

    def test_a_sold_marker_beside_a_buy_button_is_left_to_the_model(self, seams):
        # a "SOLD" badge in a recommendations rail must never untrack a live
        # listing, so wording alone is not enough when the page can be bought
        live = page("ebay_bin")
        ambiguous = {**live, "markers": {**live["markers"], "sold": True}}

        outcome = run(recheck.recheck_deterministic(FakeBrowser(ambiguous), row()))

        assert seams["disabled"] == []
        assert outcome.handled is True  # it still has a readable price


class TestFallingBackToTheModel:
    def test_an_unreachable_page_is_left_to_the_model(self, seams):
        outcome = run(
            recheck.recheck_deterministic(FakeBrowser(page("ebay_bin"), reachable=False), row())
        )

        assert outcome.handled is False
        assert seams["recorded"] == []

    def test_a_page_the_extractor_cannot_read_is_left_to_the_model(self, seams):
        outcome = run(recheck.recheck_deterministic(FakeBrowser(None), row()))

        assert outcome.handled is False

    def test_a_page_stating_no_price_anywhere_is_left_to_the_model(self, seams):
        outcome = run(recheck.recheck_deterministic(FakeBrowser(page("gone_404")), row()))

        assert outcome.handled is False
        assert seams["disabled"] == []  # ambiguous is not the same as gone

    def test_an_implausible_reading_is_thrown_away_and_the_model_re_reads(self, seams):
        # an anomalous LOCATOR read is never recorded: the LLM reads the same
        # page now and THAT read is the observation (§4.3)
        seams["context"] = {
            "last_price": Decimal("50.00"),
            "unconfirmed_price": None,
            "market": None,
        }

        outcome = run(recheck.recheck_deterministic(FakeBrowser(page("ebay_bin")), row()))

        assert outcome.handled is False
        assert seams["recorded"] == []


class TestLocatorFailures:
    def test_a_locator_that_reads_nothing_is_counted_against_the_listing(self, seams):
        tracked = row(locator_kind="css", price_locator="span.restyled-away")

        run(recheck.recheck_deterministic(FakeBrowser(page("ebay_bin")), tracked))

        assert seams["misses"] == [1]

    def test_a_working_fallback_still_records_the_price(self, seams):
        # the listing's own locator broke, but the page still states a price
        tracked = row(locator_kind="css", price_locator="span.restyled-away")

        outcome = run(recheck.recheck_deterministic(FakeBrowser(page("ebay_bin")), tracked))

        assert outcome.method == "jsonld"
        assert seams["recorded"][0]["price"] == EBAY_BIN_PRICE

    def test_only_the_listings_own_locator_counts_against_it(self, seams):
        # a site-consensus or generic fallback that misses says nothing about
        # this listing, and must not spend its three lives
        seams["consensus"] = Locator("css", "span.also-gone")
        tracked = row(locator_kind="jsonld", price_locator="offers.price")

        run(recheck.recheck_deterministic(FakeBrowser(page("ebay_bin")), tracked))

        assert seams["misses"] == []


class TestStaticRung:
    """The cheapest rung of all: one HTTP GET and no browser."""

    def _static_row(self):
        return row(locator_kind="jsonld", price_locator="offers.price", static_ok=True)

    def _raw(self) -> str:
        return (FIXTURES / "static_jsonld.html").read_text()

    def test_a_listing_proved_static_is_read_without_opening_a_browser(self, seams):
        seams["static_html"] = self._raw()
        browser = FakeBrowser(page("adafruit"))

        outcome = run(
            recheck.recheck_deterministic(
                browser,
                row(
                    listing_url="https://www.adafruit.com/product/3055",
                    site_base_url="https://www.adafruit.com",
                    locator_kind="jsonld",
                    price_locator="offers.price",
                    static_ok=True,
                ),
            )
        )

        assert (outcome.handled, outcome.transport) == (True, "static")
        assert browser.visited == []
        assert seams["recorded"][0]["price"] == Decimal("35.0000")

    def test_a_blocked_fetch_falls_through_to_the_browser(self, seams):
        seams["static_html"] = None
        browser = FakeBrowser(page("ebay_bin"))

        outcome = run(recheck.recheck_deterministic(browser, self._static_row()))

        assert (outcome.handled, outcome.transport) == (True, "browser")
        assert browser.visited == [URL]

    def test_a_browser_read_after_a_static_miss_stops_the_pointless_get(self, seams):
        # the raw page and the rendered page differ for this listing, so the
        # GET is wasted work from here on (decision 14)
        seams["static_html"] = (FIXTURES / "static_neither.html").read_text()

        run(recheck.recheck_deterministic(FakeBrowser(page("ebay_bin")), self._static_row()))

        assert seams["static_cleared"] == [1]

    def test_a_listing_never_proved_static_never_fetches(self, seams):
        seams["static_html"] = self._raw()

        run(recheck.recheck_deterministic(FakeBrowser(page("ebay_bin")), row(static_ok=False)))

        assert seams["recorded"][0]["price"] == EBAY_BIN_PRICE
