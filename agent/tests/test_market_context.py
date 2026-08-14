"""The market-price prompt block: the expected-price override, the per-tier
stats digest, the explicit no-data line, and the scrutinize-don't-reject
framing that must accompany any reference number."""

import asyncio
from datetime import UTC, datetime

from prompt import generate_prompt, market_price_block

AS_OF = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def market(tiers, status="ok", confidence="high"):
    return {
        "currency": "USD",
        "tiers": tiers,
        "confidence": confidence,
        "status": status,
        "as_of": AS_OF,
    }


def tier(median, n, basis="guide", basis_n=None, low=None, high=None):
    return {
        "median": median,
        "mean": median,
        "low": low or median,
        "high": high or median,
        "n": n,
        "sold_n": n,
        "basis": basis,
        "basis_n": n if basis_n is None else basis_n,
    }


class TestMarketPriceBlock:
    def test_expected_price_wins_over_stats_and_is_stated(self):
        block = market_price_block(
            market({"loose": tier("226.00", 9)}), expected_price="150.00", condition_hint=None
        )
        assert "150.00" in block
        assert "expect" in block.lower()
        assert "226.00" not in block

    def test_ok_stats_render_the_per_tier_digest(self):
        block = market_price_block(
            market(
                {"loose": tier("226.00", 9), "cib": tier("700.00", 5, basis="sold")},
                confidence="medium",
            ),
            expected_price=None,
            condition_hint=None,
        )
        assert "loose" in block and "226.00" in block and "9 of 9" in block
        assert "cib" in block and "700.00" in block and "5 of 5" in block
        assert "guide-anchored" in block
        assert "medium confidence" in block
        assert "Aug 13, 2026" in block

    def test_median_says_how_many_prices_it_came_from(self):
        # Measured: one guide value anchored a tier whose other six prices ran
        # from $14, so "median $225.68" beside "n=7" read as seven prices
        # agreeing on $225.68 when only one of them said so.
        block = market_price_block(
            market(
                {"loose": tier("225.68", 7, basis_n=1, low="14.00", high="225.99")},
            ),
            expected_price=None,
            condition_hint=None,
        )
        assert "1 of 7" in block
        assert "$14.00-$225.99" in block

    def test_condition_hint_tier_is_emphasized(self):
        block = market_price_block(
            market({"loose": tier("226.00", 9), "cib": tier("700.00", 5)}),
            expected_price=None,
            condition_hint="cib",
        )
        assert 'watch is for "cib"' in block

    def test_no_market_row_yields_the_explicit_no_data_line(self):
        block = market_price_block(None, expected_price=None, condition_hint=None)
        assert "No market-price data" in block

    def test_insufficient_row_counts_as_no_data(self):
        block = market_price_block(
            market({}, status="insufficient"), expected_price=None, condition_hint=None
        )
        assert "No market-price data" in block

    def test_reference_numbers_carry_the_scrutinize_not_reject_framing(self):
        with_stats = market_price_block(
            market({"loose": tier("226.00", 9)}), expected_price=None, condition_hint=None
        )
        with_expected = market_price_block(None, expected_price="150.00", condition_hint=None)
        for block in (with_stats, with_expected):
            assert "scrutinize" in block
            assert "not by itself a reason to reject" in block


class TestGeneratePromptEmbedsMarketBlock:
    def test_scan_prompt_carries_the_market_context(self):
        prompt = asyncio.run(
            generate_prompt(
                watch_id=1,
                site_id=2,
                site_name="eBay",
                item_id=3,
                item_name="Pokemon Emerald",
                base_url="https://ebay.com",
                criteria=None,
                selection_mode="cheapest",
                max_listings=3,
                allow_reproductions=False,
                market=market({"loose": tier("226.00", 9)}),
                expected_price=None,
                condition_hint=None,
            )
        )
        assert "226.00" in prompt
        assert "MARKET PRICE CONTEXT" in prompt
