"""Database-writing tools exposed to the LLM agent.

Each function's docstring doubles as the tool description the LLM sees, so
they are written as instructions to the model — keep them accurate and
imperative when editing. Errors are returned as strings (not raised) so the
agent can read them and react.

Which watch, item and site a call is about — and on a recheck, which
listing — is never a tool argument. The orchestrator binds it per unit as a
UnitContext on the run config, and langchain hands every tool its runtime
through the keyword-only `runtime` parameter, which never appears in the
schema the model sees. A wrong id typed by the model used to attach a price
to some other listing; now there is no id to type."""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from config import VISION_SIDECAR_URL, VISION_TIMEOUT_SECONDS
from database import (
    AsyncSessionLocal,
    ListingChecks,
    Listings,
    PriceChecks,
    VisionScans,
    enqueue_new_listing,
)
from langchain.tools import ToolRuntime
from notify import notify_target_met
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

log = logging.getLogger(__name__)

# Per-run tally of successful writes, read by the orchestrator for the run's
# terminal agent_runs.stats. A plain module dict, not a contextvar: one process
# drives exactly one run at a time. `errors` is counted by the orchestrator.
run_stats = {"listings_checked": 0, "prices_found": 0, "new_listings": 0, "errors": 0}


def reset_run_stats() -> None:
    """Zero the tally in place before a run starts."""
    for key in run_stats:
        run_stats[key] = 0


def read_run_stats() -> dict:
    """A copy of the tally, for the run's terminal stats write."""
    return dict(run_stats)


@dataclass(frozen=True)
class UnitContext:
    """What one unit of work is about. Bound by the orchestrator, read by every
    tool. listing_id is set on a recheck unit — the one listing being
    revisited is the only one a price may be recorded against; a scan unit
    leaves it None, and any listing of the watch is writable (save_listing is
    what creates them)."""

    watch_id: int
    item_id: int
    site_id: int
    listing_id: int | None = None


PRICE_STATUSES = ("ok", "sold", "ended", "error")
AUTHENTICITY_READS = ("looks_authentic", "suspect", "unsure")


def _unit(runtime: ToolRuntime) -> UnitContext:
    """The unit this call belongs to. Carried on config["configurable"] rather
    than the runtime's `context` slot: langchain serializes the injected
    runtime on every call, and a non-None context there trips a pydantic
    serializer warning each time — configurable rides along untouched."""
    return runtime.config["configurable"]["unit"]


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


async def _listing_mismatch(session, listing_id: int, unit: UnitContext) -> str | None:
    """Why `listing_id` may not be written under this unit, or None when it
    may. On a recheck the unit is about exactly one listing; on a scan the id
    must at least belong to this watch. Either way a typo would attach the
    observation to someone else's listing, which is data corruption."""
    if unit.listing_id is not None and listing_id != unit.listing_id:
        return (
            f"Error: this task is about listing {unit.listing_id}, not {listing_id} — "
            f"use listing_id={unit.listing_id}."
        )
    owner = await session.scalar(select(Listings.watch_id).where(Listings.id == listing_id))
    if owner != unit.watch_id:
        return (
            f"Error: listing {listing_id} is not one of this watch's listings — use the "
            f"exact listing_id save_listing returned."
        )
    return None


async def save_listing(
    url: str,
    title: str,
    match_score: int,
    match_summary: str,
    site_sku: str | None = None,
    *,
    runtime: ToolRuntime,
) -> int | str:
    """
    Save a listing that matches the user's selected criteria to the database and return its
    listing_id. It is saved under the watch, item and site this search is for — those are
    already known here, so you never pass them.

    Args:
      url: The full http(s) URL of the listing page you actually visited
      title: The listing's actual title as shown on the site
      site_sku: If a SKU is present on the site, record it here
      match_score: How well this listing fits the requested criteria, as an integer 0-100
        (examples: 67, 4, 42). Be calibrated - do not default to high.
      match_summary: One short line justifying the score, e.g. "dry battery ok, cart only,
        authentic per photos"
    Returns:
      One of these four:
        listing_id: The internal ID for the listing. If it is already tracked, returns the
          existing listing_id instead.
        SKIPPED: A string starting with "SKIPPED:" — this listing is already known and no
          longer tracked (it sold, ended, or the user untracked it). Record nothing for it
          and do not log it as a rejection either; move on.
        REFUSED: A string starting with "REFUSED:" — this listing's photos crossed the
          user's authenticity auto-reject threshold (see check_images). Do not retry;
          call log_listing_check with reason "authenticity" instead and move on.
        Error: Any other string — what was wrong with the call, or what failed while
          saving
    """
    unit = _unit(runtime)
    watch_id, item_id, site_id = unit.watch_id, unit.item_id, unit.site_id
    if not _is_http_url(url):
        return f"Error: url must be the listing page's full http(s) URL, got {url!r}"
    if not 0 <= match_score <= 100:
        return f"Error: match_score must be an integer from 0 to 100, got {match_score}"

    log.info(f"Saving listing for item {item_id} on site {site_id} (watch {watch_id})")

    async with AsyncSessionLocal() as session:
        try:
            # Deterministic backstop for the vision gate (D-V2): the REJECT
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

            stmt = (
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
                )
                .on_conflict_do_nothing(constraint="uq_watch_site_url")
            )

            result = await session.execute(stmt)
            await session.commit()
            # rowcount 1 = a genuinely new row; 0 = the conflict target existed
            is_new = result.rowcount == 1
            if is_new:
                run_stats["new_listings"] += 1

            stmt = (
                select(Listings)
                .where(
                    Listings.watch_id == watch_id, Listings.site_id == site_id, Listings.url == url
                )
                .limit(1)
            )

            results = await session.execute(stmt)
            listing_id = results.scalar()
            if listing_id is not None:
                if not listing_id.active:
                    # Sold, ended, or untracked by the user: not a discovery,
                    # and handing back its id would let price checks pile up
                    # on a row the UI no longer shows.
                    log.info(f"Skipping listing save for watch {watch_id}: known, inactive ({url})")
                    return (
                        "SKIPPED: this listing is already known and no longer tracked (it "
                        "sold, ended, or the user untracked it). Record nothing for it and "
                        "do not log it as a rejection; move on."
                    )
                log.info(f"Successfully created listing for item {item_id} on site {site_id}")
                if is_new:
                    # committed above, so this is a pure side effect — a failed
                    # enqueue can't change what this tool returns
                    await enqueue_new_listing(
                        watch_id,
                        item_id,
                        site_id,
                        int(listing_id.id),
                        url,
                        title,
                        match_score,
                        match_summary,
                    )
                return int(listing_id.id)
            else:
                log.info(f"Unable to fetch the listing id for the item {item_id} on site {site_id}")
                return f"Unable to fetch the listing id for the item {item_id} on site {site_id}"
        except Exception as e:
            log.error(f"Error recording listing for item {item_id} on site {site_id}: {e}")
            return f"Error recording listing for item {item_id} on site {site_id}: {e}"


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
    afterward to stop tracking it.

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
      currency: The three-letter code of the currency shown, e.g. "USD"
    Returns:
      A confirmation string on success, or a string starting with "Error:" saying what
      was wrong with the call or what failed.
    """
    unit = _unit(runtime)
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

    log.info(
        f"Saving price check for listing {listing_id} at a price of {price} {currency} "
        f"(status={status})"
    )
    async with AsyncSessionLocal() as session:
        try:
            mismatch = await _listing_mismatch(session, listing_id, unit)
            if mismatch:
                log.info(f"Refusing price check: {mismatch}")
                return mismatch

            stmt = (
                insert(PriceChecks)
                .values(
                    listing_id=listing_id,
                    price=price,
                    currency=currency,
                    in_stock=in_stock,
                    status=status,
                    checked_at=datetime.now(UTC),
                )
                .returning(PriceChecks.id)
            )

            result = await session.execute(stmt)
            check_id = result.scalar_one()
            await session.commit()
            run_stats["listings_checked"] += 1
            if price is not None:
                run_stats["prices_found"] += 1

            log.info(f"Successfully recorded listing {listing_id}")

        except Exception as e:
            log.error(f"Error inserting price check for listing {listing_id}: {e}")
            return f"Error inserting price check for listing {listing_id}: {e}"

    # Committed and the session closed before the enqueue: a target-hit
    # notification is a side effect of recording the price, never a
    # precondition for it. A priceless or out-of-stock check can't be a snag.
    if in_stock and price is not None and price > 0:
        await notify_target_met(listing_id, check_id, price, currency)
    return f"Successfully recorded listing {listing_id}"


async def disable_listing(listing_id: int, reason: str, *, runtime: ToolRuntime) -> str:
    """
    Mark a listing inactive so it is no longer tracked/rechecked.

    Use this when a listing is confirmed sold, ended, or otherwise no longer
    a live offer for the item - after recording that outcome with
    `save_price_check`. Call this once per listing; disabling an
    already-inactive listing is harmless.

    Args:
      listing_id: The exact listing id to disable - the listing_id you were given to
        re-check, or one save_listing returned. Any other id is refused.
      reason: Short note on why it's being disabled, e.g. "sold" or "listing removed".
    Returns:
      A confirmation string on success, or a string starting with "Error:" saying what
      was wrong with the call or what failed.
    """
    unit = _unit(runtime)
    if not reason.strip():
        return 'Error: reason must say why the listing is being disabled, e.g. "sold"'

    log.info(f"Disabling listing {listing_id}: {reason}")
    async with AsyncSessionLocal() as session:
        try:
            mismatch = await _listing_mismatch(session, listing_id, unit)
            if mismatch:
                log.info(f"Refusing disable: {mismatch}")
                return mismatch

            await session.execute(
                update(Listings).where(Listings.id == listing_id).values(active=False)
            )
            await session.commit()

            log.info(f"Listing {listing_id} marked inactive ({reason})")
            return f"Listing {listing_id} marked inactive"

        except Exception as e:
            log.error(f"Error disabling listing {listing_id}: {e}")
            return f"Error disabling listing {listing_id}: {e}"


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
      url: The full http(s) URL of the listing you evaluated and rejected
      reason: Short category for the rejection, e.g. "poor_fit", "duplicate",
        "authenticity", "auction"
      notes: Optional one-line detail on why, e.g. "no repro flags but price is 3x market"
    Returns:
      A confirmation string on success, or a string starting with "Error:" saying what
      was wrong with the call or what failed.
    """
    unit = _unit(runtime)
    watch_id, site_id = unit.watch_id, unit.site_id
    if not _is_http_url(url):
        return f"Error: url must be the listing page's full http(s) URL, got {url!r}"
    if not reason.strip():
        return 'Error: reason must name the rejection category, e.g. "poor_fit"'

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
      listing_url: The full http(s) URL of the candidate listing page you are evaluating
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
    unit = _unit(runtime)
    watch_id, item_id = unit.watch_id, unit.item_id
    if not _is_http_url(listing_url):
        return (
            f"Error: listing_url must be the listing page's full http(s) URL, got {listing_url!r}"
        )
    if not image_urls:
        return (
            "Error: image_urls is empty — skip check_images when the listing has no usable "
            "photos and rely on your own screening"
        )
    bad = [image_url for image_url in image_urls if not _is_http_url(image_url)]
    if bad:
        return f"Error: image_urls must be direct http(s) image URLs, got {bad[0]!r}"
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
        # Same isolation contract as the grounding pre-pass: a sidecar outage
        # degrades to "no verdict", it never blocks the scrape (D-V2).
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
