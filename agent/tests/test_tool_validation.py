"""Argument validation in the DB tools: a malformed call is answered with an
"Error:" string the model can act on and touches nothing — every case here
is refused before a session is opened, so no database is needed. The
ownership checks that do need rows live in test_run_queue_db.py."""

import asyncio

import pytest
import tools
from conftest import unit_runtime

LISTING_URL = "https://gamebay.test/l1"


def run(coro):
    return asyncio.run(coro)


class TestSavePriceCheck:
    def test_an_unknown_status_is_refused(self):
        result = run(tools.save_price_check(1, True, "unavailable", 10, runtime=unit_runtime()))
        assert result.startswith("Error: status must be one of ok, sold, ended, error")

    @pytest.mark.parametrize("price", [None, 0, -5])
    def test_ok_needs_a_real_price(self, price):
        result = run(tools.save_price_check(1, True, "ok", price, runtime=unit_runtime()))
        assert result.startswith("Error: status 'ok' needs the real price")

    @pytest.mark.parametrize("status", ["sold", "ended", "error"])
    def test_a_price_is_refused_unless_the_listing_is_live(self, status):
        result = run(tools.save_price_check(1, False, status, 10, runtime=unit_runtime()))
        assert result.startswith(f"Error: omit price when status is {status!r}")

    def test_currency_must_be_a_three_letter_code(self):
        result = run(tools.save_price_check(1, True, "ok", 10, "dollars", runtime=unit_runtime()))
        assert result.startswith("Error: currency must be a three-letter code")


class TestSaveListing:
    @pytest.mark.parametrize("url", ["gamebay.test/l1", "ftp://gamebay.test/l1", ""])
    def test_url_must_be_http(self, url):
        result = run(tools.save_listing(url, "title", 80, "fits", runtime=unit_runtime()))
        assert result.startswith("Error: url must be")

    @pytest.mark.parametrize("score", [-1, 101])
    def test_match_score_stays_within_0_100(self, score):
        result = run(
            tools.save_listing(LISTING_URL, "title", score, "fits", runtime=unit_runtime())
        )
        assert result.startswith("Error: match_score must be")


class TestLogListingCheck:
    def test_url_must_be_http(self):
        result = run(tools.log_listing_check("gamebay.test/l1", "poor_fit", runtime=unit_runtime()))
        assert result.startswith("Error: url must be")

    def test_reason_must_not_be_blank(self):
        result = run(tools.log_listing_check(LISTING_URL, "  ", runtime=unit_runtime()))
        assert result.startswith("Error: reason must")


class TestDisableListing:
    def test_reason_must_not_be_blank(self):
        result = run(tools.disable_listing(1, "", runtime=unit_runtime()))
        assert result.startswith("Error: reason must")
