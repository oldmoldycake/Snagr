"""Builders for the graph every aggregates test needs.

An API "item" is really five tables deep — user -> watch -> listing ->
price_checks, hanging off a shared item/category/site catalog. Spelling that out
per test would bury the one line that actually matters, so `Scenario` creates the
scaffolding lazily with sane defaults and lets each test override only the part
it is pinning down.

Typical use (the `scenario` fixture in conftest hands you one):

    item = await sc.item("Alpha")
    watch = await sc.watch(item, target_price="85.00")
    listing = await sc.listing(watch, item)
    await sc.checks(listing, (20, "100.00"), (10, "80.00"))   # (days_ago, price)

    result = await price_drops(sc.db, sc.user_id, "30d", 10)

Times are always expressed as "days ago" so tests read as a story rather than a
pile of datetime arithmetic. `sc.now` is frozen at construction, so a test that
seeds "10 days ago" and a service that computes "30 days ago" agree.

Prices are passed as strings ("100.00") and stored as Decimal, matching the
contract's decimal-string rule. Pass None for an unpriced check — the agent
writes those for sold/unavailable listings.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models import Categories, Items, Listings, PriceChecks, Sites, User, Watches


class Scenario:
    """Lazily-built fixture graph bound to one session.

    Everything defaults to the same user, category and site so tests only name
    what they care about. `other_user()` exists for the isolation tests, which
    are the reason every aggregate query joins through `watches`.
    """

    def __init__(self, session):
        self.db = session
        self.now = datetime.now(UTC)
        self._user = None
        self._other_user = None
        self._category = None
        self._site = None

    # --- time ----------------------------------------------------------------

    def ago(self, days: float) -> datetime:
        """A timestamp `days` before this scenario was created."""
        return self.now - timedelta(days=days)

    # --- lazily-created singletons -------------------------------------------

    async def user(self) -> User:
        if self._user is None:
            self._user = User(email="owner@test.local")
            self.db.add(self._user)
            await self.db.flush()
        return self._user

    async def other_user(self) -> User:
        """A second account, for proving one user can't see another's data."""
        if self._other_user is None:
            self._other_user = User(email="stranger@test.local")
            self.db.add(self._other_user)
            await self.db.flush()
        return self._other_user

    async def category(self, name="Cameras", slug=None) -> Categories:
        if name == "Cameras":
            if self._category is None:
                self._category = Categories(name=name, slug=slug or name.lower())
                self.db.add(self._category)
                await self.db.flush()
            return self._category
        # a named category is always a new one — used by the scoping tests
        cat = Categories(name=name, slug=slug or name.lower())
        self.db.add(cat)
        await self.db.flush()
        return cat

    async def site(self, name="TestBay") -> Sites:
        if name == "TestBay":
            if self._site is None:
                self._site = Sites(name=name, base_url="https://example.test")
                self.db.add(self._site)
                await self.db.flush()
            return self._site
        site = Sites(name=name, base_url=f"https://{name.lower()}.test")
        self.db.add(site)
        await self.db.flush()
        return site

    @property
    def user_id(self) -> int:
        """Only valid after `await sc.user()` — most helpers create it for you."""
        return self._user.id

    # --- graph builders ------------------------------------------------------

    async def item(self, name="Alpha", category=None, days_ago=200) -> Items:
        row = Items(
            category_id=(category or await self.category()).id,
            name=name,
            created_at=self.ago(days_ago),
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def watch(self, item, target_price=None, days_ago=200, user=None) -> Watches:
        """One user's interest in an item. `days_ago` drives the tracked_items tile."""
        row = Watches(
            user_id=(user or await self.user()).id,
            item_id=item.id,
            target_price=Decimal(target_price) if target_price is not None else None,
            created_at=self.ago(days_ago),
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def listing(self, watch, item, tag=None, active=True,
                      site=None, title=None, days_ago=200) -> Listings:
        """A marketplace listing. `active=False` must be invisible to every rollup."""
        tag = tag or f"l{id(watch)}-{item.id}-{active}"
        row = Listings(
            watch_id=watch.id,
            item_id=item.id,
            site_id=(site or await self.site()).id,
            url=f"https://example.test/{tag}",
            title=title or f"listing {tag}",
            active=active,
            created_at=self.ago(days_ago),
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def checks(self, listing, *points, currency="USD", in_stock=True):
        """Record price checks as (days_ago, price) pairs, e.g. (20, "100.00").

        Pass price=None for an unpriced check — every aggregate must skip those
        rather than treat them as zero.
        """
        for days_ago, price in points:
            self.db.add(PriceChecks(
                listing_id=listing.id,
                price=Decimal(price) if price is not None else None,
                currency=currency,
                in_stock=in_stock,
                status=None if price is not None else "sold",
                checked_at=self.ago(days_ago),
            ))
        await self.db.flush()

    # --- convenience ---------------------------------------------------------

    async def tracked(self, name="Alpha", target_price=None, category=None,
                      watch_days_ago=200, user=None):
        """item + watch in one call, for tests that don't care about the split."""
        it = await self.item(name, category=category)
        w = await self.watch(it, target_price=target_price,
                             days_ago=watch_days_ago, user=user)
        return it, w

    async def commit(self):
        await self.db.commit()
