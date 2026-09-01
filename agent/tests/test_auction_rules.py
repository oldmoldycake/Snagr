"""Auctions are never recorded — a bid is a clock reading, not a price. The
discovery and re-check prompts carry the ban (Buy It Now is the one stated
exception); the market-grounding extraction prompt deliberately does NOT,
because sold auction results are exactly the comps grounding wants."""

import asyncio

from prompt import (
    generate_price_extraction_prompt,
    generate_prompt,
    generate_recheck_prompt,
)


def _discovery_prompt(**overrides) -> str:
    args = {
        "watch_id": 1,
        "site_id": 2,
        "site_name": "TestBay",
        "item_id": 3,
        "item_name": "Widget",
        "base_url": "https://example.test",
        "criteria": None,
        "selection_mode": "cheapest",
        "max_listings": 3,
        "allow_reproductions": False,
        **overrides,
    }
    return asyncio.run(generate_prompt(**args))


def _recheck_prompt() -> str:
    return asyncio.run(
        generate_recheck_prompt(
            listing_id=7,
            listing_url="https://example.test/listing/7",
            watch_id="1",
            site_id="2",
            site_name="TestBay",
            item_id="3",
            item_name="Widget",
        )
    )


def _extraction_prompt() -> str:
    return asyncio.run(
        generate_price_extraction_prompt(
            item="Widget",
            search_results={"https://example.test/a": "$54.73 New. $29.00 Used"},
            condition_tiers=["loose", "complete"],
        )
    )


def test_discovery_prompt_bans_auctions_with_the_bin_exception():
    prompt = _discovery_prompt()
    assert "AUCTIONS ARE NEVER RECORDED" in prompt
    assert "Buy It Now" in prompt
    assert '"auction"' in prompt
    # Best Offer must be carved back out, or the ban eats real inventory
    assert "Best Offer" in prompt
    assert "Place Bid" in prompt


def test_the_ban_survives_every_discovery_branch():
    # The block is unconditional — not tucked inside a selection_mode,
    # reproduction, or vision branch that can be skipped.
    for overrides in (
        {"selection_mode": "best_match", "criteria": "boxed, working"},
        {"allow_reproductions": True},
        {"vision_enabled": True},
    ):
        assert "AUCTIONS ARE NEVER RECORDED" in _discovery_prompt(**overrides)


def test_recheck_prompt_disables_a_listing_gone_auction_only():
    prompt = _recheck_prompt()
    # the BIN-vanished conversion (standard eBay dual-format behavior)
    assert "a bid is never recorded as a price" in prompt
    assert 'reason "auction"' in prompt
    # the stated exception to the exactly-ONCE save_price_check contract
    assert "Unless the auction rule above applied" in prompt


def test_extraction_prompt_keeps_auction_results_as_comps():
    # Same word, opposite correct answer: grounding WANTS auction results as
    # marketplace evidence; the purchasable-only ban must not leak in here.
    prompt = _extraction_prompt()
    assert "AUCTIONS ARE NEVER RECORDED" not in prompt
    assert "auction results" in prompt
