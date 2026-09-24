"""Database-writing tools exposed to the LLM agent.

Each function's docstring doubles as the tool description the LLM sees, so
they are written as instructions to the model — keep them accurate and
imperative when editing. Errors are returned as strings (not raised) so the
agent can read them and react.

Which watch, item and site a call is about — and on a recheck, which
listing — is never a tool argument. The orchestrator binds it per unit as a
UnitContext on the run config, and langchain hands every tool its runtime
through the keyword-only `runtime` parameter, which never appears in the
schema the model sees. The model has no id to type, so it cannot attach a
price to the wrong listing.

The page the model is reading is untrusted, so what it types is too. Every
URL is checked against the site's own domain before it is stored or fetched,
every free-text field is capped and flattened to one line before it reaches a
later prompt or a notification body, and every price is judged for
plausibility before it can become a target-hit push (agent/validation.py).

save_price_check does one more thing the model never sees: at the moment it
confirms a price, code reads the page it is on and learns where that price
lives, so later rechecks need no model at all (agent/locators.py)."""

import logging
import re
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlparse

import httpx
import jobs as job_queue
import static
from config import VISION_SIDECAR_URL, VISION_TIMEOUT_SECONDS
from database import (
    DISABLE_REASONS,
    AsyncSessionLocal,
    ListingChecks,
    Listings,
    MarketPrices,
    VisionScans,
    Watches,
    enqueue_new_listing,
    get_price_context,
    save_locator,
)
from langchain.tools import ToolRuntime
from locators import select_locator
from observations import UnitContext, UnitMismatch, assert_writable, record_price_check
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from validation import (
    MAX_NOTES,
    MAX_REASON,
    MAX_SUMMARY,
    MAX_TITLE,
    clip_text,
    parse_price,
    public_url,
    url_allowed,
    validate_observation,
)

log = logging.getLogger(__name__)

PRICE_STATUSES = ("ok", "sold", "ended", "error")
AUTHENTICITY_READS = ("looks_authentic", "suspect", "unsure")


def unit_of(runtime: ToolRuntime) -> UnitContext:
    """The unit this call belongs to. Carried on config["configurable"] rather
    than the runtime's `context` slot: langchain serializes the injected
    runtime on every call, and a non-None context there trips a pydantic
    serializer warning each time — configurable rides along untouched."""
    return runtime.config["configurable"]["unit"]


def _refuse_url(url: str, unit: UnitContext, field: str = "url") -> str | None:
    """The model-facing refusal for a URL that may not be used, or None.

    The reason is spelled out rather than generic because the model can act
    on it: "not part of ebay.com" tells it to go back to the listing page it
    was actually on, which is usually exactly what happened.
    """
    refused = url_allowed(url, unit.site_base_url)
    if refused is None:
        return None
    return (
        f"Error: {field} must be a listing page on this site — {refused}. Use the URL "
        f"of the page you actually visited."
    )


async def save_listing(
    url: str,
    title: str,
    match_score: int,
    match_summary: str,
    site_sku: str | None = None,
    price: float | None = None,
    currency: str = "USD",
    *,
    runtime: ToolRuntime,
) -> int | str:
    """
    Save a listing that matches the user's selected criteria to the database and return its
    listing_id. It is saved under the watch, item and site this search is for — those are
    already known here, so you never pass them.

    Args:
      url: The full http(s) URL of the listing page you actually visited. It must be a
        page on THIS site - a URL on any other domain is refused, because this URL is
        revisited on every future price check.
      title: The listing's actual title as shown on the site
      site_sku: If a SKU is present on the site, record it here
      match_score: How well this listing fits the requested criteria, as an integer 0-100
        (examples: 67, 4, 42). Be calibrated - do not default to high.
      match_summary: One short line justifying the score, e.g. "dry battery ok, cart only,
        authentic per photos". Keep it to one line; long text is truncated.
      price: REQUIRED when this save replaces a tracked listing (right after
        disable_listing with reason "replaced"): the numeric price shown on the page, no
        currency symbol, for a listing you can buy now. Whenever you pass it, it is
        recorded as this listing's price, so do NOT also call save_price_check for it.
        On any other save you may leave it out and call save_price_check afterwards.
      currency: The three-letter code of that price's currency, e.g. "USD"
    Returns:
      One of these five:
        listing_id: The internal ID for the listing. If it is already tracked, returns the
          existing listing_id instead.
        SKIPPED: A string starting with "SKIPPED:" — this listing is already known and no
          longer tracked (it sold, ended, or the user untracked it). Record nothing for it
          and do not log it as a rejection either; move on.
        SLOTS FULL: A string starting with "SLOTS FULL:" — every slot of this watch is
          taken, or the replacement you asked for is not allowed; the reason is spelled
          out. Nothing was saved and nothing changed. Do not log the candidate as a
          rejection; move on.
        REFUSED: A string starting with "REFUSED:" — this listing's photos crossed the
          user's authenticity auto-reject threshold (see check_images). Do not retry;
          call log_listing_check with reason "authenticity" instead and move on.
        Error: Any other string — what was wrong with the call, or what failed while
          saving
    """
    unit = unit_of(runtime)
    watch_id, item_id, site_id = unit.watch_id, unit.item_id, unit.site_id
    refused = _refuse_url(url, unit)
    if refused:
        return refused
    if not 0 <= match_score <= 100:
        return f"Error: match_score must be an integer from 0 to 100, got {match_score}"
    if price is not None and price <= 0:
        return "Error: price must be the real price shown on the page, greater than zero"
    currency = currency.upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        return f"Error: currency must be a three-letter code like USD, got {currency!r}"
    # both reach a notification body and the next hunt's prompt
    title = clip_text(title, MAX_TITLE)
    match_summary = clip_text(match_summary, MAX_SUMMARY)
    parsed = parse_price(price) if price is not None else None

    log.info(f"Saving listing for item {item_id} on site {site_id} (watch {watch_id})")

    async with AsyncSessionLocal() as session:
        try:
            # Deterministic backstop for the vision gate: the REJECT
            # directive from check_images is prompt-mediated, so a scan that
            # crossed the owner's threshold also refuses the save here.
            auto_reject = (
                await session.execute(
                    select(VisionScans.auto_reject)
                    .where(VisionScans.watch_id == watch_id)
                    .where(VisionScans.listing_url == url)
                    .limit(1)
                )
            ).scalar()
            if auto_reject:
                log.info(f"Refusing listing save for watch {watch_id}: vision auto-reject ({url})")
                return (
                    "REFUSED: this listing's photos crossed the user's authenticity "
                    "auto-reject threshold (see check_images). Do not save it — call "
                    "log_listing_check with reason 'authenticity' instead and move on."
                )

            # Every save of this watch queues behind this lock, so the slot
            # count below is the count the write lands on: two hunts of one
            # watch on two sites cannot both take its last slot.
            watch = (
                await session.execute(
                    select(Watches.max_listings, Watches.selection_mode)
                    .where(Watches.id == watch_id)
                    .with_for_update()
                )
            ).one()
            listing = await session.scalar(
                select(Listings)
                .where(Listings.watch_id == watch_id)
                .where(Listings.site_id == site_id)
                .where(Listings.url == url)
                .limit(1)
            )
            if listing is not None and listing.active:
                return int(listing.id)
            if listing is not None and listing.inactive_reason != "replaced":
                # Sold, ended, or untracked by the user: not a discovery, and
                # handing back its id would let price checks pile up on a row
                # the UI no longer shows.
                log.info(f"Skipping listing save for watch {watch_id}: known, inactive ({url})")
                return (
                    "SKIPPED: this listing is already known and no longer tracked (it "
                    "sold, ended, or the user untracked it). Record nothing for it and "
                    "do not log it as a rejection; move on."
                )

            verdict = None
            if parsed is not None:
                context = await _price_context(session, listing, item_id)
                verdict = validate_observation(
                    parsed, currency, listing=context, market=context["market"]
                )
                if not verdict.ok:
                    return f"Error: {verdict.reason} — re-read the page and report what it shows"

            # From here the save takes a slot — a new row, or a replaced one
            # coming back — and a full watch only has one to give by trading.
            tracked = await session.scalar(
                select(func.count())
                .select_from(Listings)
                .where(Listings.watch_id == watch_id)
                .where(Listings.active)
            )
            replaced = None
            if tracked >= watch.max_listings:
                replaced, refusal = await _replacement(
                    session, unit, watch.selection_mode, parsed, verdict
                )
                if refusal:
                    log.info(f"Refusing listing save for watch {watch_id}: {refusal}")
                    return refusal
                replaced.active = False
                replaced.inactive_reason = "replaced"
                # the chain of checks ends with the tracking, in the same breath
                await job_queue.cancel_recheck(session, replaced.id)

            if listing is None:
                listing_id = await session.scalar(
                    insert(Listings)
                    .values(
                        watch_id=watch_id,
                        item_id=item_id,
                        site_id=site_id,
                        url=url,
                        title=title,
                        site_sku=site_sku,
                        active=True,
                        match_score=match_score,
                        match_summary=match_summary,
                        discovered_by_job_id=unit.job_id,
                    )
                    .returning(Listings.id)
                )
            else:
                # A listing a swap traded away, found again: the same row
                # comes back with its price history, judged afresh.
                listing_id = int(listing.id)
                listing.active = True
                listing.inactive_reason = None
                listing.title = title
                listing.site_sku = site_sku
                listing.match_score = match_score
                listing.match_summary = match_summary
            is_new = listing is None

            unit.stats["new_listings"] += 1
            # the discovery is watched before the hunt that found it has
            # even finished — one transaction, so a listing can never
            # exist without a check ahead of it
            await job_queue.enqueue_recheck(
                session,
                listing_id=listing_id,
                watch_id=watch_id,
                item_id=item_id,
                site_id=site_id,
            )
            if unit.job_id is not None:
                if replaced is not None:
                    # the ending comes first, as it happened; its ts is also
                    # the clock that hides the old URL from the next hunts
                    await job_queue.add_event(
                        session,
                        unit.job_id,
                        "info",
                        "listing_ended",
                        f'Replaced listing #{replaced.id} "{replaced.title}" with listing '
                        f'#{listing_id} "{title}"',
                        {
                            "listing_id": int(replaced.id),
                            "item_id": item_id,
                            "reason": "replaced",
                            "replaced_by": listing_id,
                        },
                    )
                await job_queue.add_event(
                    session,
                    unit.job_id,
                    "success",
                    "listing_discovered",
                    (
                        f'Saved as listing #{listing_id} — "{title}" (match {match_score})'
                        if is_new
                        else f'Tracking listing #{listing_id} again — "{title}" '
                        f"(match {match_score})"
                    ),
                    {"listing_id": listing_id, "item_id": item_id},
                )
            if replaced is not None:
                unit.swap.done = True

            if parsed is None:
                await session.commit()
            else:
                # the price the save was judged on is the price on record,
                # written in the same transaction as the save itself
                await record_price_check(
                    session,
                    unit,
                    listing_id=listing_id,
                    price=parsed,
                    currency=currency,
                    in_stock=True,
                    status="ok",
                    method="llm",
                    confirmed=verdict.confirmed,
                    notifiable=verdict.notifiable,
                )
                unit.stats["listings_checked"] += 1
                unit.stats["prices_found"] += 1
        except Exception as e:
            log.error(f"Error recording listing for item {item_id} on site {site_id}: {e}")
            return f"Error recording listing for item {item_id} on site {site_id}: {e}"

    log.info(f"Successfully saved listing {listing_id} for item {item_id} on site {site_id}")
    if is_new:
        # committed above, so this is a pure side effect — a failed enqueue
        # can't change what this tool returns. A listing brought back was
        # announced the first time it was found.
        await enqueue_new_listing(
            watch_id,
            item_id,
            site_id,
            listing_id,
            url,
            title,
            match_score,
            match_summary,
        )
    if parsed is not None and verdict.confirmed:
        await learn_locator(unit, listing_id, parsed)
    return listing_id


async def _price_context(session, listing: Listings | None, item_id: int) -> dict:
    """What validate_observation judges a price given to save_listing against.

    A listing brought back has its own history, read the same way a price
    check reads it; a new one has only the item's market.
    """
    if listing is not None:
        return await get_price_context(int(listing.id))
    market = await session.get(MarketPrices, item_id)
    return {
        "last_price": None,
        "unconfirmed_price": None,
        "market": (
            {"status": market.status, "tiers": market.tiers, "currency": market.currency}
            if market
            else None
        ),
    }


async def _replacement(
    session, unit: UnitContext, selection_mode: str, price: Decimal | None, verdict
) -> tuple[Listings | None, str | None]:
    """The listing a save on a full watch trades away, or why it may not.

    The model proposes the trade; this is where code checks it.
    Only a swap hunt may trade, once, for the listing it picked with
    disable_listing(reason="replaced"), and only with a price it can stand
    behind. In cheapest mode that price must be strictly lower than the
    traded listing's last confirmed one — a swap never trades sideways. In
    best-match mode fit is the model's call; the price is still recorded.

    Returns:
      (the listing to retire, None), or (None, the model-facing refusal).
    """
    full = "SLOTS FULL: every slot of this watch is filled"
    leftover = "Leftover good candidates are not rejections — do not log them; move on."
    if unit.swap is None:
        return None, f"{full}, so nothing more can be saved on this hunt. {leftover}"
    if unit.swap.done:
        return None, f"SLOTS FULL: this hunt has already made its one swap. {leftover}"
    if unit.swap.replaced_listing_id is None:
        return None, (
            f"{full}. To trade this candidate in, first call disable_listing with the "
            f'weakest tracked listing\'s id and reason "replaced", then call save_listing '
            f"again with price."
        )

    replaced_id = unit.swap.replaced_listing_id
    replaced = await session.get(Listings, replaced_id)
    if replaced is None or not replaced.active or replaced.watch_id != unit.watch_id:
        unit.swap.replaced_listing_id = None
        return None, (
            f"{full}, and listing {replaced_id} is no longer tracked. Pick again from "
            f"TRACKED LISTINGS."
        )
    if price is None:
        return None, (
            f"Error: a save that replaces listing {replaced_id} needs price — the price shown "
            f"on this listing's page."
        )
    if not verdict.confirmed:
        return None, (
            f"SLOTS FULL: {price} is out of line with this item's market ({verdict.reason}), "
            f"and a trade needs a price that can be believed, so listing {replaced_id} stays "
            f"tracked. Re-read the page; if that is really the price, move on."
        )
    if selection_mode == "cheapest":
        if not verdict.notifiable:
            return None, (
                f"SLOTS FULL: a price in another currency cannot be compared with listing "
                f"{replaced_id}'s, so it stays tracked. {leftover}"
            )
        replaced_price = (await get_price_context(replaced_id))["last_price"]
        if replaced_price is not None and price >= replaced_price:
            return None, (
                f"SLOTS FULL: {price} is not lower than listing {replaced_id}'s {replaced_price}"
                f" — in cheapest mode a replacement must be strictly cheaper, so listing "
                f"{replaced_id} stays tracked. {leftover}"
            )
    return replaced, None


async def save_price_check(
    listing_id: int,
    in_stock: bool,
    status: str,
    price: float | None = None,
    currency: str = "USD",
    *,
    runtime: ToolRuntime,
) -> str:
    """
    Record a listing's current price and availability: after save_listing on a search, or
    for the one listing you were told to re-check.

    This only records the observation - it does NOT change whether the listing
    is tracked. If status is "sold" or "ended", also call `disable_listing`
    afterward, with that same status as its reason, to stop tracking it.

    Args:
      listing_id: The exact listing id returned by save_listing, or the listing_id you
        were given to re-check. Any other id is refused.
      in_stock: true/false based on the page
      status: Exactly one of "ok", "sold", "ended", "error". "ok" REQUIRES a real
               visible price; if the page no longer shows a price, status MUST be
               "sold", "ended", or "error".
      price: The numeric price shown on the page (no currency symbol), greater than
             zero. Only with status "ok" - omit it entirely for "sold"/"ended"/
             "error", and NEVER invent a price or send 0 as a placeholder.
             Report exactly what the page shows: a price wildly out of line with
             this listing's history or the item's market value is recorded but NOT
             acted on until a second reading agrees with it, so a mis-typed
             decimal point costs a day, not a bargain. If the number looks wrong
             to you, re-read the page and report what it actually says.
      currency: The three-letter code of the currency shown, e.g. "USD"
    Returns:
      A confirmation string on success, or a string starting with "Error:" saying what
      was wrong with the call or what failed.
    """
    unit = unit_of(runtime)
    if status not in PRICE_STATUSES:
        return f"Error: status must be one of {', '.join(PRICE_STATUSES)}, got {status!r}"
    if status == "ok" and (price is None or price <= 0):
        return (
            "Error: status 'ok' needs the real price shown on the page (greater than zero); "
            "if the page shows no price, use status 'sold', 'ended' or 'error' and omit price"
        )
    if status != "ok" and price is not None:
        return (
            f"Error: omit price when status is {status!r} — a price is only recorded for a "
            f"live listing"
        )
    currency = currency.upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        return f"Error: currency must be a three-letter code like USD, got {currency!r}"

    confirmed, notifiable = True, True
    parsed = parse_price(price) if price is not None else None
    if parsed is not None:
        context = await get_price_context(listing_id)
        verdict = validate_observation(
            parsed,
            currency,
            listing=context,
            market=context["market"],
        )
        if not verdict.ok:
            return f"Error: {verdict.reason} — re-read the page and report what it shows"
        # An implausible reading is RECORDED, not refused: hiding an
        # observation is its own failure. It just does not notify and does not
        # enter the charts until a second reading agrees with it.
        confirmed, notifiable = verdict.confirmed, verdict.notifiable
        if verdict.anomalous:
            log.warning(f"Listing {listing_id}: unconfirmed reading {parsed} — {verdict.reason}")

    log.info(
        f"Saving price check for listing {listing_id} at a price of {price} {currency} "
        f"(status={status})"
    )
    async with AsyncSessionLocal() as session:
        try:
            await record_price_check(
                session,
                unit,
                listing_id=listing_id,
                price=parsed,
                currency=currency,
                in_stock=in_stock,
                status=status,
                method="llm",
                confirmed=confirmed,
                notifiable=notifiable,
            )
        except UnitMismatch as e:
            log.info(f"Refusing price check: {e}")
            return str(e)
        except Exception as e:
            log.error(f"Error inserting price check for listing {listing_id}: {e}")
            return f"Error inserting price check for listing {listing_id}: {e}"

    unit.stats["listings_checked"] += 1
    if parsed is not None:
        unit.stats["prices_found"] += 1
    log.info(f"Successfully recorded listing {listing_id}")

    # The price is safe; everything from here is an optimisation for next
    # time. This is the one moment a confirmed price and the page it came from
    # exist together, so it is the only moment a locator can be learned.
    if parsed is not None and confirmed:
        await learn_locator(unit, listing_id, parsed)
    return f"Successfully recorded listing {listing_id}"


async def learn_locator(
    unit: UnitContext, listing_id: int, price: Decimal, url: str | None = None
) -> bool:
    """Capture where on the current page the confirmed price lives.

    Code does every part of this — the model is never asked for a selector,
    because a hallucinated one, or one a hostile page steered it towards, is
    exactly what a stored locator must not be. The page is read with the
    fixed extractor, Python picks which of the places it states the price to
    trust, and the choice is replayed once through the browser and required
    to read back the same number before it is written down.

    Args:
      unit: The unit in flight, carrying the browser handle.
      listing_id: The listing to learn for.
      price: The price just confirmed and recorded.
      url: The listing URL to navigate to first. Passed by the orchestrator's
        post-unit learn, when the model has already browsed elsewhere; left
        out when called from the tool, which is still on the page.
    Returns:
      True when a locator was verified and stored.
    """
    browser = unit.browser
    if browser is None:
        return False
    if url is not None and not await browser.navigate(url):
        return False

    extract = await browser.extract()
    if extract is None:
        return False
    if url is not None and not _same_page(extract.get("url"), url):
        log.info(f"Listing {listing_id}: navigation did not land on the listing; not learning")
        return False

    found = select_locator(extract, price)
    if found is None:
        log.info(f"Listing {listing_id}: page does not state {price} anywhere reachable")
        return False

    # Verify by replay before trusting it: a locator that cannot read back the
    # number it was derived from would quietly record the wrong one forever.
    replayed = await browser.read_locator(found.kind, found.locator)
    if parse_price(replayed) != price:
        log.info(f"Listing {listing_id}: {found.locator} replayed as {replayed!r}, not {price}")
        return False

    probed = False
    if found.kind in static.STATIC_KINDS:
        probed = await static.probe(extract.get("url") or url, unit.site_base_url, found, price)
    return await save_locator(listing_id, found.kind, found.locator, probed)


def _same_page(href: str | None, url: str) -> bool:
    """Whether the browser is still on the listing — same host and path.

    Query strings differ freely (eBay appends tracking parameters to its own
    links), but a different path is a different listing, and learning a
    locator from the wrong page is how a listing ends up tracking someone
    else's price.
    """
    if not href:
        return False
    here, there = urlparse(href), urlparse(url)
    return here.hostname == there.hostname and here.path.rstrip("/") == there.path.rstrip("/")


async def disable_listing(listing_id: int, reason: str, *, runtime: ToolRuntime) -> str:
    """
    Mark a listing inactive so it is no longer tracked/rechecked.

    Use this when a listing is no longer a live offer for the item: it sold or
    ended (after recording that outcome with `save_price_check`), or its only
    price is now an auction bid. Call this once per listing; disabling an
    already-inactive listing is harmless.

    On a hunt for something better (your instructions show a TRACKED LISTINGS
    block), reason "replaced" picks the tracked listing your next save_listing
    will replace. It does not untrack anything by itself: the listing stays
    tracked until that save goes through, and if code refuses the save, nothing
    changes.

    Args:
      listing_id: The exact listing id to disable - the listing_id you were given to
        re-check, one save_listing returned, or (with "replaced") one from TRACKED
        LISTINGS. Any other id is refused.
      reason: Exactly one of "sold", "ended", "auction" - "sold"/"ended" matching the
        status you just saved, "auction" when the page offers only bids. "replaced"
        only on a hunt for something better, for the weakest tracked listing, right
        before the save_listing that replaces it.
    Returns:
      A confirmation string on success, or a string starting with "Error:" saying what
      was wrong with the call or what failed.
    """
    unit = unit_of(runtime)
    if reason == "replaced":
        return await _pick_replacement(listing_id, unit)
    if reason not in DISABLE_REASONS:
        return f"Error: reason must be one of {', '.join(DISABLE_REASONS)}, got {reason!r}"

    log.info(f"Disabling listing {listing_id}: {reason}")
    async with AsyncSessionLocal() as session:
        try:
            await assert_writable(session, listing_id, unit)
            await session.execute(
                update(Listings)
                .where(Listings.id == listing_id)
                .values(active=False, inactive_reason=reason)
            )
            # an untracked listing is not re-read: the check chain ends here,
            # in the same transaction that ended the tracking
            await job_queue.cancel_recheck(session, listing_id)
            await session.commit()
            log.info(f"Listing {listing_id} marked inactive ({reason})")
        except UnitMismatch as e:
            log.info(f"Refusing disable: {e}")
            return str(e)
        except Exception as e:
            log.error(f"Error disabling listing {listing_id}: {e}")
            return f"Error disabling listing {listing_id}: {e}"

    # the slot it held wakes the watch's hunts — best-effort and after the
    # commit, so a failed wake never undoes the ending (the sweep catches up)
    await job_queue.wake_hunts(unit.watch_id)
    return f"Listing {listing_id} marked inactive"


async def _pick_replacement(listing_id: int, unit: UnitContext) -> str:
    """disable_listing(reason="replaced"): remember which listing the next
    save gives up, and write nothing.

    Nothing is untracked here because the trade is not decided here. Only
    save_listing knows the candidate's price, so only it can tell whether the
    trade is allowed; retiring the old listing now would leave the watch a
    listing short whenever that save is refused. No hunt is woken either: the
    slot this frees is refilled in the same transaction that frees it.
    """
    if unit.swap is None:
        return (
            'Error: reason "replaced" is only for a hunt looking for something better than '
            'a full watch\'s weakest listing, and this hunt is not one. Use "sold", "ended" '
            'or "auction".'
        )
    if unit.swap.done:
        return "Error: this hunt has already made its one swap — replace nothing more."

    async with AsyncSessionLocal() as session:
        try:
            await assert_writable(session, listing_id, unit)
            active = await session.scalar(select(Listings.active).where(Listings.id == listing_id))
        except UnitMismatch as e:
            log.info(f"Refusing replacement pick: {e}")
            return str(e)
        except Exception as e:
            log.error(f"Error reading listing {listing_id}: {e}")
            return f"Error reading listing {listing_id}: {e}"
    if not active:
        return (
            f"Error: listing {listing_id} is not tracked any more — pick the weakest listing "
            f"from TRACKED LISTINGS."
        )

    unit.swap.replaced_listing_id = listing_id
    log.info(f"Listing {listing_id} picked for replacement (watch {unit.watch_id})")
    return (
        f"Listing {listing_id} will be replaced by your next save_listing call — pass that "
        f"call the new listing's price. Listing {listing_id} stays tracked until then, and "
        f"if the save is refused, nothing changes."
    )


async def log_listing_check(
    url: str, reason: str, notes: str | None = None, *, runtime: ToolRuntime
) -> str:
    """
    Log a listing you evaluated but decided NOT to save, so future runs don't
    have to re-discover and re-judge the same rejection from scratch. It is
    logged against the watch and site this search is for - you never pass those.

    Call this for every candidate you look at and reject - poor fit, duplicate
    of something already saved, failed authenticity screening, etc. Do NOT
    call this for listings you saved with `save_listing`.

    Args:
      url: The full http(s) URL of the listing you evaluated and rejected. It must be
        a page on THIS site - a URL on any other domain is refused.
      reason: Short category for the rejection, e.g. "poor_fit", "duplicate",
        "authenticity", "auction". A few words, not a sentence.
      notes: Optional ONE-LINE detail on why, e.g. "no repro flags but price is 3x
        market". This text is shown back to you on later searches of this site, so keep
        it factual and short; long text is truncated.
    Returns:
      A confirmation string on success, or a string starting with "Error:" saying what
      was wrong with the call or what failed.
    """
    unit = unit_of(runtime)
    watch_id, site_id = unit.watch_id, unit.site_id
    refused = _refuse_url(url, unit)
    if refused:
        return refused
    if not reason.strip():
        return 'Error: reason must name the rejection category, e.g. "poor_fit"'
    # both are replayed into every later hunt prompt for this pair, which is
    # where a page could otherwise write itself an instruction
    reason = clip_text(reason, MAX_REASON)
    notes = clip_text(notes, MAX_NOTES)

    log.info(f"Logging listing check for watch id {watch_id}")
    async with AsyncSessionLocal() as session:
        try:
            stmt = insert(ListingChecks).values(
                watch_id=watch_id,
                site_id=site_id,
                url=url,
                reason=reason,
                notes=notes,
                checked_at=datetime.now(UTC),
            )

            await session.execute(stmt)
            if unit.job_id is not None and unit.is_hunt:
                await job_queue.add_event(
                    session,
                    unit.job_id,
                    "info",
                    "listing_evaluated",
                    f"Skipped {url} — {reason}" + (f": {notes}" if notes else ""),
                    {"item_id": unit.item_id, "url": url, "reason": reason, "tracked": False},
                )
            await session.commit()

            log.info(f"Logged rejected listing for watch {watch_id} on site {site_id}: {url}")
            return f"Logged rejected listing for watch {watch_id} on site {site_id}: {url}"
        except Exception as e:
            log.error(f"Error logging listing check for watch {watch_id} on site {site_id}: {e}")
            return f"Error logging listing check for watch {watch_id} on site {site_id}: {e}"


async def check_images(
    listing_url: str,
    image_urls: list[str],
    llm_authenticity_read: str,
    *,
    runtime: ToolRuntime,
) -> str:
    """
    Get an image-based second opinion on a listing's authenticity before you
    decide to save or reject it: the listing's photos are compared against
    this item's library of known-real and known-fake reference images.

    Call this exactly once per candidate listing, after your own authenticity
    screening and before save_listing / log_listing_check.

    Args:
      listing_url: The full http(s) URL of the candidate listing page you are evaluating.
        It must be a page on THIS site - a URL on any other domain is refused.
      image_urls: Direct URLs of the photos on the listing page that actually
        depict the item itself. Choose carefully: skip packaging-only shots,
        hands/scale references, seller logos, stock banners, and unrelated
        thumbnails. 1-6 images is typical. If the listing has no usable
        photos, skip the call entirely — an empty list is refused.
      llm_authenticity_read: Your OWN verdict from the screening you already
        did, exactly one of "looks_authentic", "suspect", "unsure". Report it
        honestly — it is recorded for corroboration and does not change how
        the images are scored.
    Returns:
      A report string with per-image scores and an overall verdict
      ("leans_real", "leans_fake", or "inconclusive"), or an error string.
      Act on it as follows:
        - If it starts with "REJECT:", the fake confidence exceeded this
          user's auto-reject threshold. Do NOT save the listing: call
          log_listing_check with reason "authenticity", quote the reported
          confidence in notes, and move on.
        - "leans_fake" below the reject threshold: you may still save the
          listing if it otherwise qualifies, but lower match_score and state
          the photo concern in match_summary.
        - "leans_real" is weak reassurance only — scammers reuse photos of
          genuine items — so never raise match_score because of it and never
          describe a listing as verified authentic.
        - "inconclusive", "no verdict", or an error: the check could not help;
          rely entirely on your own screening.
    """
    unit = unit_of(runtime)
    watch_id, item_id = unit.watch_id, unit.item_id
    refused = _refuse_url(listing_url, unit, field="listing_url")
    if refused:
        return refused
    if not image_urls:
        return (
            "Error: image_urls is empty — skip check_images when the listing has no usable "
            "photos and rely on your own screening"
        )
    # Photos live on a CDN that is often a different domain from the site
    # (i.ebayimg.com, static.mercdn.net), so image URLs get the network half
    # of the guard only: no private addresses, no container names. The
    # sidecar's own fetcher (vision/fetcher.py) does the actual download.
    bad = [image_url for image_url in image_urls if public_url(image_url)]
    if bad:
        return f"Error: image_urls must be direct public http(s) image URLs, got {bad[0]!r}"
    if llm_authenticity_read not in AUTHENTICITY_READS:
        return (
            f"Error: llm_authenticity_read must be one of {', '.join(AUTHENTICITY_READS)}, "
            f"got {llm_authenticity_read!r}"
        )

    log.info(f"Checking {len(image_urls)} image(s) for watch {watch_id}: {listing_url}")
    try:
        async with httpx.AsyncClient(timeout=VISION_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{VISION_SIDECAR_URL}/check-images",
                json={
                    "watch_id": watch_id,
                    "item_id": item_id,
                    "listing_url": listing_url,
                    "image_urls": image_urls,
                    "llm_authenticity_read": llm_authenticity_read,
                },
            )
            response.raise_for_status()
            result = response.json()
    except Exception as e:
        # A sidecar outage degrades to "no verdict"; it never blocks the hunt.
        log.error(f"Vision sidecar unavailable for {listing_url}: {e}")
        return f"No verdict: authenticity image check unavailable ({e})"

    verdict = result["verdict"]
    confidence = result["fake_confidence"]

    if result["auto_reject"]:
        return (
            f"REJECT: fake confidence {confidence} meets this user's auto-reject "
            f"threshold — do NOT save this listing. Call log_listing_check with reason "
            f"'authenticity', quote the confidence in notes, and move on."
        )

    lines = [
        f"Photo authenticity check for {listing_url}: verdict {verdict}"
        + (f" (fake confidence {confidence})" if confidence is not None else "")
    ]
    for image in result["images"]:
        image_confidence = image["fake_confidence"]
        lines.append(
            f"  - {image['image_url']}: "
            + (
                f"fake confidence {image_confidence}"
                if image_confidence is not None
                else "could not be scored"
            )
        )
    if result["skipped"]:
        lines.append(f"  Skipped (could not fetch): {', '.join(result['skipped'])}")
    if verdict == "leans_fake":
        lines.append(
            "  Photos are consistent with known fakes, below the auto-reject threshold: "
            "you may still save this listing if it otherwise qualifies, but lower "
            "match_score and state the photo concern in match_summary."
        )
    elif verdict == "leans_real":
        lines.append(
            "  Photos match known-real references. Weak reassurance ONLY — scammers "
            "reuse photos of genuine items — so do not raise match_score and never "
            "describe the listing as verified authentic."
        )
    else:
        lines.append(
            "  The reference library could not judge these photos; rely entirely on "
            "your own screening."
        )
    return "\n".join(lines)
