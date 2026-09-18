"""Per-listing price locators: where on a page the price lives.

The only moment we hold a confirmed price AND the page it came from is when
the LLM reports one. At that moment code — never the model — reads the page,
finds what holds that exact number, and stores the shortest path back to it
on the listing. Every later recheck replays that path with no model in the
loop (agent/recheck.py).

Two fixed JS constants do the browser-side work. PAGE_EXTRACTOR_JS returns
one compact JSON object per page — structured data, price-shaped leaf
elements, and the auction/sold/ended markers — which is ~2 KB where the page
is ~800 KB, and which the model never sees. RUN_LOCATOR_JS replays one
stored locator so a freshly derived one can be verified before it is
trusted. The model cannot author either: a hallucinated selector, or one a
hostile page steered it towards, is exactly what this module exists to avoid.

Everything here is a pure function over that JSON except site_consensus,
which is one GROUP BY, and PageReader, which wraps the open browser session.
"""

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal

from database import Listings
from sqlalchemy import func, select
from validation import CURRENCY_CODES, parse_price

log = logging.getLogger(__name__)

# The four locator kinds, in the order the ladder tries them (decision 5:
# structured data first, the visible element last). A kind is stored on
# listings.locator_kind and recorded on every price check as its method,
# except 'css', whose checks record 'locator' — the contract's word for "a
# replayed element path" (§4.3).
LOCATOR_KINDS = ("jsonld", "meta", "microdata", "css")

# What a jsonld locator is a path into. A block may be a bare object, a list
# of them, or a {"@graph": [...]} wrapper, and marketplaces move a product
# between those shapes without changing the path to its price — so the path
# is applied to every root a page offers and the first hit wins, rather than
# being pinned to one script tag's index.
_PATH_STEP = re.compile(r"([^.\[\]]+)|\[(\d+)\]")

# PAGE_EXTRACTOR_JS ranks each candidate 0-4 by how its selector was derived
# (an itemprop, a test id, an id, an aria-label, a counted path). Anything
# without a rank sorts last.
UNRANKED = 9


PAGE_EXTRACTOR_JS = r"""() => {
  const MAX_CANDIDATES = 60;
  const MAX_TEXT = 160;
  const MAX_CANDIDATE_TEXT = 48;
  const MAX_JSONLD = 200000;
  // Never text: script and style bodies are full of currency-formatted
  // numbers, and SVG text is a chart axis, not a price on offer.
  const SKIP_TAGS = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'HEAD', 'TITLE']);
  const SKIP_SELECTOR = 'script, style, noscript, template, head, svg';
  // A class is "stable" unless it looks machine-generated: emotion (css-1x9kz3q),
  // styled-components (sc-bdVaJa), JSS (jss42), CSS-module hashes (_xyz9k4) and
  // bare hex blobs all change on the next deploy, so a path built from one is a
  // locator with a shelf life of days.
  const HASHED = new RegExp(
    '^(css-[a-z0-9]{4,}|sc-[A-Za-z0-9]{5,}|jss\\d+|_[A-Za-z0-9]{4,}|[A-Za-z]{0,3}[0-9a-f]{6,})$'
  );
  // Same idea for ids: a digit run or a framework prefix is this render's id,
  // not this page template's.
  const GENERATED_ID = /\d{4,}|[0-9a-f]{8,}|^(:r|ember|react-|radix-|headlessui-|mui-)/i;
  const CODES = '\\b(?:USD|EUR|GBP|JPY|CAD|AUD|NZD|CHF)\\b';
  const SYMBOL = '(?:[$£€¥₹]|' + CODES + ')';
  // a currency-formatted number, with the marker on either side of it
  const MONEY = new RegExp(
    SYMBOL + '\\s*\\d[\\d.,\\s]*' + '|' + '\\d[\\d.,]*\\s*' + SYMBOL
  );
  const PRICE_PROPS = new Set([
    'price', 'lowPrice', 'highPrice', 'priceCurrency', 'availability', 'itemCondition',
  ]);

  const text = (el) => (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, MAX_TEXT);
  const esc = (v) => v.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const stable = (c) => c && c.length <= 40 && !HASHED.test(c);

  const unique = (sel, el) => {
    try {
      const found = document.querySelectorAll(sel);
      return found.length === 1 && found[0] === el;
    } catch (e) {
      return false;
    }
  };

  const step = (el) => {
    let out = el.tagName.toLowerCase();
    for (const c of [...el.classList].filter(stable).slice(0, 2)) out += '.' + CSS.escape(c);
    const parent = el.parentElement;
    if (parent) {
      const siblings = [...parent.children].filter((c) => c.tagName === el.tagName);
      if (siblings.length > 1) out += ':nth-of-type(' + (siblings.indexOf(el) + 1) + ')';
    }
    return out;
  };

  // Shortest path that uniquely reaches the element, at most four levels deep:
  // deeper than that and the path is describing the page's layout rather than
  // the element, and any reflow breaks it.
  const path = (el) => {
    const parts = [];
    let node = el;
    for (let depth = 0; depth < 4 && node && node !== document.body; depth++) {
      parts.unshift(step(node));
      const sel = parts.join(' > ');
      if (unique(sel, el)) return sel;
      node = node.parentElement;
    }
    return null;
  };

  // Rank is how the selector was derived, lowest first, and it is what
  // decides between two elements on the page showing the same price: an
  // element the site itself labelled `price` is the price, while a path
  // through :nth-of-type is only where something happened to sit today.
  const selectorFor = (el) => {
    if (el.getAttribute('itemprop') === 'price' && unique('[itemprop="price"]', el)) {
      return { selector: '[itemprop="price"]', rank: 0 };
    }
    for (const attr of ['data-testid', 'data-test-id', 'data-test', 'data-qa']) {
      const value = el.getAttribute(attr);
      if (value) {
        const sel = '[' + attr + '="' + esc(value) + '"]';
        if (unique(sel, el)) return { selector: sel, rank: 1 };
      }
    }
    if (el.id && !GENERATED_ID.test(el.id) && el.id.length <= 40) {
      const sel = '#' + CSS.escape(el.id);
      if (unique(sel, el)) return { selector: sel, rank: 2 };
    }
    const label = el.getAttribute('aria-label');
    if (label && label.length <= 60) {
      const sel = '[aria-label="' + esc(label) + '"]';
      if (unique(sel, el)) return { selector: sel, rank: 3 };
    }
    const derived = path(el);
    return derived ? { selector: derived, rank: 4 } : null;
  };

  const jsonld = [];
  for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    const body = (script.textContent || '').trim();
    if (body && body.length <= MAX_JSONLD) jsonld.push(body);
  }

  // A whitelist, not a pattern: "price" appears in meta keys that have
  // nothing to do with this product (smartbanner:price says an app is FREE),
  // and an unknown key could never be selected as a locator anyway.
  const META_KEYS = new Set([
    'product:price:amount', 'product:price:currency', 'product:availability',
    'og:price:amount', 'og:price:currency', 'og:availability',
    'twitter:data1', 'price', 'availability',
  ]);
  const meta = {};
  for (const tag of document.querySelectorAll('meta[property], meta[name]')) {
    const key = (tag.getAttribute('property') || tag.getAttribute('name') || '').toLowerCase();
    const content = tag.getAttribute('content');
    if (content && META_KEYS.has(key) && !(key in meta)) meta[key] = content.slice(0, MAX_TEXT);
  }

  const microdata = [];
  for (const el of document.querySelectorAll('[itemprop]')) {
    const prop = el.getAttribute('itemprop');
    if (!PRICE_PROPS.has(prop)) continue;
    const found = selectorFor(el);
    microdata.push({
      itemprop: prop,
      content: el.getAttribute('content'),
      text: text(el),
      selector: found ? found.selector : null,
    });
    if (microdata.length >= MAX_CANDIDATES) break;
  }

  // Elements that hold a price and almost nothing else. Not strictly leaves:
  // Newegg and eBay both split a price across child spans (dollars, cents,
  // currency), so the element that actually states "$1,199.99" has children.
  // The shape that matters is "small and short" — at most a handful of
  // descendants, and text no longer than a price with its currency — which
  // keeps out the card, the section and the page that also "contain" it.
  const matched = [];
  for (const el of document.querySelectorAll('*')) {
    // a <script> body is full of currency-formatted numbers and is not text
    if (SKIP_TAGS.has(el.tagName) || el.closest(SKIP_SELECTOR)) continue;
    if (el.getElementsByTagName('*').length > 3) continue;
    const value = text(el);
    if (!value || value.length > MAX_CANDIDATE_TEXT || !MONEY.test(value)) continue;
    matched.push({ el: el, text: value });
  }

  // A pure wrapper repeats its child's text verbatim; keep the inner element,
  // which is the more precise locator. A split price differs from every child
  // it is assembled from, so it survives this.
  const candidates = [];
  for (const entry of matched) {
    const wrapped = matched.some(
      (other) => other !== entry && entry.el.contains(other.el) && other.text === entry.text
    );
    if (wrapped) continue;
    const found = selectorFor(entry.el);
    // an element no path uniquely reaches can never become a locator
    if (!found) continue;
    candidates.push({ text: entry.text, selector: found.selector, rank: found.rank });
    if (candidates.length >= MAX_CANDIDATES) break;
  }

  // Markers are read from the main region when the page marks one out: a
  // recommendations rail full of other people's auctions must not make this
  // listing an auction.
  //
  // out_of_stock is deliberately its own marker rather than part of sold.
  // Measured on eBay: a live listing with no stock and a listing that has
  // actually sold BOTH report schema.org/OutOfStock, so structured data
  // cannot tell them apart and the page's own wording has to. Folding the
  // two together would untrack a listing that is still for sale, which is
  // why sold only matches terminal wording — including eBay's bare "SOLD"
  // line, hence the multiline flag — and why the ladder additionally
  // requires buy_now to be absent before it acts (agent/recheck.py).
  const main = document.querySelector('main') || document.body;
  const body = ((main && main.innerText) || '').slice(0, 200000);
  const AUCTION = new RegExp(
    'current bid|starting bid|opening bid|\\d+\\s+bids?\\b|place\\s*bid|bid now|reserve not met',
    'i'
  );
  const BUY_NOW = /buy it now|buy now|add to cart|add to bag|add to basket/i;
  const SOLD = new RegExp(
    '\\bitem sold on\\b|\\bthis (item|listing) (has been |was |is )?sold\\b'
      + '|\\bthis listing sold\\b|\\bsold for\\b|\\bwinning bid\\b|^\\s*sold\\s*$',
    'im'
  );
  const ENDED = new RegExp(
    'listing (has )?ended|auction (has )?ended|bidding (has )?ended'
      + '|this listing was ended|no longer available',
    'i'
  );
  const OUT_OF_STOCK = /out of stock|sold out|currently unavailable|no longer in stock/i;
  const markers = {
    auction: AUCTION.test(body),
    buy_now: BUY_NOW.test(body),
    sold: SOLD.test(body),
    ended: ENDED.test(body),
    out_of_stock: OUT_OF_STOCK.test(body),
  };

  return {
    url: location.href,
    title: (document.title || '').slice(0, MAX_TEXT),
    jsonld: jsonld,
    meta: meta,
    microdata: microdata,
    candidates: candidates,
    markers: markers,
  };
}"""


# Replays one stored locator against the live page. The locator arrives as a
# json.dumps string literal (see run_locator_js), so quotes, backslashes and
# U+2028 are escaped and the value is data — it lands in querySelector() or a
# JSON path walk, never in a position the browser would execute. A hostile
# locator can at worst select the wrong element, which the exact-match check
# in learn_locator then refuses.
RUN_LOCATOR_JS = r"""() => {
  const KIND = __KIND__;
  const LOCATOR = __LOCATOR__;

  if (KIND === 'meta') {
    const tag = document.querySelector(
      'meta[property="' + LOCATOR.replace(/["\\]/g, '\\$&') + '"], ' +
      'meta[name="' + LOCATOR.replace(/["\\]/g, '\\$&') + '"]'
    );
    return tag ? tag.getAttribute('content') : null;
  }

  if (KIND === 'jsonld') {
    const walk = (root, steps) => {
      let node = root;
      for (const key of steps) {
        if (node === null || typeof node !== 'object') return undefined;
        node = node[key];
      }
      return node;
    };
    const steps = [];
    for (const m of LOCATOR.matchAll(/([^.\[\]]+)|\[(\d+)\]/g)) {
      steps.push(m[2] === undefined ? m[1] : Number(m[2]));
    }
    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
      let block;
      try {
        block = JSON.parse(script.textContent || '');
      } catch (e) {
        continue;
      }
      const roots = [block];
      if (Array.isArray(block)) roots.push(...block);
      if (block && typeof block === 'object' && Array.isArray(block['@graph'])) {
        roots.push(...block['@graph']);
      }
      for (const root of roots) {
        const found = walk(root, steps);
        if (found !== undefined && found !== null && typeof found !== 'object') {
          return String(found);
        }
      }
    }
    return null;
  }

  // 'css' and 'microdata' are both element paths
  let el;
  try {
    el = document.querySelector(LOCATOR);
  } catch (e) {
    return null;
  }
  if (!el) return null;
  const content = el.getAttribute('content');
  return content !== null ? content : (el.textContent || '').replace(/\s+/g, ' ').trim();
}"""


def run_locator_js(kind: str, locator: str) -> str:
    """RUN_LOCATOR_JS with one locator baked in as a JSON string literal.

    json.dumps is the whole safety argument: it escapes quotes, backslashes
    and the line terminators JS parses but JSON does not (U+2028/U+2029), so
    whatever the locator contains arrives as one string constant instead of
    as code. The kind travels the same way rather than being interpolated as
    a bare word.

    Args:
      kind: One of LOCATOR_KINDS — which reader the JS should use.
      locator: The stored locator: a CSS selector, a meta key, or a JSON path.
    Returns:
      The JS function source to hand to browser_evaluate.
    """
    if kind not in LOCATOR_KINDS:
        raise ValueError(f"unknown locator kind {kind!r}")
    return RUN_LOCATOR_JS.replace("__KIND__", json.dumps(kind)).replace(
        "__LOCATOR__", json.dumps(locator)
    )


def reply_text(result: object) -> str:
    """One MCP tool result as text.

    The langchain adapter hands back whatever the server sent: a plain string
    for a simple tool, but a list of content blocks for browser_evaluate, and
    a (content, artifact) tuple when the server attaches one. The blocks are
    pydantic TextContent objects over the wire and dicts when something has
    round-tripped them through JSON, so both are read.

    Args:
      result: The value a StructuredTool.ainvoke returned.
    Returns:
      The concatenated text, ready for parse_result.
    """
    if isinstance(result, str):
        return result
    if isinstance(result, tuple):
        result = result[0]
    if isinstance(result, list):
        parts = []
        for block in result:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(getattr(block, "text", "") or ""))
        return "\n".join(parts)
    return str(result)


def parse_result(text: str) -> object:
    """The JSON value out of a Playwright MCP browser_evaluate reply.

    The server answers with a "### Result" section holding the JSON return
    value, followed by a "### Ran Playwright code" section echoing what it
    executed. That framing is the MCP image's, not a protocol guarantee —
    hence the pinned image tag and test_locators.py's captured sample: if a
    future image reworks the wrapper, this is the one function that has to
    notice.

    Args:
      text: The raw text content of the browser_evaluate tool result.
    Returns:
      The decoded JSON value, or None when the reply carries no Result
      section or its body does not parse (an undefined return, an error page
      the caller handles as "no read").
    """
    marker = "### Result"
    start = text.find(marker)
    if start == -1:
        return None
    body = text[start + len(marker) :]
    end = body.find("\n### ")
    if end != -1:
        body = body[:end]
    body = body.strip()
    # the server fences the value on some paths and not others
    if body.startswith("```"):
        body = body.split("\n", 1)[-1].rsplit("```", 1)[0]
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def _walk(root: object, steps: list) -> object:
    """Follow a parsed JSON path into one root, or None if it does not fit."""
    node = root
    for key in steps:
        if isinstance(key, int):
            if not isinstance(node, list) or not -len(node) <= key < len(node):
                return None
            node = node[key]
        else:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
    return node


def _path_steps(locator: str) -> list:
    """ "offers[0].price" -> ["offers", 0, "price"]."""
    return [int(index) if index else key for key, index in _PATH_STEP.findall(locator)]


def _roots(block: object) -> list:
    """Every object a JSON-LD path may be applied to within one script body."""
    roots: list = [block]
    if isinstance(block, list):
        roots.extend(block)
    elif isinstance(block, dict) and isinstance(block.get("@graph"), list):
        roots.extend(block["@graph"])
    return roots


def _jsonld_blocks(extract: dict) -> list:
    """Parsed JSON-LD script bodies; unparseable ones are skipped, because a
    page with one broken block usually still carries a good one."""
    blocks = []
    for body in extract.get("jsonld") or []:
        try:
            blocks.append(json.loads(body))
        except json.JSONDecodeError, TypeError:
            continue
    return blocks


def read_with(kind: str, locator: str, extract: dict) -> str | None:
    """Replay one locator against an extractor payload.

    This is the read half of the recheck ladder (§4.3) and the mirror of what
    RUN_LOCATOR_JS does in the browser: same locator, same answer, no second
    page evaluation. A locator that no longer resolves returns None, which is
    what bumps listings.locator_failures.

    Args:
      kind: One of LOCATOR_KINDS.
      locator: The stored locator for that kind.
      extract: A PAGE_EXTRACTOR_JS payload.
    Returns:
      The raw text found (still unparsed — the caller runs parse_price on it),
      or None when this page does not hold it.
    """
    if kind == "meta":
        value = (extract.get("meta") or {}).get(locator)
        return str(value) if value is not None else None

    if kind == "jsonld":
        steps = _path_steps(locator)
        if not steps:
            return None
        for block in _jsonld_blocks(extract):
            for root in _roots(block):
                found = _walk(root, steps)
                if found is not None and not isinstance(found, (dict, list)):
                    return str(found)
        return None

    if kind == "microdata":
        for entry in extract.get("microdata") or []:
            if entry.get("selector") == locator:
                content = entry.get("content")
                return str(content) if content is not None else (entry.get("text") or None)
        return None

    if kind == "css":
        for entry in extract.get("candidates") or []:
            if entry.get("selector") == locator:
                return entry.get("text") or None
        return None

    return None


def read_currency(kind: str, locator: str, extract: dict) -> str | None:
    """The currency stated beside the price this locator points at.

    A locator points at a number, not at what the number is in — and a
    marketplace really does serve both (eBay states a EUR asking price and a
    USD approximation on the same page). Structured data always names its
    currency in a sibling field, so it is read from there; a visible element
    is read only when its own text spells out an ISO code, as "EUR 12,999.00"
    does. A bare symbol is not enough — "$" is four currencies — and yields
    None, leaving the caller to assume the instance's expected currency.

    Args:
      kind: The locator's kind.
      locator: The locator.
      extract: The payload it was read from.
    Returns:
      A three-letter code, or None when the page does not state one.
    """
    if kind == "jsonld":
        steps = _path_steps(locator)
        if steps and steps[-1] == "price":
            sibling = _join_steps([*steps[:-1], "priceCurrency"])
            return _currency_code(read_with(kind, sibling, extract))
        return None

    if kind == "meta":
        sibling = locator.replace(":amount", ":currency")
        return _currency_code(read_with(kind, sibling, extract)) if sibling != locator else None

    if kind == "microdata":
        for entry in extract.get("microdata") or []:
            if entry.get("itemprop") == "priceCurrency":
                return _currency_code(entry.get("content") or entry.get("text"))
        return None

    return _currency_code(read_with(kind, locator, extract))


def _join_steps(steps: list) -> str:
    """The inverse of _path_steps: ["offers", 0, "price"] -> "offers[0].price"."""
    out = ""
    for step in steps:
        if isinstance(step, int):
            out += f"[{step}]"
        else:
            out += step if not out else f".{step}"
    return out


def _currency_code(value: object) -> str | None:
    """A known three-letter currency code out of whatever the page said."""
    if not isinstance(value, str):
        return None
    for token in re.findall(r"[A-Za-z]{3}", value):
        if token.upper() in CURRENCY_CODES:
            return token.upper()
    return None


def jsonld_availability(extract: dict) -> str | None:
    """What this page's structured data says the offer's state is.

    The authoritative availability signal, and the reason the ladder can act
    on "gone" without the LLM: schema.org separates SoldOut and Discontinued
    (terminal — the listing is over) from OutOfStock, BackOrder and PreOrder
    (the seller has none today, but the listing is still a live offer). The
    visible page blurs the two; this does not.

    Args:
      extract: A PAGE_EXTRACTOR_JS payload.
    Returns:
      The bare schema.org term ("InStock", "SoldOut", …) lower-cased, or None
      when the page states none.
    """
    for block in _jsonld_blocks(extract):
        for root in _roots(block):
            offers = root.get("offers") if isinstance(root, dict) else None
            for offer in offers if isinstance(offers, list) else [offers]:
                if not isinstance(offer, dict):
                    continue
                value = offer.get("availability")
                if isinstance(value, str) and value:
                    return value.rsplit("/", 1)[-1].strip().lower()
    return None


# The two availability terms that end a listing, as opposed to merely
# emptying it. Anything else the page states leaves it live.
TERMINAL_AVAILABILITY = ("soldout", "discontinued")


@dataclass(frozen=True)
class Locator:
    """A learned place a price lives on one listing's page."""

    kind: str
    locator: str


def _jsonld_price_paths(block: object, prefix: str = "") -> list[tuple[str, object]]:
    """Every (path, value) under an offer's price key in one JSON-LD root.

    Only `price` inside an `offers` object counts. A bare top-level `price`,
    `lowPrice`/`highPrice` on an AggregateOffer, and anything under a nested
    Product recommendation are all prices of something other than "what this
    page sells right now".
    """
    found: list[tuple[str, object]] = []
    if isinstance(block, dict):
        for key, value in block.items():
            path = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
            if key == "price" and prefix.startswith("offers"):
                found.append((path, value))
            elif key == "offers":
                found.extend(_jsonld_price_paths(value, path))
    elif isinstance(block, list):
        for index, value in enumerate(block):
            found.extend(_jsonld_price_paths(value, f"{prefix}[{index}]"))
    return found


def select_locator(extract: dict, confirmed_price: Decimal) -> Locator | None:
    """Pick where on this page the confirmed price lives — code's job, not the
    model's (decision 5).

    Every place the page states a price is parsed with the same parse_price
    the validator uses, and only those equal to the price the model confirmed
    survive. Among the survivors the order is structured data first, visible
    element last: a JSON-LD offer, then product:price:amount, then
    [itemprop=price], then the best candidate element. Structured data wins
    because it exists for crawlers and therefore survives restyles — and, for
    the static probe, because it is in the raw HTML. Ties go to DOM order.

    An auction page yields nothing at all. eBay states the CURRENT BID in
    Offer.price on an auction-only listing, so a locator learned there would
    faithfully record a number that is not a price anyone can pay (§4.3).

    Args:
      extract: A PAGE_EXTRACTOR_JS payload from the page the price was read on.
      confirmed_price: The price the LLM just confirmed, already validated.
    Returns:
      The locator to verify and store, or None when nothing on the page holds
      that exact number — in which case the next LLM read tries again.
    """
    markers = extract.get("markers") or {}
    if markers.get("auction") and not markers.get("buy_now"):
        return None

    for block in _jsonld_blocks(extract):
        for root in _roots(block):
            for path, value in _jsonld_price_paths(root):
                if parse_price(value) == confirmed_price:
                    return Locator("jsonld", path)

    for key, value in (extract.get("meta") or {}).items():
        if (
            key in ("product:price:amount", "og:price:amount")
            and parse_price(value) == confirmed_price
        ):
            return Locator("meta", key)

    for entry in extract.get("microdata") or []:
        if entry.get("itemprop") != "price" or not entry.get("selector"):
            continue
        raw = entry.get("content")
        if raw is None:
            raw = entry.get("text")
        if parse_price(raw) == confirmed_price:
            return Locator("microdata", entry["selector"])

    # Among elements showing the same price, the one the site labelled as the
    # price beats one reached by counting siblings — rank first, DOM order to
    # break a tie. A "similar items" rail quoting the same number is the case
    # this exists for.
    matches = [
        (entry.get("rank", UNRANKED), order, entry["selector"])
        for order, entry in enumerate(extract.get("candidates") or [])
        if entry.get("selector") and parse_price(entry.get("text")) == confirmed_price
    ]
    if matches:
        return Locator("css", min(matches)[2])

    return None


def method_for(kind: str) -> str:
    """The price_checks.method a read through this locator kind records.

    'css' is the only kind whose name is not the method: the contract calls a
    replayed element path 'locator', while the three structured-data kinds
    say which structure they came out of (§4.3).
    """
    return "locator" if kind == "css" else kind


async def site_consensus(session, site_id: int) -> Locator | None:
    """The locator most of this site's listings agree on.

    A marketplace serves one page template, so a listing with no locator of
    its own — or one that just broke — should try its neighbours' before
    spending an LLM call. It also means one relearn after a site redesign
    fixes the whole site rather than one listing at a time. Computed at read
    time from the listings themselves; there is no consensus table to keep in
    step.

    Args:
      session: An open AsyncSession.
      site_id: The site whose listings to poll.
    Returns:
      The most common verified (kind, locator) on the site, or None when the
      site has no verified locators yet.
    """
    stmt = (
        select(Listings.locator_kind, Listings.price_locator, func.count().label("n"))
        .where(Listings.site_id == site_id)
        .where(Listings.locator_verified_at.is_not(None))
        .where(Listings.price_locator.is_not(None))
        .group_by(Listings.locator_kind, Listings.price_locator)
        .order_by(func.count().desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None or row.locator_kind not in LOCATOR_KINDS:
        return None
    return Locator(row.locator_kind, row.price_locator)


class PageReader:
    """The orchestrator's handle on the open browser session.

    Built once per run from the MCP tool map and carried on UnitContext, so a
    tool can read the page the model is looking at without the model ever
    naming a URL, a selector or a script. Every method answers None rather
    than raising for a page problem — a blocked page is an outcome the
    recheck ladder handles, not an error the run should die on.
    """

    def __init__(self, navigate, evaluate) -> None:
        """
        Args:
          navigate: The MCP browser_navigate StructuredTool.
          evaluate: The MCP browser_evaluate StructuredTool.
        """
        self._navigate = navigate
        self._evaluate = evaluate

    async def _run(self, function: str) -> object:
        try:
            result = await self._evaluate.ainvoke({"function": function})
        except Exception as e:
            log.warning(f"browser_evaluate failed: {e}")
            return None
        return parse_result(reply_text(result))

    async def navigate(self, url: str) -> bool:
        """Go to a URL. False when the navigation itself failed."""
        try:
            await self._navigate.ainvoke({"url": url})
        except Exception as e:
            log.warning(f"browser_navigate to {url} failed: {e}")
            return False
        return True

    async def extract(self) -> dict | None:
        """Run PAGE_EXTRACTOR_JS on the current page."""
        payload = await self._run(PAGE_EXTRACTOR_JS)
        return payload if isinstance(payload, dict) else None

    async def read_locator(self, kind: str, locator: str) -> str | None:
        """Replay one locator against the live page — the verify step's read."""
        value = await self._run(run_locator_js(kind, locator))
        return None if value is None else str(value)
