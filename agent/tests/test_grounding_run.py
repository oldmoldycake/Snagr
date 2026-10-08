"""TTL-gated grounding work selection, the ground_item entry point, and what
a SearXNG suspension does to a grounding, with every DB seam monkeypatched
and SearXNG answered from a script.

Queueing the selected work is the scheduler's job now, one `ground` job per
due item — see test_worker.py."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pricing
import pytest
import search
from pricing import Observation
from search import SearchGate, SearchSuspended

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


def extracted_prices(monkeypatch, reply):
    """The prices extract_observations keeps from a raw model reply."""
    monkeypatch.setattr(pricing, "build_llm", lambda: FakeLLM(reply))
    observations = asyncio.run(
        pricing.extract_observations("Pokemon Emerald", {"https://a.test": "$100"}, ["loose"])
    )
    return [o.price for o in observations]


class TestExtractedPrices:
    """The model's prices are JSON from outside this system, parsed the way a
    page's price is and refused unless they are a positive amount."""

    @pytest.mark.parametrize(
        "price, expected",
        [
            ('"12,99"', "12.99"),
            ('"1.234,56"', "1234.56"),
            ('"1,234.56"', "1234.56"),
            ('"$226"', "226"),
            ("59.99", "59.99"),
        ],
    )
    def test_separators_are_read_by_position(self, monkeypatch, price, expected):
        reply = f'{{"observations": [{{"price": {price}, "source_url": "https://a.test"}}]}}'

        assert extracted_prices(monkeypatch, reply) == [Decimal(expected)]

    @pytest.mark.parametrize("price", ['"NaN"', "NaN", "1e999", '"Infinity"', "-5", '"-5"', "0"])
    def test_a_price_that_is_not_a_positive_amount_is_dropped(self, monkeypatch, price):
        reply = (
            f'{{"observations": [{{"price": {price}, "source_url": "https://a.test"}},'
            f' {{"price": "100", "source_url": "https://a.test"}}]}}'
        )

        assert extracted_prices(monkeypatch, reply) == [Decimal("100")]


SUSPENDED = {"results": [], "unresponsive_engines": [["google", "Suspended: too many requests"]]}
RESULTS = {"results": [{"url": "https://guide.example/emerald", "content": "Loose $226"}]}


@pytest.fixture
def searxng(monkeypatch):
    """Answer every SearXNG query from a script, with a fresh gate and no
    pacing delay. Set `searxng["replies"]` to the JSON bodies to answer with,
    in order (the last one repeats), and read `searxng["queries"]` back."""
    state = {"replies": [RESULTS], "queries": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["queries"].append(request.url.params["q"])
        replies = state["replies"]
        return httpx.Response(200, json=replies.pop(0) if len(replies) > 1 else replies[0])

    original = httpx.AsyncClient

    def client(**kwargs):
        return original(transport=httpx.MockTransport(handler), **kwargs)

    # pricing holds its own reference to the gate; both must see the same one
    gate = SearchGate()
    monkeypatch.setattr(search.httpx, "AsyncClient", client)
    monkeypatch.setattr(search, "search_gate", gate)
    monkeypatch.setattr(pricing, "search_gate", gate)
    monkeypatch.setattr(search, "SEARXNG_INTER_REQUEST_DELAY_S", 0)
    monkeypatch.setattr(search, "SEARCH_PROVIDER", "searxng")
    monkeypatch.setattr(search, "SEARXNG_URL", "http://searxng")
    return state


def run_search(queries=("emerald",), pages=1):
    return asyncio.run(search.search(list(queries), pages=pages))


class TestSearchSuspension:
    """A suspension lasts minutes to hours. Sleeping it off inside the job held
    the pool slot the whole time, so it raises instead, and the gate keeps
    every other ground job from asking again until the wait is over."""

    def test_a_suspension_raises_at_once_instead_of_sleeping(self, searxng, monkeypatch):
        async def no_sleeping(seconds):
            raise AssertionError(f"slept {seconds}s")

        monkeypatch.setattr(search.asyncio, "sleep", no_sleeping)
        searxng["replies"] = [SUSPENDED]

        with pytest.raises(SearchSuspended) as raised:
            run_search()

        wait = raised.value.until - datetime.now(UTC)
        assert timedelta(seconds=search.SEARXNG_SUSPENSION_BACKOFF_S - 5) < wait
        assert wait <= timedelta(seconds=search.SEARXNG_SUSPENSION_BACKOFF_S)
        assert searxng["queries"] == ["emerald"]

    def test_a_closed_gate_asks_searxng_nothing(self, searxng):
        searxng["replies"] = [SUSPENDED]
        with pytest.raises(SearchSuspended):
            run_search()

        with pytest.raises(SearchSuspended):
            run_search(["another item"])
        assert searxng["queries"] == ["emerald"]

    def test_a_suspension_that_outlasts_the_wait_doubles_it_to_the_cap(self):
        gate = SearchGate()
        waits = []
        for _ in range(6):
            start = datetime.now(UTC)
            waits.append(round((gate.close() - start).total_seconds() / 60))

        assert waits == [15, 30, 60, 120, 240, 240]

    def test_results_reset_the_wait(self, searxng):
        searxng["replies"] = [SUSPENDED]
        with pytest.raises(SearchSuspended):
            run_search()
        search.search_gate.until = datetime.now(UTC) - timedelta(seconds=1)
        searxng["replies"] = [RESULTS]

        assert run_search() == {"https://guide.example/emerald": "Loose $226"}
        assert search.search_gate.closed_until() is None
        assert search.search_gate.backoff_s == search.SEARXNG_SUSPENSION_BACKOFF_S

    def test_an_empty_page_without_a_suspension_is_just_empty(self, searxng):
        searxng["replies"] = [{"results": [], "unresponsive_engines": []}]
        assert run_search() == {}
        assert search.search_gate.closed_until() is None

    def test_a_closed_gate_defers_a_grounding_before_it_spends_anything(self, searxng, monkeypatch):
        async def never(*args, **kwargs):
            raise AssertionError("grounding went ahead behind a closed gate")

        monkeypatch.setattr(pricing, "resolve_condition_tiers", never)
        monkeypatch.setattr(pricing, "upsert_market_price", never)
        until = search.search_gate.close()

        with pytest.raises(SearchSuspended) as raised:
            asyncio.run(pricing.ground_item(7, "Pokemon Emerald", 1))
        assert raised.value.until == until

    def test_a_suspension_midway_writes_nothing(self, searxng, monkeypatch):
        # stats built on half a search would read as the market, and the
        # write would stamp the item as attempted for a whole TTL
        async def fake_resolve_tiers(category_id):
            return ["loose"]

        async def no_guides(item_id, item_name, category_id, tiers):
            return []

        async def never(*args, **kwargs):
            raise AssertionError("a suspended grounding wrote its stats")

        monkeypatch.setattr(pricing, "resolve_condition_tiers", fake_resolve_tiers)
        monkeypatch.setattr(pricing, "gather_guide_observations", no_guides)
        monkeypatch.setattr(pricing, "upsert_market_price", never)
        searxng["replies"] = [SUSPENDED]

        with pytest.raises(SearchSuspended):
            asyncio.run(pricing.ground_item(7, "Pokemon Emerald", 1))
