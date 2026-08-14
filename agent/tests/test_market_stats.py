"""Guide-anchored per-tier stats and the market_prices payload built from
them. The core rule under test: when a guide has spoken for a tier, a pile of
asking prices never outvotes it by weight of numbers."""

from decimal import Decimal

from pricing import (
    MIN_TIER_SAMPLE,
    Observation,
    build_market_price,
    flag_outliers,
    tier_stats,
)


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


class TestUnknownTierIsNotAPrice:
    """Extraction parks a price whose condition the source never stated in
    "unknown" - a quarantine bucket, not a tier of the category. It must never
    be published as one, and must never vote on confidence."""

    def test_unknown_tier_is_never_reported(self):
        observations = [
            obs("226", origin="guide", source_type="price_guide"),
            obs("30", tier="unknown", sold_or_asking="sold"),
            obs("32", tier="unknown", sold_or_asking="sold"),
            obs("34", tier="unknown", sold_or_asking="sold"),
        ]
        payload = build_market_price(tier_stats(observations), observations)
        assert "unknown" not in payload["tiers"]
        assert payload["tiers"]["loose"]["median"] == "226.00"

    def test_pool_of_only_unknown_observations_is_insufficient(self):
        # The Mini PC case: plenty of prices, none of them attributable to a
        # condition, so there is nothing this item can honestly be said to cost.
        observations = [
            obs("100", tier="unknown", sold_or_asking="sold"),
            obs("120", tier="unknown", sold_or_asking="sold"),
            obs("140", tier="unknown", sold_or_asking="sold"),
        ]
        payload = build_market_price(tier_stats(observations), observations)
        assert payload["status"] == "insufficient"
        assert payload["tiers"] == {}

    def test_unknown_observations_stay_in_the_audit_trail(self):
        observations = [
            obs("226", origin="guide", source_type="price_guide"),
            obs("30", tier="unknown", sold_or_asking="sold"),
            obs("32", tier="unknown", sold_or_asking="sold"),
            obs("34", tier="unknown", sold_or_asking="sold"),
        ]
        payload = build_market_price(tier_stats(observations), observations)
        assert "unknown" not in payload["tiers"]
        assert [o["price"] for o in payload["observations"]] == ["226", "30", "32", "34"]
        assert {o["tier"] for o in payload["observations"]} == {"loose", "unknown"}

    def test_unknown_guide_bucket_does_not_anchor_confidence(self):
        # A guide page priced something without saying what condition it was in.
        # That cannot vouch for the tiers that ARE reportable.
        observations = [
            obs("30", sold_or_asking="sold"),
            obs("32", sold_or_asking="sold"),
            obs("34", sold_or_asking="sold"),
            obs("500", tier="unknown", origin="guide", source_type="price_guide"),
        ]
        payload = build_market_price(tier_stats(observations), observations)
        assert payload["tiers"]["loose"]["basis"] == "sold"
        assert payload["confidence"] == "medium"
        assert payload["confidence_reasons"] == ["no_guide_anchor"]


class TestImplausiblePricesAreQuarantined:
    """Extraction reads prices out of prose, and a dropped decimal point turns
    $44.99 into $4499 without changing anything else about the observation. A
    price that far above its own tier is not a price anyone paid, so it is
    quarantined the same way "unknown" is: out of the stats, still in the
    audit trail."""

    def test_extreme_high_price_is_excluded_from_its_tier(self):
        # Measured: one retailer page yielded both $44.99 and $4499 for the
        # same DS cartridge, and the bad one set the published range.
        observations = flag_outliers([obs("27.68"), obs("44.99"), obs("79.95"), obs("4499")])
        stats = tier_stats(observations)["loose"]
        assert stats["n"] == 3
        assert stats["high"] == Decimal("79.95")
        assert stats["median"] == Decimal("44.99")

    def test_quarantined_price_stays_in_the_audit_trail_with_its_reason(self):
        observations = flag_outliers([obs("27.68"), obs("44.99"), obs("79.95"), obs("4499")])
        payload = build_market_price(tier_stats(observations), observations)
        recorded = {o["price"]: o["excluded"] for o in payload["observations"]}
        assert recorded == {
            "27.68": None,
            "44.99": None,
            "79.95": None,
            "4499": "outlier",
        }

    def test_a_price_far_below_its_tier_is_kept(self):
        # A cheap copy is the deal we exist to find; only the high side carries
        # the dropped-decimal signature.
        observations = flag_outliers([obs("14.00"), obs("213.33"), obs("222.22"), obs("225.99")])
        stats = tier_stats(observations)["loose"]
        assert stats["n"] == 4
        assert stats["low"] == Decimal("14.00")

    def test_tier_too_small_to_have_a_median_is_not_judged(self):
        # Two prices cannot say which of them is the anomaly.
        observations = flag_outliers([obs("50"), obs("5000")])
        stats = tier_stats(observations)["loose"]
        assert stats["n"] == 2
        assert stats["high"] == Decimal("5000")

    def test_a_price_is_rejudged_against_the_pool_it_is_in(self):
        # The guide pass judges its own observations, then the snippet fallback
        # adds more and the whole pool is judged again. A price the smaller pool
        # called extreme must be able to come back when the median catches up.
        guide_only = flag_outliers([obs("10"), obs("12"), obs("400")])
        assert [o.excluded for o in guide_only] == [None, None, "outlier"]

        rejudged = flag_outliers(guide_only + [obs("380"), obs("390"), obs("410")])
        assert [o.excluded for o in rejudged] == [None] * 6

    def test_quarantined_price_does_not_vote_on_confidence(self):
        # The outlier is the only sold price in the pool; once it is out, the
        # remaining prices are all asking and confidence must say so.
        observations = flag_outliers(
            [obs("100"), obs("110"), obs("120"), obs("5000", sold_or_asking="sold")]
        )
        payload = build_market_price(tier_stats(observations), observations)
        assert payload["confidence_reasons"] == ["no_guide_anchor", "all_asking"]
        assert payload["confidence"] == "low"


class TestBasisCountIsPublished:
    """median and low/high are drawn from different populations - the median
    from whichever basis won, the range from every price in the tier. Without
    a count for the basis, a median built from one guide value reads as though
    the whole pool agreed on it."""

    def test_basis_n_counts_only_the_prices_behind_the_median(self):
        observations = [
            obs("226", origin="guide", source_type="price_guide"),
            obs("14.00"),
            obs("54.99"),
            obs("182.50"),
            obs("213.33"),
            obs("222.22"),
            obs("225.99"),
        ]
        stats = tier_stats(observations)["loose"]
        assert stats["basis"] == "guide"
        assert stats["basis_n"] == 1
        assert stats["n"] == 7

    def test_basis_n_reaches_the_published_payload(self):
        observations = [
            obs("226", origin="guide", source_type="price_guide"),
            obs("500"),
            obs("600"),
        ]
        payload = build_market_price(tier_stats(observations), observations)
        assert payload["tiers"]["loose"]["basis_n"] == 1
        assert payload["tiers"]["loose"]["n"] == 3
