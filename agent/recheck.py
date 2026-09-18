"""Re-reading a tracked listing's price with no model in the loop.

This is the ladder of §4.3, cheapest rung first: a plain HTTP GET when the
listing's locator was proved to work against raw HTML, then one browser page
load and one extractor evaluation, then the listing's own locator, then the
site's consensus locator, then the structured places every schema.org page
puts a price. The LLM is reached only when all of that fails, and the LLM
read then relearns the locator so the next recheck is cheap again.

Two rules run ahead of any price. A page whose only price is a bid is an
auction and is disabled, exactly as the model would. A page that says the
listing sold or ended is disabled too — but, unless its structured data says
so outright, only when the page offers no way to buy it: "out of stock" and
"sold" are indistinguishable in eBay's structured data, and untracking a live
listing is the expensive mistake.

Nothing here raises for a page problem. Every dead end answers "not handled"
and the caller falls back to the agentic recheck, which is also what relearns
the locator. Database failures do propagate — a lost observation is a failed
unit.
"""

import logging
from dataclasses import dataclass

import static
from config import EXPECTED_CURRENCY, LOCATOR_MAX_FAILURES
from database import (
    AsyncSessionLocal,
    clear_static_ok,
    deactivate_listing,
    get_price_context,
    note_locator_failure,
)
from locators import (
    TERMINAL_AVAILABILITY,
    Locator,
    PageReader,
    jsonld_availability,
    method_for,
    read_currency,
    read_with,
    site_consensus,
)
from observations import UnitContext, record_price_check
from validation import Verdict, parse_price, validate_observation

log = logging.getLogger(__name__)

# Tried after the listing's own locator and its site's consensus, in the
# priority of decision 5. A page that states its price in one of these can be
# read even by a listing that has never been learned.
FALLBACK_LOCATORS = (
    Locator("jsonld", "offers.price"),
    Locator("jsonld", "offers[0].price"),
    Locator("meta", "product:price:amount"),
    Locator("meta", "og:price:amount"),
)


@dataclass(frozen=True)
class Outcome:
    """What the deterministic recheck did with one listing.

    handled=False is the only thing the orchestrator must act on: it means
    nothing was recorded and the LLM has to read this page. method and
    transport are for the log line that shows what this path is buying.
    """

    handled: bool
    method: str | None = None
    transport: str = "browser"
    note: str | None = None


NOT_HANDLED = Outcome(handled=False)


async def recheck_deterministic(browser: PageReader, row) -> Outcome:
    """Re-read one tracked listing without the LLM.

    Args:
      browser: The open session's page reader.
      row: One get_listed_items row — the listing, its watch, its site, and
        whatever locator it has learned.
    Returns:
      An Outcome. handled=False means nothing was recorded and the caller
      must run the agentic recheck instead.
    """
    listing_id = int(row["listing_id"])
    url, base_url = row["listing_url"], row["site_base_url"]
    unit = UnitContext(
        watch_id=int(row["watch_id"]),
        item_id=int(row["item_id"]),
        site_id=int(row["site_id"]),
        listing_id=listing_id,
        browser=browser,
    )
    stored = _stored_locator(row)
    context = await get_price_context(listing_id)
    context["condition_hint"] = row["condition_hint"]

    if row["static_ok"] and stored is not None:
        outcome = await _static_rung(unit, listing_id, url, base_url, stored, context)
        if outcome is not None:
            return outcome
        # the browser may still succeed with this very locator, in which case
        # the raw and rendered pages differ for this listing (decision 14)
        log.info(f"Static rung missed for listing {listing_id}; opening the browser")
        context["static_missed"] = True

    if not await browser.navigate(url):
        return NOT_HANDLED
    extract = await browser.extract()
    if extract is None:
        return NOT_HANDLED
    context["markers"] = extract.get("markers") or {}

    gone = _terminal(extract)
    if gone:
        await deactivate_listing(listing_id, gone)
        # method 'locator' = code read the page; which signal decided it is
        # in the log, and status is what the checks log and the UI show
        await _record(unit, listing_id, None, None, "locator", status=gone, in_stock=False)
        return Outcome(True, "locator", note=gone)

    if context["markers"].get("auction") and not context["markers"].get("buy_now"):
        # this listing converted to auction-only since it was saved; a bid is
        # not a price anyone can pay, so it stops being tracked
        await deactivate_listing(listing_id, "auction")
        return Outcome(True, "locator", note="auction")

    return await _read_ladder(unit, listing_id, row, stored, extract, context)


async def _static_rung(
    unit: UnitContext, listing_id: int, url: str, base_url: str, stored: Locator, context: dict
) -> Outcome | None:
    """One GET, no browser. None means "that did not work, open the browser".

    Deliberately incurious: a 404, a redirect, a challenge page, an offer the
    raw HTML says has ended, or a price the bands do not believe all fall
    through rather than being acted on here. The browser confirms every one
    of those itself.
    """
    raw = await static.structured(url, base_url, stored.kind)
    if raw is None:
        return None
    availability = jsonld_availability(raw)
    if availability in TERMINAL_AVAILABILITY:
        return None

    found = read_with(stored.kind, stored.locator, raw)
    verdict = _judge(found, context)
    if verdict is None or not verdict.ok or verdict.anomalous:
        return None

    method = method_for(stored.kind)
    await _record(
        unit,
        listing_id,
        found,
        verdict,
        method,
        in_stock=availability != "outofstock",
        currency=read_currency(stored.kind, stored.locator, raw),
    )
    return Outcome(True, method, transport="static")


async def _read_ladder(
    unit: UnitContext, listing_id: int, row, stored: Locator | None, extract: dict, context: dict
) -> Outcome:
    """Try each locator in turn against the page the browser just read."""
    in_stock = not (
        context["markers"].get("out_of_stock") or jsonld_availability(extract) == "outofstock"
    )

    for locator, source in await _ladder(row, stored):
        found = read_with(locator.kind, locator.locator, extract)
        verdict = _judge(found, context)
        if verdict is None:
            if source == "listing":
                await _note_miss(listing_id)
            continue
        if not verdict.ok:
            log.info(f"Listing {listing_id}: {locator.kind} read refused — {verdict.reason}")
            continue
        if verdict.anomalous:
            # an implausible LOCATOR read is thrown away rather than recorded:
            # the LLM re-reads this same page now, and that read is the
            # observation (§4.3, the confirm rule)
            log.warning(f"Listing {listing_id}: {locator.kind} read {found!r} — {verdict.reason}")
            return NOT_HANDLED

        if context.get("static_missed") and source == "listing":
            await clear_static_ok(listing_id)
        method = method_for(locator.kind)
        await _record(
            unit,
            listing_id,
            found,
            verdict,
            method,
            in_stock=in_stock,
            currency=read_currency(locator.kind, locator.locator, extract),
        )
        return Outcome(True, method)

    return NOT_HANDLED


def _stored_locator(row) -> Locator | None:
    """The listing's own learned locator, if it still has one."""
    kind, locator = row["locator_kind"], row["price_locator"]
    return Locator(kind, locator) if kind and locator else None


async def _ladder(row, stored: Locator | None) -> list[tuple[Locator, str]]:
    """The locators to try, in order, each tagged with where it came from.

    The listing's own learned locator first, then the one most of the site's
    other listings agree on — a marketplace serves one page template, so a
    neighbour's locator is the best guess for a listing that has never been
    learned or whose own locator just broke — then the structured places
    every schema.org page puts a price.
    """
    ladder: list[tuple[Locator, str]] = []
    if stored is not None:
        ladder.append((stored, "listing"))

    async with AsyncSessionLocal() as session:
        consensus = await site_consensus(session, int(row["site_id"]))
    if consensus is not None and consensus != stored:
        ladder.append((consensus, "site"))

    seen = {stored, consensus}
    ladder.extend((fallback, "fallback") for fallback in FALLBACK_LOCATORS if fallback not in seen)
    return ladder


def _terminal(extract: dict) -> str | None:
    """ "sold", "ended", or None — is this listing over?

    Structured data is believed outright when it states a terminal state.
    Wording is not: a live listing with no stock and a listing that actually
    sold both report schema.org/OutOfStock on eBay, so only the page's own
    words separate them — and those words appear in recommendation rails too.
    Requiring the absence of any Buy It Now / Add to cart affordance is what
    keeps a neighbour's "SOLD" badge from untracking a live listing. Anything
    ambiguous by that rule is left to the LLM, which the recheck prompt
    already tells it to resolve.
    """
    if jsonld_availability(extract) in TERMINAL_AVAILABILITY:
        return "sold"
    markers = extract.get("markers") or {}
    if markers.get("buy_now"):
        return None
    if markers.get("ended"):
        return "ended"
    if markers.get("sold"):
        return "sold"
    return None


def _judge(found: str | None, context: dict) -> Verdict | None:
    """Parse and validate one reading, or None when nothing was read."""
    if found is None:
        return None
    price = parse_price(found)
    if price is None:
        return None
    market = context.get("market")
    return validate_observation(
        price,
        EXPECTED_CURRENCY,
        listing=context,
        market={**market, "condition_hint": context.get("condition_hint")} if market else None,
        markers=context.get("markers"),
    )


async def _note_miss(listing_id: int) -> None:
    """Count a miss by the listing's own locator, clearing it once it has
    missed too often."""
    if await note_locator_failure(listing_id, LOCATOR_MAX_FAILURES):
        log.info(f"Listing {listing_id} will relearn its locator on the next LLM read")


async def _record(
    unit: UnitContext,
    listing_id: int,
    found: str | None,
    verdict: Verdict | None,
    method: str,
    *,
    status: str = "ok",
    in_stock: bool | None = None,
    currency: str | None = None,
) -> None:
    """Write the observation through the one writer.

    currency comes from the page when its structured data states one beside
    the price; otherwise the instance's expected currency is the only
    available answer, and a listing that has switched currency reads as an
    anomaly and goes to the LLM, which reports the currency explicitly.
    """
    quoted = currency or EXPECTED_CURRENCY
    async with AsyncSessionLocal() as session:
        await record_price_check(
            session,
            unit,
            listing_id=listing_id,
            price=parse_price(found) if found is not None else None,
            currency=quoted,
            in_stock=in_stock,
            status=status,
            method=method,
            confirmed=verdict.confirmed if verdict else True,
            notifiable=quoted == EXPECTED_CURRENCY and (verdict.notifiable if verdict else True),
        )
