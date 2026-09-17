"""What the agent is allowed to believe about a page.

Marketplace pages are untrusted input, and everything in this file exists
because something on one can otherwise reach somewhere it should not:

- parse_price / validate_observation (S1): the number stored is the number
  notified on. A page — or a mis-read of one — that says "$4.49" for a $449
  item would otherwise wake a buying bot. Implausible prices are still
  recorded, because hiding an observation is its own failure; they are just
  not believed until a second read agrees.
- url_allowed (S2): a saved listing URL is navigated to on every later
  recheck, so it is a request the agent will keep making. It must point at
  the site it claims to be on, and never at the private network the agent
  runs inside.
- clip_text (S4/S5): model-typed text is replayed into later prompts and
  into notification bodies. Caps and a single line keep a page from writing
  a paragraph into either.

Pure functions, all of them: no DB, no network, no DNS. The network-level
backstop for S2 is the MCP's own --blocked-origins (PR 2a).
"""

import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from config import (
    EXPECTED_CURRENCY,
    PRICE_BAND_HIGH,
    PRICE_BAND_LOW,
    PRICE_MARKET_FLOOR,
)

# Caps on model-typed text (S4/S5). Generous enough that no honest value is
# ever truncated — a marketplace title is ~80 characters — and small enough
# that a page cannot write an essay into the next scan prompt or an ntfy body.
MAX_TITLE = 300
MAX_SUMMARY = 300
MAX_REASON = 60
MAX_NOTES = 300
MAX_URL = 2000

# A price is at most this, in whatever currency: above it the page is not
# quoting a price, it is quoting a phone number or a part code.
MAX_PRICE = Decimal(10) ** 8
# How close a second read must be to an unconfirmed one to corroborate it.
CORROBORATION = Decimal("0.01")

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")

# Currency codes a marketplace page might state next to a price. A closed set
# on purpose: scanning visible text for any three capitals finds "ADD" in
# "ADD TO CART" and would record a price in a currency that does not exist.
CURRENCY_CODES = frozenset(
    {
        "USD",
        "EUR",
        "GBP",
        "JPY",
        "CAD",
        "AUD",
        "NZD",
        "CHF",
        "SEK",
        "NOK",
        "DKK",
        "PLN",
        "CZK",
        "MXN",
        "BRL",
        "INR",
        "SGD",
        "HKD",
        "KRW",
        "CNY",
        "ZAR",
        "TRY",
        "ILS",
        "AED",
    }
)
# Registrable-domain suffixes that are two labels deep. The full Public
# Suffix List is a dependency and a monthly update; this covers the
# marketplaces Snagr tracks, and a miss is conservative — an unlisted
# multi-part suffix makes the guard compare MORE of the host, never less.
_TWO_LABEL_SUFFIXES = frozenset(
    {
        "co.uk",
        "org.uk",
        "me.uk",
        "co.jp",
        "co.nz",
        "co.za",
        "com.au",
        "com.br",
        "com.mx",
        "com.sg",
        "com.hk",
        "com.tr",
    }
)


def parse_price(raw: object) -> Decimal | None:
    """The single price a piece of page text states, or None.

    Used by both halves of the system, which is the point: the number a
    locator yields is parsed exactly the way the number the model typed is,
    so "the locator still reads the confirmed price" is a comparison of like
    with like.

    Deliberately strict. Text holding two different numbers ("$10 to $20",
    "12 bids $30.00") is not a price — it is a range or a page fragment that
    happens to sit next to one — so it parses to None rather than to whichever
    number came first. Separators are read by position: with both present the
    rightmost is the decimal point, and a lone comma with one or two digits
    behind it is a decimal comma.

    Args:
      raw: Text, or a number JSON-LD stated directly. None and objects are
        not prices.
    Returns:
      The Decimal stated, or None when the text states no single price.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, (int, float)):
        raw = repr(raw)
    if not isinstance(raw, str):
        return None

    values = set()
    last = None
    for token in _NUMBER.findall(raw):
        try:
            last = Decimal(_normalise(token))
        except InvalidOperation:
            return None
        values.add(last)
    if len(values) != 1:
        return None
    return last


def _normalise(token: str) -> str:
    """One matched number token as a Decimal-parseable string."""
    if "." in token and "," in token:
        if token.rfind(".") > token.rfind(","):
            return token.replace(",", "")
        return token.replace(".", "").replace(",", ".")
    if token.count(",") == 1 and len(token.rsplit(",", 1)[1]) in (1, 2):
        return token.replace(",", ".")
    if "," in token:
        return token.replace(",", "")
    if token.count(".") > 1:
        return token.replace(".", "")
    return token


@dataclass(frozen=True)
class Verdict:
    """What one candidate observation is allowed to become.

    ok=False is a refusal: the reading is not a price at all and nothing is
    recorded. anomalous is the softer judgement — a real-looking number that
    does not fit what this listing and this market have shown — and it is
    what splits the two paths of the confirm rule (§4.3): an anomalous
    LOCATOR read is thrown away and the LLM re-reads the page, while an
    anomalous LLM read is recorded with confirmed=False, kept out of the
    aggregates, and believed only once a later read agrees within 1%.
    """

    ok: bool
    anomalous: bool = False
    confirmed: bool = True
    notifiable: bool = True
    reason: str | None = None


def validate_observation(
    price: Decimal | None,
    currency: str,
    listing: dict | None = None,
    market: dict | None = None,
    markers: dict | None = None,
) -> Verdict:
    """Judge one price reading before it is allowed to become a price check.

    Shape first (a price has at most two decimal places and is neither zero
    nor astronomical), then the auction rule, then plausibility against two
    references: this listing's own last price, and the item's market median
    for the condition the watch is after. Failing a band does not reject the
    reading — it withholds belief in it.

    A price in the wrong currency is recorded with notifiable=False rather
    than refused: the same "recorded, never mixed" stance the grounding pass
    takes, since a $226/€208 blend is a number with no meaning.

    Args:
      price: The parsed price, or None when nothing parsed.
      currency: The three-letter code the page quoted.
      listing: This listing's context, with two separate references.
        last_price is the last CONFIRMED price and is what the bands are
        measured against — deliberately not the last price of any kind, or
        one bad reading would become the yardstick that makes the next
        identical bad reading look normal. unconfirmed_price is the most
        recent reading if it was not believed, and exists only so a second
        reading can corroborate it.
      market: The item's market_prices payload (status/tiers/currency), and
        condition_hint for the tier the watch cares about. None when the item
        has never been grounded.
      markers: PAGE_EXTRACTOR_JS's markers for the page this was read from.
    Returns:
      A Verdict. ok=False means record nothing.
    """
    if price is None:
        return Verdict(ok=False, reason="no price parsed")
    # normalize() first: Adafruit really does state "35.0000" in its JSON-LD,
    # and trailing zeros are formatting, not precision. What this rejects is a
    # number with real digits past the cents place, which is not a price.
    if price.normalize().as_tuple().exponent < -2:
        return Verdict(ok=False, reason=f"{price} has more than two decimal places")
    if not 0 < price < MAX_PRICE:
        return Verdict(ok=False, reason=f"{price} is not a plausible price")
    if not re.fullmatch(r"[A-Z]{3}", currency or ""):
        return Verdict(ok=False, reason=f"{currency!r} is not a three-letter currency code")

    markers = markers or {}
    if markers.get("auction") and not markers.get("buy_now"):
        return Verdict(ok=False, reason="the page's only price is a bid")

    notifiable = currency == EXPECTED_CURRENCY
    reason = _band_failure(price, listing, market)
    if reason is None:
        return Verdict(ok=True, notifiable=notifiable)

    return Verdict(
        ok=True,
        anomalous=True,
        confirmed=_corroborates(price, listing),
        notifiable=notifiable,
        reason=reason,
    )


def _band_failure(price: Decimal, listing: dict | None, market: dict | None) -> str | None:
    """Why this price is implausible here, or None when it is not."""
    last = (listing or {}).get("last_price")
    if last and PRICE_BAND_LOW and PRICE_BAND_HIGH:
        ratio = price / Decimal(last)
        if not Decimal(str(PRICE_BAND_LOW)) <= ratio <= Decimal(str(PRICE_BAND_HIGH)):
            return f"{price} is {ratio:.2f}x this listing's last price of {last}"

    floor = _market_floor(market)
    if floor is not None and price < floor:
        return f"{price} is below {PRICE_MARKET_FLOOR}x the market median for this item"
    return None


def _market_floor(market: dict | None) -> Decimal | None:
    """The lowest price the market makes credible, or None when there is no
    usable reference. The watch's own condition tier is the yardstick when it
    named one; otherwise the cheapest tier is, because a loose copy is the
    weakest thing the item is legitimately sold as."""
    if not market or not PRICE_MARKET_FLOOR or market.get("status") != "ok":
        return None
    tiers = market.get("tiers") or {}
    medians = {}
    for tier, stat in tiers.items():
        median = parse_price((stat or {}).get("median"))
        if median is not None and median > 0:
            medians[tier] = median
    if not medians:
        return None

    hint = market.get("condition_hint")
    reference = medians.get(hint) if hint else None
    if reference is None:
        reference = min(medians.values())
    return reference * Decimal(str(PRICE_MARKET_FLOOR))


def _corroborates(price: Decimal, listing: dict | None) -> bool:
    """Whether this reading confirms an earlier unbelieved one.

    The confirm rule's only way back: a price the bands rejected is believed
    when the very next reading lands within 1% of it — two independent reads
    of the same surprising number is evidence, one is a glitch. There is no
    retroactive flip; the earlier row stays excluded from the aggregates
    forever, and it never becomes the band reference either.
    """
    previous = (listing or {}).get("unconfirmed_price")
    if not previous:
        return False
    previous = Decimal(previous)
    return abs(price - previous) / previous <= CORROBORATION


def public_url(url: str) -> str | None:
    """Why this URL cannot be a page on the public web, or None when it can.

    The half of the guard that is about the network rather than the site: an
    http(s) URL, carrying no credentials, whose host is not a bare container
    name, not localhost or an .internal/.local name, and not a literal address
    in a private, loopback, link-local or otherwise reserved range. This is
    what stops `http://backend:8000/api/…` or `http://169.254.169.254/` from
    being fetched at all.

    No DNS is resolved — this is a pure function. A public name that resolves
    inward is out of scope here and is what the MCP's own --blocked-origins
    covers at the network level (PR 2a).

    Args:
      url: The URL to judge.
    Returns:
      A short reason it is refused, or None.
    """
    if not url or len(url) > MAX_URL:
        return "the URL is empty or absurdly long"

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "only http(s) URLs with a hostname are accepted"
    if parsed.username or parsed.password:
        return "a URL carrying credentials is never a listing page"

    host = parsed.hostname.lower().rstrip(".")
    literal = _address(host)
    if literal is not None:
        return None if literal.is_global else f"{host} is a private or reserved address"
    if "." not in host:
        return f"{host} is not a public hostname"
    if host == "localhost" or host.endswith((".localhost", ".internal", ".local", ".home.arpa")):
        return f"{host} is not a public hostname"
    return None


def url_allowed(url: str, site_base_url: str | None) -> str | None:
    """Why this URL may not be saved or navigated to, or None when it may (S2).

    A listing URL is not a one-off read: it is stored and navigated to on
    every recheck from now on, so accepting one the page chose is accepting a
    standing request. On top of public_url's network rule, the host must sit
    inside the site's own registrable domain — which is the rule that makes
    `http://vision:8100/rescore` unreachable no matter what it resolves to,
    and which, per decision 9, also rejects a genuine redirect to a sister
    domain (ebay.com -> ebay.co.uk). That loss is accepted; it is the same
    rule that closes the SSRF.

    Args:
      url: The URL to judge.
      site_base_url: The site's own base_url, which fixes the allowed domain.
        None means the site is unknown, and nothing is allowed.
    Returns:
      A short reason the URL is refused, or None when it is fine.
    """
    refused = public_url(url)
    if refused:
        return refused

    if not site_base_url:
        return "the site has no base URL to check this against"
    site_host = (urlparse(site_base_url).hostname or "").lower().rstrip(".")
    if not site_host:
        return "the site has no base URL to check this against"
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    domain = _registrable(site_host)
    if host != domain and not host.endswith("." + domain):
        return f"{host} is not part of {domain}"
    return None


def _address(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The host as a literal IP, or None when it is a name."""
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def _registrable(host: str) -> str:
    """The registrable domain of a hostname — what a listing URL must be
    inside. "www.ebay.com" and "ebay.com" both give "ebay.com"."""
    labels = host.split(".")
    if len(labels) > 2 and ".".join(labels[-2:]) in _TWO_LABEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def clip_text(value: str | None, limit: int) -> str | None:
    """One line of display text, capped (S4/S5).

    Model-typed strings are replayed into later scan prompts and into ntfy /
    Discord / webhook bodies. Newlines are what would let a rejection note
    forge a new section in a prompt, and control characters are what would
    let it forge terminal output, so both are flattened here rather than at
    each of the places that render them.

    Args:
      value: The text as the model typed it. None passes through.
      limit: The cap, from this module's MAX_* constants.
    Returns:
      A single clipped line, or None.
    """
    if value is None:
        return None
    cleaned = "".join(
        " " if unicodedata.category(character) in ("Cc", "Cf", "Zl", "Zp") else character
        for character in value
    )
    cleaned = " ".join(cleaned.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"
