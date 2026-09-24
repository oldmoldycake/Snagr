"""max_listings is one slot budget per watch across every site and hunt, not
a per-site quota. The discovery prompt spells that out and addresses the
model in open slots (the cap minus what the watch already holds), so a watch
with three sites cannot fill 3x its cap, and a later hunt cannot add another
round on top.

A hunt that finds its watch full can only trade up: the prompt shows the
tracked listings weakest first, and save_listing makes each trade — for the
weakest, which code picks — and refuses any save that would over-fill the
watch, and any trade that is not a trade up. Those tests need the real
Postgres (the same harness as test_jobs_db.py); the prompt tests do not.
"""

import asyncio
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import tools
from conftest import OPEN_JOB_INDEX, SITE_BASE_URL, unit_runtime
from database import (
    AsyncSessionLocal,
    Base,
    Categories,
    Items,
    JobEvents,
    Jobs,
    Listings,
    PriceChecks,
    Sites,
    User,
    Watches,
    engine,
    get_known_listing_urls,
)
from prompt import generate_prompt
from sqlalchemy import select, text, update


def _prompt(**overrides) -> str:
    args = {
        "watch_id": 1,
        "site_id": 2,
        "site_name": "TestBay",
        "item_id": 3,
        "item_name": "Widget",
        "base_url": "https://example.test",
        "criteria": None,
        "selection_mode": "cheapest",
        "max_listings": 5,
        "allow_reproductions": False,
        **overrides,
    }
    return asyncio.run(generate_prompt(**args))


def test_the_budget_is_stated_as_a_watch_wide_cap():
    prompt = _prompt(tracked_listings=3)
    assert "TRACKING SLOTS: 2 open" in prompt
    assert "at most 5 listing(s) IN TOTAL" in prompt
    assert "not 5 per site" in prompt
    assert "3 slot(s) are already filled" in prompt
    assert "Save at most 2 new listing(s) this run" in prompt


def test_selection_and_stop_rules_count_open_slots_not_the_cap():
    cheapest = _prompt(tracked_listings=3)
    assert "keep the 2 cheapest listing(s)" in cheapest
    assert "keep the 5 cheapest" not in cheapest
    assert "(up to 2)" in cheapest
    assert "(up to 5)" not in cheapest

    best_match = _prompt(tracked_listings=3, selection_mode="best_match", criteria="boxed")
    assert "save exactly 2 listing(s)" in best_match
    assert "Only save fewer than 2" in best_match
    assert "exactly 5" not in best_match


def test_an_untouched_watch_has_every_slot_open():
    prompt = _prompt()
    assert "TRACKING SLOTS: 5 open" in prompt
    assert "0 slot(s) are already filled" in prompt
    assert "keep the 5 cheapest listing(s)" in prompt


def test_an_over_full_watch_clamps_to_zero_open():
    # watches over-filled before the cap was enforced must not go negative
    prompt = _prompt(tracked_listings=39)
    assert "TRACKING SLOTS: 0 open" in prompt
    assert "-34" not in prompt


def test_leftover_candidates_are_not_logged_as_rejections():
    # logging them would land them in PREVIOUSLY REJECTED and hide them from
    # the hunt that finally has a free slot
    prompt = _prompt(tracked_listings=3)
    assert "Leftover good candidates are NOT rejections" in prompt
    assert "do not log them with `log_listing_check`" in prompt


# --- swap hunts: the prompt -------------------------------------------------


def _row(listing_id, price, score, site="TestBay"):
    return {
        "listing_id": listing_id,
        "site_name": site,
        "title": f"Widget #{listing_id}",
        "price": Decimal(price) if price is not None else None,
        "match_score": score,
    }


TRACKED = [
    _row(1, "40.00", 90),
    _row(2, "55.00", 60),
    _row(3, None, 70, site="OtherBay"),
    _row(4, "55.00", 40),
]


def _order(prompt: str) -> list[str]:
    block = prompt.split("TRACKED LISTINGS")[1].split("Save a candidate")[0]
    return re.findall(r"listing_id=(\d+)", block)


def test_a_swap_hunt_shows_tracked_listings_instead_of_slots():
    prompt = _prompt(tracked_listings=4, max_listings=4, swap_listings=TRACKED)
    assert "TRACKED LISTINGS: all 4 slot(s) are filled" in prompt
    assert "TRACKING SLOTS" not in prompt
    assert "keep the 0 cheapest" not in prompt
    assert "code trades it for\n  the weakest tracked listing" in prompt
    assert "The reply names the new weakest listing" in prompt
    assert "good candidates are NOT rejections" in prompt
    assert "Stop once nothing left on the site beats the weakest tracked listing" in prompt


def test_cheapest_mode_lists_the_highest_price_first_and_unpriced_before_all():
    prompt = _prompt(tracked_listings=4, max_listings=4, swap_listings=TRACKED)
    # 3 has no believed price at all; 2 and 4 tie on price and fall to id
    assert _order(prompt) == ["3", "2", "4", "1"]
    assert "listing_id=3 · OtherBay · no confirmed price · match 70" in prompt
    assert "listing_id=2 · TestBay · $55.00 · match 60" in prompt
    assert "any believable price (the weakest has no confirmed price)" in prompt


def test_cheapest_mode_names_the_price_to_beat():
    priced = [row for row in TRACKED if row["price"] is not None]
    prompt = _prompt(tracked_listings=3, max_listings=3, swap_listings=priced)
    assert _order(prompt) == ["2", "4", "1"]
    assert "strictly lower than $55.00" in prompt


def test_best_match_mode_lists_the_lowest_score_first_price_breaking_ties():
    tied = [*TRACKED, _row(5, "70.00", 40)]
    prompt = _prompt(
        tracked_listings=5,
        max_listings=5,
        selection_mode="best_match",
        criteria="boxed",
        swap_listings=tied,
    )
    # 5 and 4 share the lowest score; the dearer of the two is the weaker
    assert _order(prompt) == ["5", "4", "2", "3", "1"]
    assert "a higher match_score than 40" in prompt


# --- swap hunts: what code allows ------------------------------------------

_ALL_TABLES = ", ".join(t.name for t in Base.metadata.sorted_tables)

_LOOP = asyncio.new_event_loop()


def db(coro):
    """Run one coroutine on the module's shared event loop (asyncpg
    connections are loop-bound)."""
    return _LOOP.run_until_complete(coro)


async def _create_schema():
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f"DROP TABLE IF EXISTS {table.name} CASCADE"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(OPEN_JOB_INDEX))


async def _drop_schema():
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(text(f"DROP TABLE IF EXISTS {table.name} CASCADE"))


@pytest.fixture(scope="module")
def schema():
    db(_create_schema())
    yield
    db(_drop_schema())
    db(engine.dispose())
    _LOOP.close()


@pytest.fixture
def clean(schema):
    yield
    db(_truncate())


async def _truncate():
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {_ALL_TABLES} RESTART IDENTITY CASCADE"))


async def _seed_full_watch(selection_mode: str = "cheapest", prices=("50.00", "80.00")) -> dict:
    """A watch whose every slot is taken: one listing per price, each with a
    confirmed check and its next recheck queued, plus the running hunt job
    the swap happens under."""
    async with AsyncSessionLocal() as session:
        user = User(email="owner@test.local")
        category = Categories(name="Games", slug="games")
        site = Sites(name="TestBay", base_url=SITE_BASE_URL)
        session.add_all([user, category, site])
        await session.flush()
        item = Items(category_id=category.id, name="Widget")
        session.add(item)
        await session.flush()
        watch = Watches(
            user_id=user.id,
            item_id=item.id,
            max_listings=len(prices),
            selection_mode=selection_mode,
        )
        session.add(watch)
        await session.flush()
        listing_ids = []
        for n, price in enumerate(prices):
            listing = Listings(
                watch_id=watch.id,
                item_id=item.id,
                site_id=site.id,
                url=f"{SITE_BASE_URL}/tracked-{n}",
                title=f"Tracked {n}",
                active=True,
                match_score=70,
            )
            session.add(listing)
            await session.flush()
            session.add(
                PriceChecks(
                    listing_id=listing.id,
                    price=Decimal(price),
                    currency="USD",
                    in_stock=True,
                    status="ok",
                    method="llm",
                    checked_at=datetime.now(UTC),
                )
            )
            session.add(
                Jobs(
                    kind="recheck",
                    watch_id=watch.id,
                    item_id=item.id,
                    site_id=site.id,
                    listing_id=listing.id,
                )
            )
            listing_ids.append(listing.id)
        hunt = Jobs(
            kind="hunt",
            status="running",
            watch_id=watch.id,
            item_id=item.id,
            site_id=site.id,
            payload={"swap": True},
        )
        session.add(hunt)
        await session.flush()
        ids = {
            "watch_id": watch.id,
            "item_id": item.id,
            "site_id": site.id,
            "job_id": hunt.id,
            "listings": listing_ids,
        }
        await session.commit()
        return ids


def _runtime(ids, swap: bool = True):
    return unit_runtime(
        watch_id=ids["watch_id"],
        item_id=ids["item_id"],
        site_id=ids["site_id"],
        job_id=ids["job_id"],
        swap=swap,
    )


def _save(runtime, url=f"{SITE_BASE_URL}/candidate", price=None, match_score=85):
    return db(
        tools.save_listing(
            url=url,
            title="Widget — better",
            match_score=match_score,
            match_summary="fits, no repro flags",
            price=price,
            runtime=runtime,
        )
    )


def _traded_id(result) -> int:
    """The listing a TRADED: reply saved."""
    assert result.startswith("TRADED:"), result
    return int(re.search(r"saved as listing (\d+)", result).group(1))


async def _listings(watch_id) -> dict[int, Listings]:
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(Listings).where(Listings.watch_id == watch_id))).all()
        return {row.Listings.id: row.Listings for row in rows}


def _active(ids) -> set[int]:
    return {lid for lid, row in db(_listings(ids["watch_id"])).items() if row.active}


async def _events(job_id) -> list[JobEvents]:
    async with AsyncSessionLocal() as session:
        return list(
            (
                await session.execute(
                    select(JobEvents).where(JobEvents.job_id == job_id).order_by(JobEvents.seq)
                )
            ).scalars()
        )


async def _checks(listing_id) -> list[PriceChecks]:
    async with AsyncSessionLocal() as session:
        return list(
            (
                await session.execute(
                    select(PriceChecks).where(PriceChecks.listing_id == listing_id)
                )
            ).scalars()
        )


async def _pending_recheck(listing_id) -> bool:
    async with AsyncSessionLocal() as session:
        return (
            await session.scalar(
                select(Jobs.id)
                .where(Jobs.kind == "recheck")
                .where(Jobs.listing_id == listing_id)
                .where(Jobs.status == "pending")
            )
        ) is not None


@pytest.mark.usefixtures("clean")
class TestSwaps:
    def test_a_full_watch_refuses_a_save_without_a_replacement(self):
        ids = db(_seed_full_watch())
        result = _save(_runtime(ids, swap=False))
        assert result.startswith("SLOTS FULL:")
        assert _active(ids) == set(ids["listings"])

    def test_a_swap_save_needs_its_price(self):
        ids = db(_seed_full_watch())
        result = _save(_runtime(ids))
        assert result.startswith("Error: every slot of this watch is filled")
        assert _active(ids) == set(ids["listings"])

    def test_cheapest_mode_refuses_a_replacement_that_is_not_cheaper(self):
        ids = db(_seed_full_watch())
        runtime = _runtime(ids)
        weakest = ids["listings"][1]  # $80
        for price in (95, 80):
            result = _save(runtime, price=price)
            assert result.startswith("SLOTS FULL:"), result
            assert "strictly cheaper" in result
            assert f"listing {weakest}, the weakest tracked" in result
        assert _active(ids) == set(ids["listings"])
        assert db(_pending_recheck(weakest))
        assert len(db(_listings(ids["watch_id"]))) == 2

    def test_a_cheaper_replacement_trades_for_the_weakest_and_keeps_n_tracked(self):
        ids = db(_seed_full_watch())
        runtime = _runtime(ids)
        kept, weakest = ids["listings"]  # $50, $80
        new_id = _traded_id(_save(runtime, price=60))

        assert _active(ids) == {kept, new_id}
        replaced = db(_listings(ids["watch_id"]))[weakest]
        assert replaced.inactive_reason == "replaced"
        assert not db(_pending_recheck(weakest))
        assert db(_pending_recheck(new_id))
        # the price the trade was judged on is the price on record
        (check,) = db(_checks(new_id))
        assert check.price == Decimal("60.00")
        assert check.confirmed
        stats = runtime.config["configurable"]["unit"].stats
        assert stats["new_listings"] == 1
        assert stats["prices_found"] == 1

    def test_a_swap_is_told_as_an_ending_then_a_discovery(self):
        ids = db(_seed_full_watch())
        weakest = ids["listings"][1]
        new_id = _traded_id(_save(_runtime(ids), price=60))

        events = db(_events(ids["job_id"]))
        assert [e.event_type for e in events] == [
            "listing_ended",
            "listing_discovered",
            "price_found",
        ]
        ended = events[0]
        assert ended.message.startswith(f'Replaced listing #{weakest} "Tracked 1" with listing')
        assert ended.payload["reason"] == "replaced"
        assert ended.payload["listing_id"] == weakest
        assert ended.payload["replaced_by"] == new_id

    def test_a_hunt_trades_as_often_as_it_finds_better(self):
        # the site searched after another filled the watch gets its say on
        # every slot, not just one: each trade raises the bar for the next
        ids = db(_seed_full_watch())
        runtime = _runtime(ids)
        cheapest = ids["listings"][0]  # $50

        first = _save(runtime, price=60)
        first_id = _traded_id(first)
        # the listing just saved is now the weakest, and the reply says so
        assert f"The weakest tracked listing is now listing {first_id} ($60.00" in first

        second = _save(runtime, url=f"{SITE_BASE_URL}/another", price=5)
        second_id = _traded_id(second)
        assert f"in place of listing {first_id}" in second
        assert f"is now listing {cheapest} ($50.00" in second
        assert _active(ids) == {cheapest, second_id}

        third = _save(runtime, url=f"{SITE_BASE_URL}/third", price=55)
        assert third.startswith("SLOTS FULL:")
        assert _active(ids) == {cheapest, second_id}

    def test_best_match_mode_trades_on_fit_whatever_the_price(self):
        ids = db(_seed_full_watch("best_match"))
        # both fit 70; the dearer one is the weaker
        new_id = _traded_id(_save(_runtime(ids), price=500))
        assert _active(ids) == {ids["listings"][0], new_id}

    def test_best_match_mode_refuses_a_worse_fit_and_an_equal_one_that_costs_more(self):
        ids = db(_seed_full_watch("best_match"))
        runtime = _runtime(ids)
        worse = _save(runtime, price=10, match_score=60)
        assert worse.startswith("SLOTS FULL: a match_score of 60 does not beat")
        equal = _save(runtime, url=f"{SITE_BASE_URL}/equal", price=90, match_score=70)
        assert equal.startswith("SLOTS FULL: a match_score of 70 does not beat")
        assert _active(ids) == set(ids["listings"])

        # as good a fit for less is a trade up
        cheaper = _save(runtime, url=f"{SITE_BASE_URL}/cheaper", price=75, match_score=70)
        assert _active(ids) == {ids["listings"][0], _traded_id(cheaper)}

    def test_a_listing_on_another_site_of_the_watch_can_be_traded(self):
        ids = db(_seed_full_watch())

        async def move_to_another_site():
            async with AsyncSessionLocal() as session:
                other = Sites(name="OtherBay", base_url="https://other.test")
                session.add(other)
                await session.flush()
                listing = await session.get(Listings, ids["listings"][1])
                listing.site_id = other.id
                await session.commit()

        db(move_to_another_site())
        new_id = _traded_id(_save(_runtime(ids), price=60))
        assert _active(ids) == {ids["listings"][0], new_id}

    def test_a_replaced_listing_comes_back_as_the_same_row_with_its_history(self):
        ids = db(_seed_full_watch())
        runtime = _runtime(ids)
        kept, weakest = ids["listings"]
        new_id = _traded_id(_save(runtime, price=60))

        # the new one sells; the old URL is found again on a later hunt
        db(tools.disable_listing(new_id, "sold", runtime=_runtime(ids, swap=False)))
        back = _save(_runtime(ids, swap=False), url=f"{SITE_BASE_URL}/tracked-1")

        assert back == weakest
        row = db(_listings(ids["watch_id"]))[weakest]
        assert row.active
        assert row.inactive_reason is None
        assert row.match_score == 85
        assert [c.price for c in db(_checks(weakest))] == [Decimal("80.00")]
        assert db(_pending_recheck(weakest))
        assert _active(ids) == {kept, weakest}

    def test_a_sold_listing_stays_terminal(self):
        ids = db(_seed_full_watch())
        sold = ids["listings"][1]
        db(tools.disable_listing(sold, "sold", runtime=_runtime(ids, swap=False)))
        result = _save(_runtime(ids, swap=False), url=f"{SITE_BASE_URL}/tracked-1")
        assert result.startswith("SKIPPED:")

    def test_a_replaced_url_is_hidden_for_a_day_then_findable(self):
        ids = db(_seed_full_watch())
        _traded_id(_save(_runtime(ids), price=60))

        known = db(get_known_listing_urls(ids["watch_id"], ids["site_id"]))
        assert f"{SITE_BASE_URL}/tracked-1" in known

        async def age_the_swap(hours: int):
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(JobEvents)
                    .where(JobEvents.event_type == "listing_ended")
                    .values(ts=datetime.now(UTC) - timedelta(hours=hours))
                )
                await session.commit()

        db(age_the_swap(23))
        assert f"{SITE_BASE_URL}/tracked-1" in db(
            get_known_listing_urls(ids["watch_id"], ids["site_id"])
        )
        db(age_the_swap(25))
        known = db(get_known_listing_urls(ids["watch_id"], ids["site_id"]))
        assert f"{SITE_BASE_URL}/tracked-1" not in known
        # every other kind of known URL is still known
        assert f"{SITE_BASE_URL}/tracked-0" in known
        assert f"{SITE_BASE_URL}/candidate" in known
