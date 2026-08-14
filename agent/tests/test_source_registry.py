"""Registry lifecycle: which domains a grounding fetches, and how evidence
promotes, demotes, and rotates them. Pure functions — the LLM proposes
domains elsewhere, but trust only ever moves here, in code."""

from pricing import (
    CANDIDATE_DEAD_MISSES,
    DEAD_CONSECUTIVE_MISSES,
    PROMOTE_MIN_TIERED_OBS,
    record_source_result,
    source_fetch_plan,
)


def entry(domain, status="candidate", hits=0, consecutive_misses=0):
    return {
        "domain": domain,
        "kind": "price_guide",
        "status": status,
        "hits": hits,
        "consecutive_misses": consecutive_misses,
        "notes": None,
    }


class TestSourceFetchPlan:
    def test_pinned_come_first_then_trusted(self):
        registry = [entry("guide.com", status="trusted"), entry("other.com", status="trusted")]
        fetch, candidate = source_fetch_plan(registry, ["pinned.com"])
        assert fetch == ["pinned.com", "guide.com", "other.com"]
        assert candidate is None

    def test_first_candidate_returned_separately_dead_skipped(self):
        registry = [
            entry("dead.com", status="dead"),
            entry("cand-a.com"),
            entry("cand-b.com"),
            entry("guide.com", status="trusted"),
        ]
        fetch, candidate = source_fetch_plan(registry, None)
        assert fetch == ["guide.com"]
        assert candidate == "cand-a.com"

    def test_pinned_domain_not_duplicated_from_registry(self):
        registry = [entry("guide.com", status="trusted")]
        fetch, candidate = source_fetch_plan(registry, ["guide.com"])
        assert fetch == ["guide.com"]
        assert candidate is None

    def test_no_registry_and_no_pins(self):
        assert source_fetch_plan(None, None) == ([], None)


class TestRecordSourceResult:
    def test_qualifying_parse_promotes_candidate(self):
        registry = [entry("cand.com", consecutive_misses=2)]
        updated = record_source_result(registry, None, "cand.com", PROMOTE_MIN_TIERED_OBS)
        assert updated[0]["status"] == "trusted"
        assert updated[0]["hits"] == 1
        assert updated[0]["consecutive_misses"] == 0

    def test_parse_below_promote_bar_is_a_miss(self):
        registry = [entry("guide.com", status="trusted", hits=4)]
        updated = record_source_result(registry, None, "guide.com", PROMOTE_MIN_TIERED_OBS - 1)
        assert updated[0]["status"] == "trusted"
        assert updated[0]["hits"] == 4
        assert updated[0]["consecutive_misses"] == 1

    def test_hit_resets_consecutive_misses(self):
        registry = [entry("guide.com", status="trusted", hits=1, consecutive_misses=3)]
        updated = record_source_result(registry, None, "guide.com", 5)
        assert updated[0]["consecutive_misses"] == 0
        assert updated[0]["hits"] == 2

    def test_candidate_with_no_hits_dies_quickly(self):
        registry = [entry("cand.com", consecutive_misses=CANDIDATE_DEAD_MISSES - 1)]
        updated = record_source_result(registry, None, "cand.com", 0)
        assert updated[0]["status"] == "dead"

    def test_any_domain_dies_at_consecutive_miss_limit(self):
        registry = [
            entry(
                "guide.com",
                status="trusted",
                hits=7,
                consecutive_misses=DEAD_CONSECUTIVE_MISSES - 1,
            )
        ]
        updated = record_source_result(registry, None, "guide.com", 0)
        assert updated[0]["status"] == "dead"

    def test_surviving_candidate_rotates_to_the_end(self):
        registry = [entry("cand-a.com"), entry("cand-b.com"), entry("guide.com", status="trusted")]
        updated = record_source_result(registry, None, "cand-a.com", 0)
        assert [e["domain"] for e in updated] == ["cand-b.com", "guide.com", "cand-a.com"]
        assert updated[-1]["consecutive_misses"] == 1

    def test_pinned_domains_are_exempt(self):
        registry = [entry("pinned.com", status="trusted", consecutive_misses=4)]
        updated = record_source_result(registry, ["pinned.com"], "pinned.com", 0)
        assert updated == registry

    def test_unknown_domain_changes_nothing(self):
        registry = [entry("guide.com", status="trusted")]
        assert record_source_result(registry, None, "elsewhere.com", 3) == registry

    def test_input_registry_is_not_mutated(self):
        registry = [entry("cand.com")]
        record_source_result(registry, None, "cand.com", PROMOTE_MIN_TIERED_OBS)
        assert registry == [entry("cand.com")]
