"""Reading a price without a browser.

Structured data exists for crawlers, so on most marketplaces the same
JSON-LD or `product:price:amount` the browser saw is already in the raw HTML
— and a plain GET costs a few kilobytes and no Chromium page load at all.

Two moments use this. At learn time, probe() checks whether the locator just
verified in the browser reads the same price out of the raw HTML; when it
does, listings.static_ok is set and that listing's rechecks stop opening a
browser. At recheck time, read() is the ladder's first rung — and a
deliberately incurious one: a 404, a redirect, a challenge
page or a price that does not match all fall straight through to the browser,
which confirms availability itself. Nothing here ever concludes that a
listing is gone.

Only `jsonld` and `meta` locators can be probed. `css` and `microdata` are
element paths and Python has no DOM; parsing HTML with regexes to fake one is
how you end up recording the wrong number.

No new dependency: html.parser from the standard library, and the httpx the
agent already uses.
"""

import logging
from decimal import Decimal
from html.parser import HTMLParser

import httpx
from config import STATIC_FETCH
from locators import Locator, read_with
from validation import parse_price, url_allowed

log = logging.getLogger(__name__)

# The kinds that live in the raw HTML. A css or microdata locator is a path
# through a rendered DOM and cannot be replayed here at all.
STATIC_KINDS = ("jsonld", "meta")

# One GET, hard-bounded: this rung exists to be cheap, and a site that hangs
# should cost less than the browser it is replacing, not more.
TIMEOUT_SECONDS = 15.0
# Past this the response is not a listing page; reading it all is wasted work.
MAX_BYTES = 4_000_000

# Sent because a bare python-httpx User-Agent is the first thing a
# marketplace's bot filter rejects. The point is to look like the browser
# whose read this is replacing, not to defeat a filter: a site that refuses
# is simply read with the browser instead.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class _Structured(HTMLParser):
    """Pulls the JSON-LD bodies and meta tags out of raw HTML.

    Everything else is ignored, including the document structure: this is not
    a DOM, and nothing built on it may claim to be one. HTMLParser switches
    to CDATA mode inside <script>, so a JSON-LD body arrives verbatim rather
    than entity-decoded.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.jsonld: list[str] = []
        self.meta: dict[str, str] = {}
        self._in_jsonld = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        values = {key.lower(): (value or "") for key, value in attrs}
        if tag == "script":
            self._in_jsonld = values.get("type", "").strip().lower() == "application/ld+json"
        elif tag == "meta":
            key = (values.get("property") or values.get("name") or "").strip().lower()
            content = values.get("content")
            # first wins, matching PAGE_EXTRACTOR_JS
            if key and content and key not in self.meta:
                self.meta[key] = content

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_jsonld = False

    def handle_data(self, data: str) -> None:
        if self._in_jsonld and data.strip():
            self.jsonld.append(data.strip())


def extract(html: str) -> dict:
    """The structured data in a raw HTML document.

    Shaped like a PAGE_EXTRACTOR_JS payload on purpose — same `jsonld` list,
    same `meta` mapping — so locators.read_with replays a locator against raw
    HTML and against a rendered page with one implementation and no second
    idea of what a locator means.

    Args:
      html: The response body.
    Returns:
      {"jsonld": [raw script bodies], "meta": {key: content}}. Malformed
      markup yields whatever was parseable before it; a page that states
      nothing yields empty collections.
    """
    parser = _Structured()
    try:
        parser.feed(html)
        parser.close()
    except AssertionError as e:
        # html.parser raises bare AssertionErrors on some malformed markup
        log.info(f"Static parse stopped early on malformed markup: {e}")
    return {"jsonld": parser.jsonld, "meta": parser.meta}


async def fetch(url: str, site_base_url: str | None) -> str | None:
    """GET one listing page as plain HTML, or None.

    Guarded exactly as a navigation is: the URL must belong to the
    site's own domain and must not be a private address, checked before a
    connection is opened. Redirects are never followed — a listing that has
    moved is a change in availability, and the browser is what decides that.

    Args:
      url: The listing URL.
      site_base_url: The site's base_url, which fixes the allowed domain.
    Returns:
      The response body, or None for anything that is not a plain 200 —
      a redirect, a 404, a challenge page, a timeout. Never raises: every
      one of those is "read it with the browser instead".
    """
    refused = url_allowed(url, site_base_url)
    if refused:
        log.warning(f"Static fetch refused for {url}: {refused}")
        return None

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT_SECONDS, follow_redirects=False, headers=HEADERS
        ) as client:
            response = await client.get(url)
    except httpx.HTTPError as e:
        log.info(f"Static fetch of {url} failed: {e}")
        return None

    if response.status_code != httpx.codes.OK:
        log.info(f"Static fetch of {url} answered {response.status_code}; using the browser")
        return None
    if len(response.content) > MAX_BYTES:
        log.info(f"Static fetch of {url} returned {len(response.content)} bytes; using the browser")
        return None
    return response.text


async def structured(url: str, site_base_url: str | None, kind: str) -> dict | None:
    """The raw page's structured data, or None to use the browser instead.

    The one place that decides whether a listing can be read without a
    browser at all: the STATIC_FETCH kill switch, the kinds that can live in
    raw HTML, and the fetch itself.

    Args:
      url: The listing URL.
      site_base_url: The site's base_url, for the guard.
      kind: The locator kind about to be replayed.
    Returns:
      An extract() payload, or None.
    """
    if not STATIC_FETCH or kind not in STATIC_KINDS:
        return None
    html = await fetch(url, site_base_url)
    return None if html is None else extract(html)


async def read(url: str, site_base_url: str | None, locator: Locator) -> str | None:
    """One GET, one locator, no browser.

    Args:
      url: The listing URL.
      site_base_url: The site's base_url, for the guard.
      locator: The listing's stored locator. A kind that cannot live in raw
        HTML reads nothing rather than guessing.
    Returns:
      The raw text the locator found — still unvalidated, the caller decides
      whether to believe it — or None, which means "use the browser".
    """
    raw = await structured(url, site_base_url, locator.kind)
    return None if raw is None else read_with(locator.kind, locator.locator, raw)


async def probe(url: str, site_base_url: str | None, locator: Locator, price: Decimal) -> bool:
    """Whether this listing can be rechecked without a browser from now on.

    Run once, at the moment a locator is learned and verified: the LLM read
    that paid for the locator also pays for this, and every browserless
    recheck afterwards is the return on it. Only an exact match counts —
    a raw page that states a different number than the rendered one is a page
    where the rendered one is the truth.

    Args:
      url: The listing URL.
      site_base_url: The site's base_url, for the guard.
      locator: The locator just verified in the browser.
      price: The price the browser confirmed through it.
    Returns:
      True to set listings.static_ok.
    """
    found = await read(url, site_base_url, locator)
    if found is None:
        return False
    if parse_price(found) != price:
        log.info(f"Static probe of {url} read {found!r}, not {price}; keeping the browser")
        return False
    log.info(f"Static probe of {url} matched {price}: rechecks can skip the browser")
    return True
