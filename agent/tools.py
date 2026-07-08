"""Database-writing tools exposed to the LLM agent.

Each function's docstring doubles as the tool description the LLM sees, so
they are written as instructions to the model — keep them accurate and
imperative when editing. Errors are returned as strings (not raised) so the
agent can read them and react."""

import logging
from datetime import datetime
from database import AsyncSessionLocal, ListingChecks
from database import Listings, PriceChecks
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import except_, select, update


log = logging.getLogger(__name__)
async def save_listing(watch_id: int, item_id: int, site_id: int, url: str, title: str, match_score: int, match_summary: str, site_sku:str|None = None) -> int|str:
    """
    Save a listing that matches the user's selected criteria to the database and return its listing_id.

    Args:
      watch_id: The internal id of the watch (user+item) this search is being run for
      item_id: The item id you have for the current item
      site_id: The internal id for the current site being searched
      url: The URL of the item that was found meeting the required criteria
      title: The listing's actual title as shown on the site
      site_sku: If a SKU is present on the site, record it here
      match_score: How well this listing fits the requested criteria, as an integer 0-100 (examples: 67, 4, 42). Be calibrated - do not default to high.
      match_summary: One short line justifying the score, e.g. "dry battery ok, cart only, authentic per photos"
    Returns:
      One of these two:
        listing_id: The internal ID for the listing. If it already exists, returns the existing listing_id instead.
        Error: A string naming the site/item combo that errored and what the error was
    """

    log.info(f"Saving listing for item {item_id} on site {site_id} (watch {watch_id})")

    async with AsyncSessionLocal() as session:
        try:
            stmt = insert(Listings).values(
                watch_id=watch_id,
                item_id=item_id,
                site_id=site_id,
                url=url,
                title=title,
                site_sku=site_sku,
                active=True,
                match_score=match_score,
                match_summary=match_summary
            ).on_conflict_do_nothing(constraint='uq_watch_site_url')

            await session.execute(stmt)
            await session.commit()

            stmt = select(Listings).where(
              Listings.watch_id == watch_id,
              Listings.site_id == site_id,
              Listings.url == url
            ).limit(1)

            results = await session.execute(stmt)
            listing_id  = results.scalar()
            if listing_id is not None:
                log.info(f"Successfully created listing for item {item_id} on site {site_id}")
                return int(listing_id.id)
            else:
                log.info(f"Unable to fetch the listing id for the item {item_id} on site {site_id}")
                return f"Unable to fetch the listing id for the item {item_id} on site {site_id}"
        except Exception as e:
            log.error(f"Error recording listing for item {item_id} on site {site_id}: {e}")
            return f"Error recording listing for item {item_id} on site {site_id}: {e}"


    
async def save_price_check(listing_id: int, in_stock: bool, status: str, price: float | None = None, currency: str = "USD") -> str:
    """
    Use this tool after a listing is created, to record its current price and availability.

    This only records the observation - it does NOT change whether the listing
    is tracked. If status is "sold" or "ended", also call `disable_listing`
    afterward to stop tracking it.

    Args:
      listing_id: The exact listing id returned by save_listing
      in_stock: true/false based on the page
      status: Exactly one of "ok", "sold", "ended", "error". If the page no
               longer shows a price, status MUST be "sold", "ended", or
               "error" - never "ok" with a missing/zero price.
      price: The numeric price shown on the page (no currency symbol). Omit
             this entirely if no price is shown (e.g. status is "sold"/"ended"/
             "error") - do NOT invent a price or send 0 as a placeholder.
      currency: The currency shown, e.g. "USD"
    Returns:
      A confirmation string on success, or a string describing the error.
    """

    log.info(f"Saving price check for listing {listing_id} at a price of {price} {currency} (status={status})")
    async with AsyncSessionLocal() as session:
        try:
            stmt = insert(PriceChecks).values(
                listing_id=listing_id,
                price=price,
                currency=currency,
                in_stock=in_stock,
                status=status,
                checked_at=datetime.now()
            )

            await session.execute(stmt)
            await session.commit()

            log.info(f"Successfully recorded listing {listing_id}")
            return f"Successfully recorded listing {listing_id}"


        except Exception as e:
            log.error(f"Error inserting price check for listing {listing_id}: {e}")
            return f"Error inserting price check for listing {listing_id}: {e}"


async def disable_listing(listing_id: int, reason: str) -> str:
    """
    Mark a listing inactive so it is no longer tracked/rechecked.

    Use this when a listing is confirmed sold, ended, or otherwise no longer
    a live offer for the item - after recording that outcome with
    `save_price_check`. Call this once per listing; disabling an
    already-inactive listing is harmless.

    Args:
      listing_id: The exact listing id to disable.
      reason: Short note on why it's being disabled, e.g. "sold" or "listing removed".
    Returns:
      A confirmation string on success, or a string describing the error.
    """

    log.info(f"Disabling listing {listing_id}: {reason}")
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(
                update(Listings).where(Listings.id == listing_id).values(active=False)
            )
            await session.commit()

            log.info(f"Listing {listing_id} marked inactive ({reason})")
            return f"Listing {listing_id} marked inactive"

        except Exception as e:
            log.error(f"Error disabling listing {listing_id}: {e}")
            return f"Error disabling listing {listing_id}: {e}"


async def log_listing_check(watch_id: int, site_id: int, url: str, reason: str, notes: str|None = None) -> str:
    """
    Log a listing you evaluated but decided NOT to save, so future runs don't
    have to re-discover and re-judge the same rejection from scratch.

    Call this for every candidate you look at and reject - poor fit, duplicate
    of something already saved, failed authenticity screening, etc. Do NOT
    call this for listings you saved with `save_listing`.

    Args:
      watch_id: The internal id of the watch (user+item) this search is being run for
      site_id: The internal id for the current site being searched
      url: The URL of the listing you evaluated and rejected
      reason: Short category for the rejection, e.g. "poor_fit", "duplicate", "authenticity"
      notes: Optional one-line detail on why, e.g. "no repro flags but price is 3x market"
    Returns:
      A con efirmation string on success, or a string describing the error.
    """

    log.info(f"Logging listing check for watch id {watch_id}")
    async with AsyncSessionLocal() as session:
        try:
            stmt = insert(ListingChecks).values(
                watch_id=watch_id,
                site_id=site_id,
                url=url,
                reason=reason,
                notes=notes,
                checked_at=datetime.now(),
            )

            await session.execute(stmt)
            await session.commit()

            log.info(f"Logged rejected listing for watch {watch_id} on site {site_id}: {url}")
            return f"Logged rejected listing for watch {watch_id} on site {site_id}: {url}"
        except Exception as e:
            log.error(f"Error logging listing check for watch {watch_id} on site {site_id}: {e}")
            return f"Error logging listing check for watch {watch_id} on site {site_id}: {e}"



