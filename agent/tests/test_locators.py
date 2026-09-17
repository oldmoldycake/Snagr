"""Picking and replaying a price locator, against real captured pages.

Every fixture in tests/fixtures/ is genuine PAGE_EXTRACTOR_JS output from a
live marketplace page (see the README there for provenance and redactions),
so what is under test is the behaviour on pages as they are really served —
JSON-LD that states a bid as the price, split price elements, hashed class
names, sixty candidates of which none is ours.

The extractor JS itself runs in a browser and is not exercised here
(decision 15); these tests cover the Python that chooses from its output.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from locators import (
    LOCATOR_KINDS,
    TERMINAL_AVAILABILITY,
    Locator,
    jsonld_availability,
    method_for,
    parse_result,
    read_with,
    reply_text,
    run_locator_js,
    select_locator,
)

FIXTURES = Path(__file__).parent / "fixtures"


def page(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def reply(name: str) -> str:
    return (FIXTURES / f"mcp_reply_{name}.txt").read_text()


class TestSelectLocator:
    """Which place on the page a confirmed price is learned from."""

    @pytest.mark.parametrize(
        "name,price,kind,locator",
        [
            ("ebay_bin", "14390.00", "jsonld", "offers.price"),
            ("ebay_out_of_stock", "8699.00", "jsonld", "offers.price"),
            ("craigslist", "550.00", "jsonld", "offers.price"),
            ("adafruit", "35.00", "jsonld", "offers.price"),
            # offers is a list on this one — the path carries the index
            ("gog", "59.99", "jsonld", "offers[0].price"),
        ],
    )
    def test_structured_data_wins(self, name, price, kind, locator):
        assert select_locator(page(name), Decimal(price)) == Locator(kind, locator)

    def test_the_priority_runs_jsonld_meta_microdata_css(self):
        # adafruit is the one captured page stating its price in all three
        # structured forms; stripping them one at a time walks the ladder
        full = page("adafruit")
        price = Decimal("35.00")

        assert select_locator(full, price) == Locator("jsonld", "offers.price")
        assert select_locator({**full, "jsonld": []}, price) == Locator(
            "meta", "product:price:amount"
        )
        assert select_locator({**full, "jsonld": [], "meta": {}}, price) == Locator(
            "microdata", '[itemprop="price"]'
        )
        assert select_locator(
            {**full, "jsonld": [], "meta": {}, "microdata": []}, price
        ) == Locator("css", '[itemprop="price"]')

    def test_a_visible_element_is_learned_when_no_structured_price_matches(self):
        # Newegg states no price in its JSON-LD, and the element that shows
        # one is assembled from child spans
        assert select_locator(page("newegg"), Decimal("2399.00")) == Locator(
            "css", "div.price-current_2026:nth-of-type(2)"
        )

    def test_a_labelled_element_beats_one_reached_by_counting(self):
        # the page shows 74.50 twice: the real price carries data-testid, the
        # decoy sits in a "similar items" rail behind a :nth-of-type path
        assert select_locator(page("hashed_classes"), Decimal("74.50")) == Locator(
            "css", '[data-testid="price"]'
        )

    def test_no_hashed_class_ever_enters_a_selector(self):
        # every class on that page is emotion/styled-components/JSS shaped;
        # a locator built from one would expire on the site's next deploy
        for candidate in page("hashed_classes")["candidates"]:
            assert not any(
                token in candidate["selector"] for token in ("css-", "sc-", "jss", "_xyz")
            )

    def test_an_auction_teaches_nothing(self):
        # eBay states the CURRENT BID as Offer.price on an auction-only
        # listing: learning it would record a number nobody can pay
        auction = page("ebay_auction")
        assert auction["markers"]["auction"] is True
        assert auction["markers"]["buy_now"] is False
        assert select_locator(auction, Decimal("1925.00")) is None

    def test_a_buy_it_now_price_is_learned_even_beside_a_bid(self):
        # the one exception: a dual-format listing's BIN price is payable
        auction = page("ebay_auction")
        both = {**auction, "markers": {**auction["markers"], "buy_now": True}}

        assert select_locator(both, Decimal("1925.00")) is not None

    @pytest.mark.parametrize("name", ["allbirds", "gone_404"])
    def test_a_page_that_does_not_state_the_price_teaches_nothing(self, name):
        assert select_locator(page(name), Decimal("98.00")) is None

    def test_a_price_the_page_does_not_show_teaches_nothing(self):
        assert select_locator(page("adafruit"), Decimal("36.00")) is None

    def test_the_two_currencies_on_one_page_stay_apart(self):
        # this listing is priced in EUR and shows a USD approximation; each
        # number is learned from where it actually appears
        both = page("ebay_foreign_currency")

        assert select_locator(both, Decimal("15006.05")) == Locator("jsonld", "offers.price")
        visible = select_locator(both, Decimal("12999.00"))
        assert visible is not None and visible.kind == "css"


class TestReadWith:
    """Replaying a locator against a later page load."""

    @pytest.mark.parametrize(
        "name,price",
        [
            ("ebay_bin", "14390.00"),
            ("gog", "59.99"),
            ("adafruit", "35.00"),
            ("newegg", "2399.00"),
            ("hashed_classes", "74.50"),
        ],
    )
    def test_what_was_learned_reads_back(self, name, price):
        from validation import parse_price

        extract = page(name)
        found = select_locator(extract, Decimal(price))

        assert parse_price(read_with(found.kind, found.locator, extract)) == Decimal(price)

    def test_a_locator_that_no_longer_resolves_reads_nothing(self):
        # what bumps listings.locator_failures on a restyled page
        assert read_with("css", "span.gone", page("ebay_bin")) is None
        assert read_with("jsonld", "offers.wasRenamed", page("ebay_bin")) is None
        assert read_with("meta", "product:price:amount", page("ebay_bin")) is None

    def test_an_unknown_kind_reads_nothing(self):
        assert read_with("psychic", "offers.price", page("ebay_bin")) is None

    def test_microdata_prefers_the_content_attribute_over_the_rendered_text(self):
        # Adafruit renders "$35.00" but states content="35.0000"
        assert read_with("microdata", '[itemprop="price"]', page("adafruit")) == "35.0000"


class TestAvailability:
    """Live, empty, or over."""

    @pytest.mark.parametrize(
        "name,expected",
        [("ebay_bin", "instock"), ("ebay_out_of_stock", "outofstock"), ("gone_404", None)],
    )
    def test_the_offer_state_is_read_from_structured_data(self, name, expected):
        assert jsonld_availability(page(name)) == expected

    def test_ebay_calls_a_sold_listing_out_of_stock_too(self):
        # measured, and the reason markers exist: structured data alone
        # cannot tell "seller has none today" from "this listing is over"
        sold, empty = page("ebay_sold"), page("ebay_out_of_stock")

        assert jsonld_availability(sold) == jsonld_availability(empty) == "outofstock"
        assert "outofstock" not in TERMINAL_AVAILABILITY
        assert sold["markers"]["sold"] is True
        assert empty["markers"]["sold"] is False

    def test_a_listing_with_no_stock_is_not_marked_sold_or_ended(self):
        markers = page("ebay_out_of_stock")["markers"]

        assert markers["out_of_stock"] is True
        assert (markers["sold"], markers["ended"]) == (False, False)


class TestRunLocatorJs:
    """The locator is data in the browser, never code."""

    def test_a_locator_is_baked_in_as_a_string_literal(self):
        source = run_locator_js("css", "span.price")

        assert 'const LOCATOR = "span.price";' in source
        assert 'const KIND = "css";' in source

    @pytest.mark.parametrize(
        "hostile",
        [
            '"]) ; alert(1) //',
            "'; fetch('http://evil.test'); '",
            "a\\b",
            "line break",
            'quote"inside',
        ],
    )
    def test_a_hostile_locator_stays_one_string(self, hostile):
        source = run_locator_js("css", hostile)

        # the escaped literal round-trips to exactly what went in, so nothing
        # in it was ever parsed as JavaScript
        literal = source.split("const LOCATOR = ", 1)[1].split(";\n", 1)[0]
        assert json.loads(literal) == hostile

    def test_an_unknown_kind_is_refused_before_anything_is_built(self):
        with pytest.raises(ValueError, match="unknown locator kind"):
            run_locator_js("eval", "span.price")

    @pytest.mark.parametrize("kind", LOCATOR_KINDS)
    def test_every_kind_templates(self, kind):
        assert "__LOCATOR__" not in run_locator_js(kind, "offers.price")


class TestParseResult:
    """The MCP's reply framing, pinned to captured samples."""

    def test_an_object_result_decodes(self):
        assert parse_result(reply("object")) == {
            "price": "74.50",
            "markers": {"auction": False},
        }

    def test_a_string_result_decodes(self):
        assert parse_result(reply("string")) == "Fixture page"

    @pytest.mark.parametrize("name", ["undefined", "null"])
    def test_a_result_that_is_not_a_value_reads_as_nothing(self, name):
        assert parse_result(reply(name)) is None

    def test_a_reply_with_no_result_section_reads_as_nothing(self):
        assert parse_result("### Error\nnavigation failed") is None
        assert parse_result("") is None

    def test_the_echoed_playwright_code_is_not_part_of_the_value(self):
        # the section after the result repeats the whole evaluated function,
        # which is full of braces and quotes
        assert parse_result(reply("object")) == {"price": "74.50", "markers": {"auction": False}}
        assert "Ran Playwright code" in reply("object")


class TestReplyText:
    """Whatever shape the langchain MCP adapter hands back."""

    def test_a_plain_string_passes_through(self):
        assert reply_text("### Result\n1") == "### Result\n1"

    def test_content_blocks_are_joined(self):
        assert reply_text([{"text": "### Result"}, {"text": "1"}]) == "### Result\n1"

    def test_a_content_and_artifact_tuple_reads_its_content(self):
        assert reply_text(([{"text": "### Result\n1"}], {"kind": "image"})) == "### Result\n1"

    def test_objects_with_a_text_attribute_are_read(self):
        class Block:
            text = "### Result\n2"

        assert reply_text([Block()]) == "### Result\n2"


class TestMethodFor:
    def test_a_replayed_element_path_records_as_locator(self):
        assert method_for("css") == "locator"

    @pytest.mark.parametrize("kind", ["jsonld", "meta", "microdata"])
    def test_structured_kinds_record_under_their_own_name(self, kind):
        assert method_for(kind) == kind
