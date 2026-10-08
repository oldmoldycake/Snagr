"""Web search for market-price grounding: one call, whichever provider
SEARCH_PROVIDER names - a self-hosted SearXNG, the Brave Search API, or none.

Every provider answers the same shape, {url: snippet} deduped by url across
queries and pages, so grounding never knows which one ran. They fail
differently - SearXNG suspends its upstream engines and still answers 200,
Brave answers 429 - so each keeps its own pacing and back-off. Grounding is
best-effort: a failed search is logged and answers None. The one exception is
a SearXNG suspension, which lasts minutes to hours: that raises
SearchSuspended, and the worker hands the ground job back to the queue rather
than holding a pool slot to sleep it off.

No address guard on either: SearXNG is the operator's own service and usually
lives on the private network the guard exists to keep pages away from, and
the Brave endpoint is a constant, never a URL a page supplied.
"""

import asyncio
import html
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from config import BRAVE_API_KEY, SEARCH_PROVIDER, SEARXNG_URL

log = logging.getLogger(__name__)

SEARCH_TIMEOUT_SECONDS = 10

# Pages per query when the caller does not say; this SearXNG instance returns
# nothing past page 5.
SEARXNG_PAGES = 3

# SearXNG suspends its upstream engines when queried too fast. Grounding is not
# time-sensitive, so pace generously and back off long when it happens anyway:
# 15 minutes first, doubling while the suspension outlasts the wait, so a long
# one costs a search every few hours rather than one per item per wait.
SEARXNG_INTER_REQUEST_DELAY_S = 5.0
SEARXNG_SUSPENSION_BACKOFF_S = 900
SEARXNG_SUSPENSION_BACKOFF_CAP_S = 4 * 3600

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
# Brave bills per request and one request already carries 20 results - more
# than SearXNG's three pages - so a query costs one page unless asked for more.
BRAVE_RESULTS_PER_PAGE = 20
BRAVE_PAGES = 1
# The free plan allows one request a second. A 429 after the pause is the
# monthly quota, not the per-second window, and no wait inside a job fixes it.
BRAVE_INTER_REQUEST_DELAY_S = 1.1
BRAVE_RATE_LIMIT_BACKOFF_S = 2.0


class SearchSuspended(Exception):
    """SearXNG has suspended its upstream engines, so no search can succeed
    before `until`. Not the ground job's failure: the worker puts the job back
    in the queue, due then, with its attempt given back."""

    def __init__(self, until: datetime):
        """`until` is when the gate reopens: the job's new run_after."""
        super().__init__(f"SearXNG has suspended its engines; trying again at {until:%H:%M} UTC")
        self.until = until


@dataclass
class SearchGate:
    """Whether SearXNG is worth asking yet, for the whole process.

    One suspension means every ground job behind it would meet the same one,
    so the gate closes for all of them: a job that finds it closed is deferred
    before it spends a model call, and only one search goes out per wait to
    see whether the suspension has lifted. Each time it has not, the wait
    doubles up to SEARXNG_SUSPENSION_BACKOFF_CAP_S; any search that returns
    results resets it. In memory on purpose - a restart that forgets costs one
    search. Brave never closes it.
    """

    until: datetime | None = None
    backoff_s: int = SEARXNG_SUSPENSION_BACKOFF_S

    def closed_until(self) -> datetime | None:
        """When the current wait ends, or None when a search may go out now."""
        if self.until is not None and self.until > datetime.now(UTC):
            return self.until
        return None

    def close(self) -> datetime:
        """Start a wait after a suspension, doubling the next; returns its end."""
        self.until = datetime.now(UTC) + timedelta(seconds=self.backoff_s)
        self.backoff_s = min(self.backoff_s * 2, SEARXNG_SUSPENSION_BACKOFF_CAP_S)
        return self.until

    def reopen(self) -> None:
        """A search came back with results: the suspension is over."""
        self.until = None
        self.backoff_s = SEARXNG_SUSPENSION_BACKOFF_S


search_gate = SearchGate()


async def search(queries: list[str], pages: int | None = None) -> dict[str, str] | None:
    """Run each query against the configured provider and merge the results
    into {url: snippet}. `pages` caps how deep each query goes; None means the
    provider's own default depth. With no provider it answers {} without a
    request - a mode announced once at startup, not a failure to log per call.

    Raises SearchSuspended when SearXNG has suspended its engines, or already
    had when this was called."""
    match SEARCH_PROVIDER:
        case "searxng":
            return await _search_searxng(queries, pages or SEARXNG_PAGES)
        case "brave":
            return await _search_brave(queries, pages or BRAVE_PAGES)
        case _:
            return {}


async def _search_searxng(queries: list[str], pages: int) -> dict[str, str] | None:
    if until := search_gate.closed_until():
        raise SearchSuspended(until)
    try:
        search_results = {}

        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT_SECONDS) as client:
            for query in queries:
                pageno = 1
                while pageno <= pages:
                    log.info(f"Searching SearXNG (page {pageno}): {query}")
                    params = {"q": query, "format": "json", "pageno": pageno}
                    response = await client.get(f"{SEARXNG_URL}/search", params=params)
                    response.raise_for_status()
                    response_json = response.json()

                    results = response_json["results"]

                    # A suspension looks like success - HTTP 200 with an empty
                    # result list - so raise_for_status never sees it.
                    # Suspensions expire on their own, but in minutes to hours:
                    # sleeping one off here would hold a pool slot all that time.
                    if not results:
                        suspended = response_json.get("unresponsive_engines") or []
                        if suspended:
                            until = search_gate.close()
                            log.warning(
                                f"SearXNG engines suspended ({suspended}); "
                                f"no searches until {until:%H:%M} UTC"
                            )
                            raise SearchSuspended(until)
                        log.warning(f"No results on page {pageno} for: {query}")
                        break

                    search_gate.reopen()
                    known = len(search_results)
                    for result in results:
                        # Not every engine returns a snippet; the url is what dedupes.
                        search_results[result["url"]] = result.get("content") or ""
                    log.info(
                        f"{len(results)} results, {len(search_results) - known} new "
                        f"({len(results) - (len(search_results) - known)} already seen)"
                    )

                    pageno += 1
                    await asyncio.sleep(SEARXNG_INTER_REQUEST_DELAY_S)

        log.info(f"SearXNG search completed: {len(search_results)} unique urls")
        return search_results

    except SearchSuspended:
        raise
    except Exception as e:
        log.error(f"Error searching SearXNG: {e}")


def brave_snippet(result: dict) -> str:
    """One Brave result as plain snippet text. The description comes with
    <strong> around the matched words and HTML entities left in, and the extra
    snippets (on plans that return them) are more of the page's own text -
    more chances for a price to reach extraction."""
    parts = [result.get("description") or "", *(result.get("extra_snippets") or [])]
    text = " ".join(part for part in parts if part)
    return html.unescape(re.sub(r"<[^>]+>", "", text))


async def _search_brave(queries: list[str], pages: int) -> dict[str, str] | None:
    try:
        search_results = {}
        backed_off = False
        headers = {"Accept": "application/json", "X-Subscription-Token": BRAVE_API_KEY}

        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT_SECONDS, headers=headers) as client:
            for query in queries:
                page = 1
                while page <= pages:
                    log.info(f"Searching Brave (page {page}): {query}")
                    params = {
                        "q": query,
                        "count": BRAVE_RESULTS_PER_PAGE,
                        "offset": page - 1,
                        "extra_snippets": "true",
                    }
                    response = await client.get(BRAVE_SEARCH_URL, params=params)

                    if response.status_code == 429:
                        if not backed_off:
                            backed_off = True
                            log.warning(
                                f"Brave rate limit hit, backing off "
                                f"{BRAVE_RATE_LIMIT_BACKOFF_S}s before one retry"
                            )
                            await asyncio.sleep(BRAVE_RATE_LIMIT_BACKOFF_S)
                            continue
                        log.error("Brave still rate limited (monthly quota?), stopping search")
                        return search_results

                    response.raise_for_status()
                    response_json = response.json()

                    # No web results at all means no "web" key, not an empty list.
                    results = (response_json.get("web") or {}).get("results") or []
                    if not results:
                        log.warning(f"No results on page {page} for: {query}")
                        break

                    known = len(search_results)
                    for result in results:
                        search_results[result["url"]] = brave_snippet(result)
                    log.info(
                        f"{len(results)} results, {len(search_results) - known} new "
                        f"({len(results) - (len(search_results) - known)} already seen)"
                    )

                    await asyncio.sleep(BRAVE_INTER_REQUEST_DELAY_S)
                    if not (response_json.get("query") or {}).get("more_results_available"):
                        break
                    page += 1

        log.info(f"Brave search completed: {len(search_results)} unique urls")
        return search_results

    except Exception as e:
        log.error(f"Error searching Brave: {e}")
