"""TTL-gated grounding work selection and the ground_item entry point, with
every DB seam monkeypatched.

Queueing the selected work is the scheduler's job now, one `ground` job per
due item — see test_worker.py."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pricing
from pricing import Observation

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def candidate(item_id, as_of=None, last_attempt_at=None):
    return {
        "item_id": item_id,
        "item_name": f"item {item_id}",
        "category_id": 1,
        "as_of": as_of,
        "last_attempt_at": last_attempt_at,
    }


def hours_ago(hours):
    return NOW - timedelta(hours=hours)


def selected_ids(candidates):
    return [row["item_id"] for row in pricing.select_grounding_work(candidates, NOW)]


class TestSelectGroundingWork:
    def test_never_grounded_items_come_first_and_ignore_the_cap(self, monkeypatch):
        monkeypatch.setattr(pricing, "MARKET_PRICE_MAX_REFRESH_PER_RUN", 1)
        candidates = [
            candidate(1, as_of=hours_ago(100), last_attempt_at=hours_ago(100)),
            candidate(2),
            candidate(3),
        ]
        assert selected_ids(candidates) == [2, 3, 1]

    def test_fresh_items_are_left_alone(self):
        candidates = [candidate(1, as_of=hours_ago(1), last_attempt_at=hours_ago(1))]
        assert selected_ids(candidates) == []

    def test_stale_items_refresh_oldest_first_under_the_cap(self, monkeypatch):
        monkeypatch.setattr(pricing, "MARKET_PRICE_MAX_REFRESH_PER_RUN", 2)
        candidates = [
            candidate(1, as_of=hours_ago(50), last_attempt_at=hours_ago(50)),
            candidate(2, as_of=hours_ago(200), last_attempt_at=hours_ago(200)),
            candidate(3, as_of=hours_ago(100), last_attempt_at=hours_ago(100)),
        ]
        assert selected_ids(candidates) == [2, 3]

    def test_recent_attempt_defers_an_item_even_when_grounding_failed(self):
        # as_of never moved (attempts kept failing) but the attempt was recent:
        # retrying every run would burn full grounding cost on a hard item.
        candidates = [
            candidate(1, last_attempt_at=hours_ago(1)),
            candidate(2, as_of=hours_ago(100), last_attempt_at=hours_ago(1)),
        ]
        assert selected_ids(candidates) == []


def observation(price):
    return Observation(
        price=Decimal(price),
        tier="loose",
        condition_raw=None,
        sold_or_asking="sold",
        source_url="https://guide.com/x",
        source_type="price_guide",
        origin="guide",
    )


class TestGroundItem:
    def test_grounds_one_item_end_to_end_and_upserts_the_payload(self, monkeypatch):
        upserted = {}

        async def fake_resolve_tiers(category_id):
            return ["loose", "cib"]

        async def fake_collect(item_id, item_name, category_id, tiers):
            assert (item_id, item_name, category_id) == (7, "Pokemon Emerald", 1)
            assert tiers == ["loose", "cib"]
            return [observation("100"), observation("110")]

        async def fake_upsert(item_id, **kwargs):
            upserted["item_id"] = item_id
            upserted.update(kwargs)
            return True

        monkeypatch.setattr(pricing, "resolve_condition_tiers", fake_resolve_tiers)
        monkeypatch.setattr(pricing, "collect_observations", fake_collect)
        monkeypatch.setattr(pricing, "upsert_market_price", fake_upsert)

        payload = asyncio.run(pricing.ground_item(7, "Pokemon Emerald", 1))

        assert payload["status"] == "ok"
        assert upserted["item_id"] == 7
        assert upserted["status"] == "ok"
        assert upserted["currency"] == "USD"
        assert upserted["tiers"] == payload["tiers"]
        assert len(upserted["observations"]) == 2

    def test_an_implausible_price_never_reaches_the_published_tiers(self, monkeypatch):
        upserted = {}

        async def fake_resolve_tiers(category_id):
            return ["loose"]

        async def fake_collect(item_id, item_name, category_id, tiers):
            return [
                observation("100"),
                observation("110"),
                observation("120"),
                observation("9000"),
            ]

        async def fake_upsert(item_id, **kwargs):
            upserted.update(kwargs)
            return True

        monkeypatch.setattr(pricing, "resolve_condition_tiers", fake_resolve_tiers)
        monkeypatch.setattr(pricing, "collect_observations", fake_collect)
        monkeypatch.setattr(pricing, "upsert_market_price", fake_upsert)

        asyncio.run(pricing.ground_item(7, "Pokemon Emerald", 1))

        assert upserted["tiers"]["loose"]["high"] == "120.00"
        assert upserted["tiers"]["loose"]["n"] == 3
        assert [o["excluded"] for o in upserted["observations"]] == [None, None, None, "outlier"]


class FakeLLM:
    """Records the config each model call was made with, and answers with a
    canned reply."""

    def __init__(self, reply):
        self.reply = reply
        self.configs = []

    async def ainvoke(self, prompt, config=None):
        self.configs.append(config)
        return type("Reply", (), {"content": self.reply})()


class TestGroundingCallsAreTraced:
    """Each call carries the tracing handler and a name of its own; the
    session and tags come from the trace the ground job opens around them
    (test_tracing.py)."""

    def test_an_extraction_call_is_traced_by_name(self, monkeypatch):
        llm = FakeLLM('{"observations": []}')
        monkeypatch.setattr(pricing, "build_llm", lambda: llm)
        monkeypatch.setattr(pricing, "callbacks", ["handler"])

        asyncio.run(
            pricing.extract_observations("Pokemon Emerald", {"https://a.test": "$100"}, ["loose"])
        )

        assert llm.configs == [{"callbacks": ["handler"], "run_name": "extract-observations"}]

    def test_tier_generation_is_traced_by_name(self, monkeypatch):
        llm = FakeLLM('["loose", "cib"]')
        monkeypatch.setattr(pricing, "build_llm", lambda: llm)
        monkeypatch.setattr(pricing, "callbacks", ["handler"])

        async def fake_category(category_id):
            return {"name": "Video games", "condition_tiers": None}

        async def fake_item_names(category_id):
            return ["Pokemon Emerald"]

        async def fake_set_tiers(category_id, tiers):
            return None

        monkeypatch.setattr(pricing, "get_category_tiers", fake_category)
        monkeypatch.setattr(pricing, "get_category_item_names", fake_item_names)
        monkeypatch.setattr(pricing, "set_condition_tiers", fake_set_tiers)

        assert asyncio.run(pricing.resolve_condition_tiers(1)) == ["loose", "cib"]
        assert llm.configs == [{"callbacks": ["handler"], "run_name": "condition-tiers"}]
