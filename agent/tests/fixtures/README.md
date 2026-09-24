# Page fixtures

Captured on **2026-09-16** by navigating the pinned Playwright MCP image
(`mcr.microsoft.com/playwright/mcp` 0.0.79) to each URL and running
`locators.PAGE_EXTRACTOR_JS` on it. Each `*.json` is that extractor's real
output, so `test_locators.py` asserts against pages as marketplaces actually
serve them rather than against a hand-written idea of one.

Re-capture by pointing `PLAYWRIGHT_MCP_URL` at a running MCP and evaluating
`PAGE_EXTRACTOR_JS` on the page; the payload is the file. Expect the visible
prices to have moved on — the tests read the price out of the fixture rather
than hard-coding today's number wherever that is possible.

**Redactions.** Inside the JSON-LD bodies, seller wording and location
(`description`, `address`, `postalCode`, `addressLocality`, `streetAddress`)
are replaced with `[redacted]`, and bulky fields nothing here reads
(`image`, `breadcrumb`, `shippingDetails`, payment methods, return policies,
ratings) are dropped. `gog.json` keeps 3 of its 242 per-country offers.
Everything the locator code actually reads — price paths, availability, meta
keys, candidate text, selectors, ranks and markers — is byte-for-byte what
the browser produced.

| Fixture | Page | What it is here for |
|---|---|---|
| `ebay_bin.json` | eBay, live Buy It Now | the ordinary case: `offers.price` in JSON-LD, `buy_now` set |
| `ebay_out_of_stock.json` | eBay, live listing with no stock | `OutOfStock` + `out_of_stock`, **not** sold — the listing must stay tracked |
| `ebay_sold.json` | eBay, sold while these fixtures were being captured | also reports `OutOfStock`; only the page wording says it ended, hence the `sold` marker |
| `ebay_auction.json` | eBay, auction only | `Offer.price` **is the current bid** — must yield no locator, `markers.auction` set |
| `ebay_foreign_currency.json` | eBay, priced in EUR with a USD approximation | the visible price and the JSON-LD price are different numbers in different currencies |
| `newegg.json` | Newegg product page | no JSON-LD price; the price element is split across child spans, and two elements show the same price |
| `craigslist.json` | Craigslist for-sale post | minimal page that still carries `offers.price`; the post title also contains the price |
| `adafruit.json` | Adafruit product page | the only captured page carrying all three structured forms — JSON-LD, `product:price:amount` and `[itemprop=price]` — so it drives the priority test |
| `gog.json` | GOG store page | JSON-LD whose `offers` is a **list**: `offers[0].price` |
| `allbirds.json` | Allbirds collection page (`/collections/mens`) | no price anywhere the extractor can reach → no locator; also exercises Tailwind's escaped class names |
| `pricecharting.json` | Price Charting guide page | hits the 60-candidate cap, and every candidate is someone else's price |
| `gone_404.json` | a 404 page | nothing at all: no JSON-LD, no meta, no candidates |
| `hashed_classes.json` | a constructed page, captured the same way | emotion/styled-components/JSS class names must never enter a selector; `data-testid` wins instead |
| `mcp_reply_*.txt` | raw `browser_evaluate` replies | the `### Result` framing `parse_result` has to survive, for an object, a string, `undefined` and `null` |

The `static_*.html` files are raw HTML for the browserless rung (`test_static.py`), not
extractor output: small pages, some trimmed from real ones (seller wording redacted as above),
each standing for one thing a plain GET can receive:

| Fixture | What it is here for |
|---|---|
| `static_jsonld.html` | JSON-LD and a `product:price:amount` meta tag both in the raw HTML — either locator reads the price without a browser |
| `static_meta_only.html` | only the meta tag carries the price — only meta candidates are found |
| `static_malformed.html` | one unparseable JSON-LD block before a good one — the bad block must be skipped, not fatal |
| `static_neither.html` | the price exists only in the rendered DOM — the static rung must give way to the browser |
| `static_challenge.html` | a bot-challenge page ("Just a moment...") — states no price, so the check falls through to the browser |

Two shapes are not from the sites the design doc named. Mercari, Reverb and
Back Market all served a challenge page to the headless browser (0 anchors,
title "Just a moment…"), so the hashed-class case is a page constructed to
carry emotion/styled-components/JSS class names and captured through the same
browser. Adafruit and GOG stand in for the meta-only and offers-list shapes
the walled sites would have provided.
