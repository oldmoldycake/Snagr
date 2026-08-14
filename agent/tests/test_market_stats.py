"""Guide-anchored per-tier stats and the market_prices payload built from
them. The core rule under test: when a guide has spoken for a tier, a pile of
asking prices never outvotes it by weight of numbers."""

from decimal import Decimal

from pricing import MIN_TIER_SAMPLE, Observation, build_market_price, tier_stats


def obs(price, tier="loose", sold_or_asking="asking", origin="search", source_type="other"):
    return Observation(
        price=Decimal(price),
        tier=tier,
        condition_raw=None,
        sold_or_asking=sold_or_asking,
        source_url="https://example.com/x",
        source_type=source_type,
        origin=origin,
    )


class TestGuideAnchoredTierStats:
    def test_guide_observation_anchors_the_median(self):
        observations = [
            obs("226", origin="guide", source_type="price_guide", sold_or_asking="sold"),
            obs("500"),
            obs("600"),
            obs("700"),
        ]
        stats = tier_stats(observations)["loose"]
        assert stats["median"] == Decimal("226.00")
        assert stats["basis"] == "guide"
        assert stats["n"] == 4
        assert (stats["low"], stats["high"]) == (Decimal("226"), Decimal("700"))

    def test_marketplace_price_on_a_guide_page_does_not_anchor_the_tier(self):
        # PriceCharting's own aggregated figure sits right next to a single
        # live eBay "compare prices" listing on the same page - both fetched
        # with origin="guide", but only one is actually a guide statistic.
        observations = [
            obs("1061.00", origin="guide", source_type="price_guide"),
            obs("101.24", origin="guide", source_type="marketplace"),
            obs("54.99", origin="guide", source_type="retailer"),
        ]
        stats = tier_stats(observations)["loose"]
        assert stats["basis"] == "guide"
        assert stats["median"] == Decimal("1061.00")

    def test_sold_prices_beat_asking_without_a_guide(self):
        observations = [
            obs("100", sold_or_asking="sold"),
            obs("110", sold_or_asking="sold"),
            obs("120", sold_or_asking="sold"),
            obs("500"),
            obs("700"),
        ]
        stats = tier_stats(observations)["loose"]
        assert stats["basis"] == "sold"
        assert stats["median"] == Decimal("110.00")

    def test_thin_sold_sample_falls_back_to_all_prices(self):
        observations = [obs("100", sold_or_asking="sold"), obs("300"), obs("500")]
        stats = tier_stats(observations)["loose"]
        assert stats["basis"] == "all"
        assert stats["median"] == Decimal("300.00")


class TestBuildMarketPrice:
    def test_single_guide_value_is_reportable_and_high_confidence(self):
        observations = [
            obs("226", origin="guide", source_type="price_guide", sold_or_asking="sold")
        ]
        payload = build_market_price(tier_stats(observations), observations)
        assert payload["status"] == "ok"
        assert payload["tiers"]["loose"]["median"] == "226.00"
        assert payload["tiers"]["loose"]["basis"] == "guide"
        assert payload["confidence"] == "high"
        assert payload["confidence_reasons"] == []

    def test_thin_snippet_only_tier_is_insufficient(self):
        observations = [obs("100"), obs("120")]
        assert len(observations) < MIN_TIER_SAMPLE
        payload = build_market_price(tier_stats(observations), observations)
        assert payload["status"] == "insufficient"
        assert payload["tiers"] == {}

    def test_snippet_tier_at_min_sample_is_ok_but_not_high(self):
        observations = [
            obs("100", sold_or_asking="sold"),
            obs("110", sold_or_asking="sold"),
            obs("120", sold_or_asking="sold"),
        ]
        payload = build_market_price(tier_stats(observations), observations)
        assert payload["status"] == "ok"
        assert payload["confidence"] == "medium"
        assert payload["confidence_reasons"] == ["no_guide_anchor"]

    def test_below_min_total_sample_is_low_confidence(self):
        observations = [obs("100", tier="cib"), obs("120", tier="cib")]
        payload = build_market_price(tier_stats(observations), observations)
        assert payload["confidence"] == "low"
        assert "n=2" in payload["confidence_reasons"]

    def test_all_asking_pool_demotes_once_more(self):
        observations = [obs("100"), obs("110"), obs("120"), obs("130"), obs("140")]
        payload = build_market_price(tier_stats(observations), observations)
        assert payload["confidence"] == "low"
        assert payload["confidence_reasons"] == ["no_guide_anchor", "all_asking"]

    def test_payload_is_json_ready_decimal_strings(self):
        observations = [
            obs("1234.5", origin="guide", source_type="price_guide"),
            obs("99", tier="cib"),
        ]
        payload = build_market_price(tier_stats(observations), observations)
        tier = payload["tiers"]["loose"]
        assert {tier["median"], tier["mean"], tier["low"], tier["high"]} == {"1234.50"}
        assert tier["n"] == 1
        recorded = payload["observations"]
        assert {o["price"] for o in recorded} == {"1234.5", "99"}
        assert {o["origin"] for o in recorded} == {"guide", "search"}
