"""Grounding search across its three providers: the request each one sends,
how its answer becomes {url: snippet}, and how it backs off when the
provider pushes back.

Nothing here reaches the network: httpx.AsyncClient is replaced by a
transport that answers from a script, and asyncio.sleep only records how long
it was asked to wait. Config validation runs `import config` in a subprocess,
because the checks run at import time and the test process has already
imported it.
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import search

AGENT_DIR = Path(__file__).resolve().parents[1]


def brave_answer(results, more=False):
    return httpx.Response(
        200, json={"web": {"results": results}, "query": {"more_results_available": more}}
    )


def searxng_answer(results, unresponsive=None):
    return httpx.Response(
        200, json={"results": results, "unresponsive_engines": unresponsive or []}
    )


@pytest.fixture
def served(monkeypatch):
    """Answer each GET with the next scripted response, and record what was
    requested and every sleep.

    Set `served["responses"]` to the responses (or exceptions) in order;
    read `served["requests"]` and `served["slept"]` back.
    """
    state = {"responses": [], "requests": [], "slept": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        response = state["responses"].pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    original = httpx.AsyncClient

    def client(**kwargs):
        return original(transport=httpx.MockTransport(handler), **kwargs)

    async def sleep(seconds):
        state["slept"].append(seconds)

    monkeypatch.setattr(search.httpx, "AsyncClient", client)
    monkeypatch.setattr(search.asyncio, "sleep", sleep)
    return state


@pytest.fixture
def brave(monkeypatch, served):
    monkeypatch.setattr(search, "SEARCH_PROVIDER", "brave")
    monkeypatch.setattr(search, "BRAVE_API_KEY", "test-brave-key")
    return served


@pytest.fixture
def searxng(monkeypatch, served):
    monkeypatch.setattr(search, "SEARCH_PROVIDER", "searxng")
    monkeypatch.setattr(search, "SEARXNG_URL", "http://searx.lan:8888")
    return served


def run(queries, pages=None):
    return asyncio.run(search.search(queries, pages))


class TestBrave:
    def test_request_carries_the_key_and_asks_for_one_page_of_twenty(self, brave):
        brave["responses"] = [brave_answer([])]
        run(["pokemon emerald sold price"])

        (request,) = brave["requests"]
        assert str(request.url).startswith(search.BRAVE_SEARCH_URL)
        assert request.headers["X-Subscription-Token"] == "test-brave-key"
        assert request.url.params["q"] == "pokemon emerald sold price"
        assert request.url.params["count"] == "20"
        assert request.url.params["offset"] == "0"
        assert request.url.params["extra_snippets"] == "true"

    def test_results_become_plain_text_snippets(self, brave):
        brave["responses"] = [
            brave_answer(
                [
                    {
                        "url": "https://a.com/1",
                        "description": "<strong>Pokemon Emerald</strong> sold for $120 &amp; up",
                        "extra_snippets": ["Loose: $95", "CIB: $210"],
                    },
                    {"url": "https://b.com/2"},
                ]
            )
        ]

        assert run(["q"]) == {
            "https://a.com/1": "Pokemon Emerald sold for $120 & up Loose: $95 CIB: $210",
            "https://b.com/2": "",
        }

    def test_results_dedupe_by_url_across_queries(self, brave):
        brave["responses"] = [
            brave_answer([{"url": "https://a.com/1", "description": "first"}]),
            brave_answer(
                [
                    {"url": "https://a.com/1", "description": "again"},
                    {"url": "https://b.com/2", "description": "new"},
                ]
            ),
        ]

        assert list(run(["one", "two"])) == ["https://a.com/1", "https://b.com/2"]

    def test_an_answer_without_web_results_is_no_results(self, brave):
        brave["responses"] = [httpx.Response(200, json={"query": {}})]
        assert run(["q"], pages=3) == {}
        assert len(brave["requests"]) == 1

    def test_later_pages_are_asked_for_only_while_brave_has_more(self, brave):
        brave["responses"] = [
            brave_answer([{"url": "https://a.com/1"}], more=True),
            brave_answer([{"url": "https://b.com/2"}], more=False),
        ]

        assert len(run(["q"], pages=3)) == 2
        assert [r.url.params["offset"] for r in brave["requests"]] == ["0", "1"]

    def test_requests_are_paced_for_the_free_plan(self, brave):
        brave["responses"] = [brave_answer([{"url": "https://a.com/1"}])]
        run(["q"])
        assert brave["slept"] == [search.BRAVE_INTER_REQUEST_DELAY_S]

    def test_one_rate_limit_is_waited_out_and_retried(self, brave):
        brave["responses"] = [
            httpx.Response(429),
            brave_answer([{"url": "https://a.com/1", "description": "$10"}]),
        ]

        assert run(["q"]) == {"https://a.com/1": "$10"}
        assert brave["slept"][0] == search.BRAVE_RATE_LIMIT_BACKOFF_S

    def test_a_second_rate_limit_stops_the_search_with_what_it_has(self, brave):
        brave["responses"] = [
            httpx.Response(429),
            brave_answer([{"url": "https://a.com/1"}]),
            httpx.Response(429),
        ]

        assert list(run(["one", "two", "three"])) == ["https://a.com/1"]
        assert len(brave["requests"]) == 3

    def test_an_http_error_answers_none(self, brave):
        brave["responses"] = [httpx.Response(401)]
        assert run(["q"]) is None


class TestSearxng:
    def test_request_asks_the_configured_instance_for_json(self, searxng):
        searxng["responses"] = [searxng_answer([])]
        run(["q"])

        (request,) = searxng["requests"]
        assert str(request.url).startswith("http://searx.lan:8888/search")
        assert request.url.params["format"] == "json"
        assert request.url.params["pageno"] == "1"

    def test_three_pages_by_default(self, searxng):
        searxng["responses"] = [
            searxng_answer([{"url": f"https://a.com/{page}", "content": "x"}]) for page in range(3)
        ]

        assert len(run(["q"])) == 3
        assert [r.url.params["pageno"] for r in searxng["requests"]] == ["1", "2", "3"]

    def test_a_suspension_is_slept_off_once_then_retried(self, searxng):
        searxng["responses"] = [
            searxng_answer([], unresponsive=[["google", "Suspended: too many requests"]]),
            searxng_answer([{"url": "https://a.com/1", "content": "$10"}]),
        ]

        assert run(["q"], pages=1) == {"https://a.com/1": "$10"}
        assert searxng["slept"][0] == search.SEARXNG_SUSPENSION_BACKOFF_S


class TestNoProvider:
    def test_no_request_is_made_and_nothing_is_found(self, monkeypatch, served):
        monkeypatch.setattr(search, "SEARCH_PROVIDER", "none")
        assert run(["q"]) == {}
        assert served["requests"] == []


def provider_for(**env):
    """Import config in a fresh interpreter under `env` layered over a blank
    search config, and answer (returncode, output)."""
    blank = {"SEARCH_PROVIDER": "", "SEAR_XNG_URL": "", "BRAVE_API_KEY": ""}
    done = subprocess.run(
        [sys.executable, "-c", "import config; print(config.SEARCH_PROVIDER)"],
        cwd=AGENT_DIR,
        env={**os.environ, **blank, **env},
        capture_output=True,
        text=True,
    )
    return done.returncode, done.stdout.strip() + done.stderr


class TestConfig:
    def test_unset_follows_sear_xng_url(self):
        assert provider_for(SEAR_XNG_URL="http://searx.lan:8888") == (0, "searxng")
        assert provider_for() == (0, "none")

    def test_an_explicit_choice_wins(self):
        assert provider_for(SEARCH_PROVIDER="Brave", BRAVE_API_KEY="k", SEAR_XNG_URL="x") == (
            0,
            "brave",
        )

    def test_brave_without_a_key_stops_the_agent(self):
        code, output = provider_for(SEARCH_PROVIDER="brave")
        assert code != 0
        assert "SEARCH_PROVIDER=brave needs BRAVE_API_KEY" in output

    def test_searxng_without_a_url_stops_the_agent(self):
        code, output = provider_for(SEARCH_PROVIDER="searxng")
        assert code != 0
        assert "SEARCH_PROVIDER=searxng needs SEAR_XNG_URL" in output

    def test_an_unknown_provider_stops_the_agent(self):
        code, output = provider_for(SEARCH_PROVIDER="google")
        assert code != 0
        assert "must be searxng, brave or none" in output
