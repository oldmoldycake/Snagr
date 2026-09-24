"""The one place a price observation is written.

Both paths that can see a price end here: the save_price_check tool, when the
LLM reports one, and the deterministic recheck, when code replays a locator.
Having one writer is what lets the notification rules hold no matter which
path ran — a ntfy push fires from a browserless HTTP GET exactly as it fires
from a model reading a page.

Everything happens in one transaction, under a row lock on the watch. The
check row, the cooldown stamp and the outbox row are decided against the same
snapshot, so two workers checking two of a watch's listings at the same
moment cannot both conclude they are the crossing and both announce it.

The one asymmetry is deliberate: **an observation beats a notification.** The
notification steps run inside a savepoint, so a failure there rolls back the
announcement and nothing else — losing the price to a broken outbox would be
the worse outcome by far, and it is exactly what the old
commit-then-notify-separately shape protected against.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from config import NOTIFY_COOLDOWN_HOURS
from database import Items, Listings, NotificationOutbox, PriceChecks, Sites, Watches
from jobs import add_event
from locators import PageReader
from notify import target_hit_payload
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

log = logging.getLogger(__name__)

COOLDOWN = timedelta(hours=NOTIFY_COOLDOWN_HOURS)


def new_tally() -> dict[str, int]:
    """A fresh per-unit tally — what the job's terminal stats are built from."""
    return {"listings_checked": 0, "prices_found": 0, "new_listings": 0, "errors": 0}


@dataclass
class Swap:
    """What a swap hunt has traded so far. Mutable, like the tally: the unit
    is frozen so its ids cannot move, not so its progress cannot.

    A swap hunt runs on a full watch at a person's request, and its only way
    to save anything is to trade the weakest tracked listing for something
    better. disable_listing(reason="replaced") only picks the
    listing to give up; the next save_listing makes the trade, both halves in
    one transaction, so a refused save leaves the watch exactly as it was.
    done is set by that save: one trade per hunt, and a hunt is one site.
    """

    replaced_listing_id: int | None = None
    done: bool = False


@dataclass(frozen=True)
class UnitContext:
    """What one unit of work is about.

    Bound by the orchestrator, read by every tool (agent/tools.py) and by the
    deterministic recheck. listing_id is set on a recheck unit — the one
    listing being revisited is the only one a price may be recorded against;
    a hunt unit leaves it None, and any listing of the watch is writable
    (save_listing is what creates them). browser is the handle on the open
    session, so a tool can read the page the model is looking at; like the
    ids, it is never a model-supplied argument. site_base_url is what every
    URL the model types is checked against.

    job_id is the job this unit runs under: where its progress events go. The
    tally rides here rather than in a module global because workers run
    several jobs at once, and a job's stats have to be its own.

    swap is set on a swap hunt only — a person's "hunt now" on a full watch —
    and None everywhere else, which is what keeps reason="replaced" out of
    every other unit's reach.

    It lives here, next to the one writer of observations, because that is
    what it exists to constrain — the tools import it from here.
    """

    watch_id: int
    item_id: int
    site_id: int
    site_base_url: str | None = None
    listing_id: int | None = None
    browser: PageReader | None = None
    job_id: int | None = None
    stats: dict[str, int] = field(default_factory=new_tally)
    swap: Swap | None = None

    @property
    def is_hunt(self) -> bool:
        """A hunt is not bound to one listing — that is exactly what makes it
        a hunt, and what decides whether its writes have a story to tell."""
        return self.listing_id is None


class UnitMismatch(Exception):
    """A call named a listing this unit may not write to.

    Carries the model-facing wording, because the tool hands it straight back
    to the LLM: on a recheck the unit is about exactly one listing, and on a
    hunt the id must at least belong to this watch. Either way a typo would
    attach the observation to someone else's listing, which is data
    corruption rather than a bad answer.
    """


@dataclass(frozen=True)
class Recorded:
    """What one call to record_price_check did."""

    check_id: int
    notified: bool


async def assert_writable(session, listing_id: int, unit: UnitContext) -> None:
    """Raise UnitMismatch unless this unit may write to this listing."""
    if unit.listing_id is not None and listing_id != unit.listing_id:
        raise UnitMismatch(
            f"Error: this task is about listing {unit.listing_id}, not {listing_id} — "
            f"use listing_id={unit.listing_id}."
        )
    owner = await session.scalar(select(Listings.watch_id).where(Listings.id == listing_id))
    if owner != unit.watch_id:
        raise UnitMismatch(
            f"Error: listing {listing_id} is not one of this watch's listings — use the "
            f"exact listing_id save_listing returned."
        )


async def record_price_check(
    session,
    unit: UnitContext,
    *,
    listing_id: int,
    price: Decimal | None,
    currency: str,
    in_stock: bool | None,
    status: str,
    method: str,
    confirmed: bool = True,
    notifiable: bool = True,
) -> Recorded:
    """Write one price observation and, if it is a crossing, queue the alert.

    Args:
      session: An open AsyncSession. This function owns the transaction on it
        and commits before returning.
      unit: The unit of work this call belongs to — which watch, item, site
        and (on a recheck) listing it is bound to.
      listing_id: The listing observed. Checked against the unit.
      price: The price, or None for a check that saw no price.
      currency: The three-letter code the page quoted.
      in_stock: Whether the page offered it, or None when unknowable.
      status: One of ok | sold | ended | error.
      method: How it was read — llm | jsonld | meta | microdata | locator.
      confirmed: False for a reading the plausibility bands rejected. Such a
        row is kept but never announced and never aggregated.
      notifiable: False when the price is quoted in another currency —
        recorded, never mixed, never announced.
    Returns:
      The check's id and whether it queued a notification.
    Raises:
      UnitMismatch when the listing is not this unit's to write.
      Anything the database raises: a failed observation is a failed unit.
    """
    # serialises every writer of this watch for the rest of the transaction,
    # so the edge test and the cooldown take see one consistent picture
    await session.execute(select(Watches.id).where(Watches.id == unit.watch_id).with_for_update())
    await assert_writable(session, listing_id, unit)

    check_id = (
        await session.execute(
            insert(PriceChecks)
            .values(
                listing_id=listing_id,
                price=price,
                currency=currency,
                in_stock=in_stock,
                status=status,
                method=method,
                confirmed=confirmed,
                checked_at=datetime.now(UTC),
            )
            .returning(PriceChecks.id)
        )
    ).scalar_one()

    # A page the reader could not get a price out of is a failed read of that
    # site, and the tally is where the worker learns it: the model reports
    # this by recording status="error" rather than by raising, so nothing
    # upstream would otherwise notice a marketplace that has stopped
    # answering (see agent/breaker.py).
    if status == "error":
        unit.stats["errors"] += 1

    # A hunt has a log; a recheck has none, because its whole output is the
    # price_checks row the trigger turns into a listing.checked frame.
    if unit.is_hunt and unit.job_id is not None:
        await _announce(session, unit.job_id, listing_id, unit.item_id, price, currency, status)

    notified = False
    # A priceless, out-of-stock, unbelieved or foreign-currency check can
    # never be a snag, so it never reaches the notification path at all.
    if confirmed and notifiable and in_stock and price is not None and price > 0:
        try:
            async with session.begin_nested():
                notified = await _queue_target_hit(
                    session, listing_id, check_id, price, currency, method
                )
        except Exception as e:
            # observation beats notification: the savepoint rolls back the
            # announcement, the check below still commits
            log.error(f"Target-hit enqueue failed for listing {listing_id}, price kept: {e}")
            notified = False

    await session.commit()
    return Recorded(check_id=check_id, notified=notified)


async def _announce(
    session,
    job_id: int,
    listing_id: int,
    item_id: int,
    price: Decimal | None,
    currency: str,
    status: str,
) -> None:
    """Write this observation into the hunt's log, in the same transaction.

    Two of the contract's event types come from here because this is where
    they are true: a price the hunt read, and a listing it found already over.
    """
    if status in ("sold", "ended"):
        await add_event(
            session,
            job_id,
            "warn",
            "listing_ended",
            f"Listing {status} — the slot is free again",
            {"listing_id": listing_id, "item_id": item_id},
        )
    elif price is not None:
        await add_event(
            session,
            job_id,
            "success",
            "price_found",
            f"Price read {price} {currency}",
            {"listing_id": listing_id, "item_id": item_id, "price": str(price)},
        )


async def _queue_target_hit(
    session,
    listing_id: int,
    check_id: int,
    price: Decimal,
    currency: str,
    method: str,
) -> bool:
    """Decide and queue the target-hit notification. True when one was queued."""
    row = (
        (
            await session.execute(
                select(
                    Listings.url.label("listing_url"),
                    Watches.id.label("watch_id"),
                    Watches.user_id.label("user_id"),
                    Watches.target_price.label("target_price"),
                    Items.id.label("item_id"),
                    Items.name.label("item_name"),
                    Sites.id.label("site_id"),
                    Sites.name.label("site_name"),
                )
                .join(Watches, Watches.id == Listings.watch_id)
                .join(Items, Items.id == Listings.item_id)
                .join(Sites, Sites.id == Listings.site_id)
                .where(Listings.id == listing_id)
                .where(Watches.notify)
                .where(Watches.target_price.is_not(None))
                .limit(1)
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return False  # notifications off for this watch, or no target set

    # The watch's best price across its active listings ignoring the check
    # just written — the "was this watch already met?" half of the edge test.
    # Unbelieved readings are excluded here too: a $4.49 nobody trusts must
    # not make the watch look already-met and silence the real crossing.
    latest_per_listing = (
        select(PriceChecks.listing_id, PriceChecks.price)
        .distinct(PriceChecks.listing_id)
        .join(Listings, Listings.id == PriceChecks.listing_id)
        .where(Listings.watch_id == row["watch_id"])
        .where(Listings.active)
        .where(PriceChecks.price > 0)
        .where(PriceChecks.confirmed)
        .where(PriceChecks.id != check_id)
        .order_by(PriceChecks.listing_id, PriceChecks.checked_at.desc())
        .subquery()
    )
    best_before = await session.scalar(select(func.min(latest_per_listing.c.price)))

    payload = target_hit_payload(row, best_before, price, currency, listing_id, method)
    if payload is None:
        return False

    # Take the cooldown and queue in the same breath: the conditional UPDATE
    # is what makes "told" a fact rather than an intention, and the stamp
    # lands at enqueue because the outbox owns delivery from there on.
    taken = await session.scalar(
        update(Watches)
        .where(Watches.id == row["watch_id"])
        .where(
            (Watches.last_notified_at.is_(None))
            | (Watches.last_notified_at < datetime.now(UTC) - COOLDOWN)
        )
        .values(last_notified_at=datetime.now(UTC))
        .returning(Watches.id)
    )
    if taken is None:
        log.info(f"Watch {row['watch_id']} hit its target but is still in cooldown")
        return False

    session.add(NotificationOutbox(user_id=row["user_id"], event="target.hit", payload=payload))
    log.info(f"Queued target-hit notification for listing {listing_id}")
    return True
