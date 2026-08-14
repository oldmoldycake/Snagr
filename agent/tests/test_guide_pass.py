"""The guide-pass orchestration with every seam (DB helpers, page fetching)
monkeypatched: fetch order, the dry-run candidate probe, registry write-back,
guide-page caching, and the snippet shotgun staying unfired when a guide
already answered."""

import asyncio
from decimal import Decimal

import pricing
from pricing import Observation


def entry(domain, status="candidate", hits=0, consecutive_misses=0):
    return {
        "domain": domain,
        "kind": "price_guide",
        "status": status,
        "hits": hits,
        "consecutive_misses": consecutive_misses,
        "notes": None,
    }


def guide_obs(price, url):
    return Observation(
        price=Decimal(price),
        tier="loose",
        condition_raw=None,
        sold_or_asking="sold",
        source_url=url,
        source_type="price_guide",
        origin="guide",
    )


def wire(monkeypatch, registry, pinned=None, guide_pages=None, yields=None):
    """Point every seam at in-memory fakes. `yields` maps domain -> how many
    tier-tagged observations its fetch produces; returns what the fakes saw."""
    recorded = {"fetched": [], "registry": None, "pages": None}

    async def get_price_sources(category_id):
        return {"price_sources": registry, "pinned_sources": pinned}

    async def get_item_grounding(item_id):
        return {
            "name": "Pokemon Emerald",
            "search_aliases": ["pokemon emerald gba"],
            "guide_pages": guide_pages,
        }

    async def set_price_sources(category_id, sources):
        recorded["registry"] = sources
        return True

    async def set_guide_pages(item_id, pages):
        recorded["pages"] = pages
        return True

    async def fetch_domain_observations(domain, alias, item_name, tiers, cached_url):
        recorded["fetched"].append(domain)
        count = (yields or {}).get(domain, 0)
        if not count:
            return [], None
        url = f"https://{domain}/guide"
        return [guide_obs("100", url) for _ in range(count)], url

    monkeypatch.setattr(pricing, "get_price_sources", get_price_sources)
    monkeypatch.setattr(pricing, "get_item_grounding", get_item_grounding)
    monkeypatch.setattr(pricing, "set_price_sources", set_price_sources)
    monkeypatch.setattr(pricing, "set_guide_pages", set_guide_pages)
    monkeypatch.setattr(pricing, "fetch_domain_observations", fetch_domain_observations)
    return recorded


def gather():
    return asyncio.run(pricing.gather_guide_observations(1, "Pokemon Emerald", 1, ["loose"]))


class TestGatherGuideObservations:
    def test_candidate_probed_when_sure_things_come_up_dry(self, monkeypatch):
        registry = [entry("guide.com", status="trusted"), entry("cand.com")]
        recorded = wire(monkeypatch, registry, yields={"guide.com": 2, "cand.com": 2})
        observations = gather()
        assert recorded["fetched"] == ["guide.com", "cand.com"]
        assert len(observations) == 4

    def test_candidate_left_alone_when_guides_answer(self, monkeypatch):
        registry = [
            entry("a.com", status="trusted"),
            entry("b.com", status="trusted"),
            entry("cand.com"),
        ]
        recorded = wire(monkeypatch, registry, yields={"a.com": 2, "b.com": 2})
        gather()
        assert recorded["fetched"] == ["a.com", "b.com"]

    def test_registry_updates_written_back_pinned_exempt(self, monkeypatch):
        registry = [entry("cand.com")]
        recorded = wire(
            monkeypatch, registry, pinned=["pinned.com"], yields={"pinned.com": 2, "cand.com": 2}
        )
        gather()
        assert recorded["fetched"] == ["pinned.com", "cand.com"]
        (updated,) = recorded["registry"]
        assert (updated["domain"], updated["status"], updated["hits"]) == ("cand.com", "trusted", 1)

    def test_resolved_pages_cached_unchanged_pages_not_rewritten(self, monkeypatch):
        registry = [entry("guide.com", status="trusted"), entry("other.com", status="trusted")]
        recorded = wire(monkeypatch, registry, yields={"guide.com": 2, "other.com": 2})
        gather()
        assert recorded["pages"] == {
            "guide.com": "https://guide.com/guide",
            "other.com": "https://other.com/guide",
        }

        already_cached = dict(recorded["pages"])
        recorded = wire(
            monkeypatch,
            registry,
            guide_pages=already_cached,
            yields={"guide.com": 2, "other.com": 2},
        )
        gather()
        assert recorded["pages"] is None

    def test_dead_cached_page_dropped(self, monkeypatch):
        registry = [entry("guide.com", status="trusted")]
        recorded = wire(
            monkeypatch, registry, guide_pages={"guide.com": "https://guide.com/old"}, yields={}
        )
        assert gather() == []
        assert recorded["pages"] == {}

    def test_no_sources_yet_is_a_quiet_no_op(self, monkeypatch):
        recorded = wire(monkeypatch, registry=None)
        assert gather() == []
        assert recorded["fetched"] == []
        assert recorded["registry"] is None


class TestCollectObservations:
    def test_snippet_shotgun_stays_unfired_when_a_guide_answered(self, monkeypatch):
        searched = []

        async def fake_gather(item_id, item_name, category_id, tiers):
            return [guide_obs("226", "https://guide.com/x")]

        async def fake_search(item, base_url=None):
            searched.append(item)
            return {}

        monkeypatch.setattr(pricing, "gather_guide_observations", fake_gather)
        monkeypatch.setattr(pricing, "search_searxng_queries", fake_search)
        observations = asyncio.run(pricing.collect_observations(1, "Pokemon Emerald", 1, ["loose"]))
        assert searched == []
        assert len(observations) == 1

    def test_falls_back_to_broad_snippets_when_guides_are_dry(self, monkeypatch):
        searched = []

        async def fake_gather(item_id, item_name, category_id, tiers):
            return []

        async def fake_search(item, base_url=None):
            searched.append(item)
            return {"https://x.com/1": "sold for $100 loose"}

        async def fake_extract(item, search_results, tiers):
            assert search_results == {"https://x.com/1": "sold for $100 loose"}
            return [guide_obs("100", "https://x.com/1")]

        monkeypatch.setattr(pricing, "gather_guide_observations", fake_gather)
        monkeypatch.setattr(pricing, "search_searxng_queries", fake_search)
        monkeypatch.setattr(pricing, "extract_observations", fake_extract)
        observations = asyncio.run(pricing.collect_observations(1, "Pokemon Emerald", 1, ["loose"]))
        assert searched == ["Pokemon Emerald"]
        assert len(observations) == 1
