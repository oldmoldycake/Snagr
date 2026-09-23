"""HTTP layer for /api/jobs — every row of the contract's behaviour table
(docs/design/activity-page.md §4), which is what frontend/src/mocks/handlers.ts
answers.

The queue's mechanics belong to the agent (agent/tests/test_jobs_db.py); what
is pinned here is what a person can ask of it and what they are allowed to see
of it — including the two things that are easy to get subtly wrong: asking
twice never duplicates, and a job you may not see is a 404 rather than a 403.

Seeding goes through `db_session` and COMMITS, like test_sites_api.py: each
request runs on its own session, so uncommitted rows are invisible.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from app.config import settings
from app.models import Jobs, Sites, User, Watches
from sqlalchemy import select

from tests.conftest import CSRF
from tests.factories import Scenario

OWNER = {"email": "jobs@example.com", "password": "hunter2hunter2"}
STRANGER = {"email": "stranger@example.com", "password": "hunter2hunter2"}


async def _sign_in(client, creds=OWNER):
    """Register (which also signs in) and return the new user's id."""
    res = await client.post("/api/auth/register", json=creds, headers=CSRF)
    assert res.status_code == 201, res.text
    return res.json()["user"]["id"]


@asynccontextmanager
async def _seed_for(db_session, user_id):
    """Scenario bound to an already-registered user, committed on exit."""
    async with db_session() as session:
        scenario = Scenario(session)
        scenario._user = await session.get(User, user_id)
        yield scenario
        await session.commit()


async def _watched_item(client, name="Game Boy Color", sites=("eBay",)) -> dict:
    """A category linked to `sites`, and the caller watching one item in it —
    the smallest world in which the hunter has something to do."""
    cat = (await client.post("/api/categories", json={"name": "Handhelds"}, headers=CSRF)).json()
    site_ids = []
    for site_name in sites:
        body = {"name": site_name, "base_url": f"https://{site_name.lower()}.test"}
        site_ids.append((await client.post("/api/sites", json=body, headers=CSRF)).json()["id"])
    await client.put(
        f"/api/categories/{cat['id']}/sites", json={"site_ids": site_ids}, headers=CSRF
    )
    body = {"category_id": cat["id"], "name": name, "target_price": "150.00"}
    res = await client.post("/api/items", json=body, headers=CSRF)
    assert res.status_code == 201, res.text
    return res.json()


async def _watch_row(sc, user_id) -> Watches:
    """The watch POST /api/items just created, as an ORM row the factories
    can hang listings and jobs off."""
    return await sc.db.scalar(select(Watches).where(Watches.user_id == user_id))


async def _jobs(client, **params) -> list[dict]:
    res = await client.get("/api/jobs", params=params)
    assert res.status_code == 200, res.text
    return res.json()["data"]


# --- POST /api/jobs -------------------------------------------------------------


class TestEnqueue:
    async def test_a_hunt_is_queued_per_site_the_watch_searches(self, client):
        await _sign_in(client)
        item = await _watched_item(client, sites=("eBay", "Mercari"))

        res = await client.post(
            "/api/jobs",
            json={"kind": "hunt", "scope": "item", "scope_id": item["id"]},
            headers=CSRF,
        )
        assert res.status_code == 202, res.text
        queued = res.json()["data"]
        assert sorted(j["site_name"] for j in queued) == ["Mercari", "eBay"]
        assert {j["kind"] for j in queued} == {"hunt"}
        assert {j["reason"] for j in queued} == {"user"}
        assert {j["priority"] for j in queued} == {100}
        assert queued[0]["label"].startswith("Game Boy Color × ")

    async def test_asking_twice_brings_the_same_job_forward(self, client, db_session):
        """The open-job index is the design: a double-click cannot queue two
        hunts of the same pair, so there is no 409 to handle."""
        user_id = await _sign_in(client)
        item = await _watched_item(client)
        async with _seed_for(db_session, user_id) as sc:
            job = await sc.db.scalar(Jobs.__table__.select().with_only_columns(Jobs.id))
            await sc.db.execute(
                Jobs.__table__.update()
                .where(Jobs.id == job)
                .values(run_after=datetime.now(UTC) + timedelta(hours=2))
            )

        body = {"kind": "hunt", "scope": "item", "scope_id": item["id"]}
        first = (await client.post("/api/jobs", json=body, headers=CSRF)).json()["data"]
        again = (await client.post("/api/jobs", json=body, headers=CSRF)).json()["data"]

        assert [j["id"] for j in first] == [j["id"] for j in again]
        assert len(await _jobs(client, kind="hunt")) == 1
        # brought forward, not left sitting two hours out
        assert datetime.fromisoformat(again[0]["run_after"]) <= datetime.now(UTC)

    async def test_a_full_watch_has_nothing_to_hunt_for(self, client, db_session):
        """Decision 9: a watch with every slot filled costs nothing until one
        frees. An empty data is still a 202 — the request was understood."""
        user_id = await _sign_in(client)
        item = await _watched_item(client)
        async with _seed_for(db_session, user_id) as sc:
            watch = await _watch_row(sc, user_id)
            item_row = await sc.item(item["name"])
            for n in range(watch.max_listings):
                await sc.listing(watch, item_row, tag=f"full{n}")

        res = await client.post(
            "/api/jobs",
            json={"kind": "hunt", "scope": "item", "scope_id": item["id"]},
            headers=CSRF,
        )
        assert res.status_code == 202
        assert res.json()["data"] == []

    async def test_a_recheck_bumps_every_pending_check_in_scope(self, client, db_session):
        user_id = await _sign_in(client)
        item = await _watched_item(client)
        async with _seed_for(db_session, user_id) as sc:
            watch = await _watch_row(sc, user_id)
            item_row = await sc.item(item["name"])
            listing = await sc.listing(watch, item_row)
            await sc.job(
                kind="recheck",
                watch=watch,
                status="pending",
                listing_id=listing.id,
                run_after=datetime.now(UTC) + timedelta(minutes=29),
            )
            # a running check is already doing what is being asked for
            other = await sc.listing(watch, item_row, tag="running")
            await sc.job(kind="recheck", watch=watch, status="running", listing_id=other.id)

        res = await client.post(
            "/api/jobs",
            json={"kind": "recheck", "scope": "item", "scope_id": item["id"]},
            headers=CSRF,
        )
        assert res.status_code == 202, res.text
        bumped = res.json()["data"]
        assert [j["status"] for j in bumped] == ["pending"]
        assert bumped[0]["priority"] == 100
        assert datetime.fromisoformat(bumped[0]["run_after"]) <= datetime.now(UTC)

    @pytest.mark.parametrize(
        ("body", "field"),
        [
            ({"kind": "ground", "scope": "global"}, "kind"),
            ({"kind": "hunt", "scope": "everything"}, "scope"),
            ({"kind": "hunt", "scope": "item"}, "scope_id"),
        ],
    )
    async def test_a_request_that_makes_no_sense_is_a_422(self, client, body, field):
        await _sign_in(client)
        res = await client.post("/api/jobs", json=body, headers=CSRF)
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "validation_error"
        assert field in res.json()["error"]["fields"]

    async def test_asking_again_forgets_a_backoff(self, client, db_session):
        """A hunt that keeps coming back empty waits longer each time; a
        person asking is the strongest reason there is to look now."""
        user_id = await _sign_in(client)
        item = await _watched_item(client)
        async with _seed_for(db_session, user_id) as sc:
            job = await sc.db.scalar(select(Jobs))
            job.run_after = datetime.now(UTC) + timedelta(hours=4)
            job.payload = {"backoff_minutes": 240}
            job.reason = "backoff"
            job.user_id = None

        body = {"kind": "hunt", "scope": "item", "scope_id": item["id"]}
        (queued,) = (await client.post("/api/jobs", json=body, headers=CSRF)).json()["data"]

        assert queued["reason"] == "user"
        assert datetime.fromisoformat(queued["run_after"]) <= datetime.now(UTC)
        detail = (await client.get(f"/api/items/{item['id']}")).json()
        assert detail["hunt"]["backoff_minutes"] is None

    async def test_a_watch_switched_off_is_still_hunted_on_request(self, client):
        # off means "only when you press Hunt now" — this is the press
        await _sign_in(client)
        item = await _watched_item(client)
        await client.patch(f"/api/items/{item['id']}", json={"hunt": False}, headers=CSRF)

        res = await client.post(
            "/api/jobs",
            json={"kind": "hunt", "scope": "item", "scope_id": item["id"]},
            headers=CSRF,
        )
        assert res.status_code == 202
        assert [j["reason"] for j in res.json()["data"]] == ["user"]

    async def test_a_hunt_while_the_operator_has_hunting_off_is_a_409(self, client, monkeypatch):
        """HUNT_ENABLED=false: the agent claims no hunts, so queueing one
        would be a silent fake. Rechecks are still what they were."""
        await _sign_in(client)
        item = await _watched_item(client)
        monkeypatch.setattr(settings, "HUNT_ENABLED", False)

        res = await client.post(
            "/api/jobs",
            json={"kind": "hunt", "scope": "item", "scope_id": item["id"]},
            headers=CSRF,
        )
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "hunting_disabled"

        res = await client.post(
            "/api/jobs",
            json={"kind": "recheck", "scope": "item", "scope_id": item["id"]},
            headers=CSRF,
        )
        assert res.status_code == 202

    async def test_a_scope_holding_none_of_your_watches_is_a_404(self, client):
        await _sign_in(client)
        await _watched_item(client)
        res = await client.post(
            "/api/jobs", json={"kind": "hunt", "scope": "item", "scope_id": 9999}, headers=CSRF
        )
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"

    async def test_a_mutation_needs_the_csrf_header(self, client):
        await _sign_in(client)
        res = await client.post("/api/jobs", json={"kind": "hunt", "scope": "global"})
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "csrf"


# --- GET /api/jobs --------------------------------------------------------------


class TestList:
    async def test_requires_a_session(self, client):
        res = await client.get("/api/jobs")
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "unauthenticated"

    async def test_kind_and_status_take_comma_separated_lists(self, client, db_session):
        user_id = await _sign_in(client)
        async with _seed_for(db_session, user_id) as sc:
            watch = await sc.watch(await sc.item("Alpha"))
            await sc.job(watch=watch, status="done")
            await sc.job(kind="recheck", watch=watch, status="failed")
            await sc.job(kind="ground", watch=None, item_id=watch.item_id, status="pending")

        assert len(await _jobs(client, kind="hunt")) == 1
        assert len(await _jobs(client, kind="hunt,ground")) == 2
        assert len(await _jobs(client, status="done,failed")) == 2
        assert len(await _jobs(client, kind="recheck", status="done")) == 0

    async def test_a_queue_reads_forwards_and_history_backwards(self, client, db_session):
        user_id = await _sign_in(client)
        async with _seed_for(db_session, user_id) as sc:
            watch = await sc.watch(await sc.item("Alpha"))
            soon = await sc.job(watch=watch, status="pending", days_ago=0)
            later = await sc.job(
                kind="ground",
                watch=None,
                item_id=watch.item_id,
                status="pending",
                days_ago=0,
                run_after=datetime.now(UTC) + timedelta(hours=1),
            )
            old = await sc.job(kind="recheck", watch=watch, status="done", days_ago=3)
            new = await sc.job(kind="recheck", watch=watch, status="done", days_ago=1)
            ids = {"soon": soon.id, "later": later.id, "old": old.id, "new": new.id}

        queue = await _jobs(client, status="pending")
        assert [j["id"] for j in queue] == [ids["soon"], ids["later"]]

        history = await _jobs(client, status="done")
        assert [j["id"] for j in history] == [ids["new"], ids["old"]]

    async def test_another_users_work_is_simply_not_there(self, client, make_client, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
        await _sign_in(client)
        await _watched_item(client)

        stranger = await make_client()
        await _sign_in(stranger, STRANGER)
        assert await _jobs(stranger) == []

    async def test_item_id_narrows_to_one_item(self, client, db_session):
        user_id = await _sign_in(client)
        async with _seed_for(db_session, user_id) as sc:
            alpha = await sc.watch(await sc.item("Alpha"))
            beta = await sc.watch(await sc.item("Beta"))
            await sc.job(watch=alpha)
            await sc.job(watch=beta)
            wanted = alpha.item_id

        assert [j["item_name"] for j in await _jobs(client, item_id=wanted)] == ["Alpha"]


# --- GET /api/jobs/summary ------------------------------------------------------


class TestSummary:
    async def test_the_numbers_the_presence_sentence_reads(self, client, db_session):
        user_id = await _sign_in(client)
        async with _seed_for(db_session, user_id) as sc:
            item = await sc.item("Alpha")
            watch = await sc.watch(item)
            tracked = await sc.listing(watch, item)
            queued = await sc.listing(watch, item, tag="queued")
            await sc.job(watch=watch, status="running")
            await sc.job(kind="recheck", watch=watch, status="running", listing_id=tracked.id)
            await sc.job(
                kind="recheck",
                watch=watch,
                status="pending",
                listing_id=queued.id,
                days_ago=0,
                run_after=datetime.now(UTC) + timedelta(minutes=12),
            )
            await sc.job(watch=watch, status="done", days_ago=0, site_id=(await sc.site("B")).id)

        summary = (await client.get("/api/jobs/summary")).json()
        assert summary["hunts_running"] == 1
        assert summary["checks_running"] == 1
        assert summary["checks_pending"] == 1
        assert summary["listings_watched"] == 2
        assert summary["hunts_today"] == 1
        assert summary["last_hunt"]["status"] == "done"
        assert datetime.fromisoformat(summary["next_check_at"]) > datetime.now(UTC)

    async def test_a_paused_site_is_everyones_news(self, client, make_client, monkeypatch, sc):
        """Sites are shared, so the banner shows to every viewer — unlike a
        job, which belongs to one watch."""
        from app.config import settings

        monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
        await _sign_in(client)
        site = await sc.site("eBay")
        site.paused_until = datetime.now(UTC) + timedelta(hours=1)
        site.paused_reason = "5 consecutive read errors: challenge page"
        await sc.commit()

        stranger = await make_client()
        await _sign_in(stranger, STRANGER)
        for who in (client, stranger):
            (paused,) = (await who.get("/api/jobs/summary")).json()["paused_sites"]
            assert paused["site_name"] == "eBay"
            assert paused["paused_reason"].endswith("challenge page")

    async def test_a_lifted_pause_leaves_the_banner(self, client, sc):
        await _sign_in(client)
        site = await sc.site("eBay")
        site.paused_until = datetime.now(UTC) - timedelta(minutes=1)
        site.paused_reason = "5 consecutive read errors"
        await sc.commit()

        assert (await client.get("/api/jobs/summary")).json()["paused_sites"] == []


# --- GET /api/jobs/{id} and its events ------------------------------------------


class TestDetail:
    async def test_a_job_you_may_not_see_is_a_404_not_a_403(
        self, client, make_client, monkeypatch, db_session
    ):
        from app.config import settings

        monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
        user_id = await _sign_in(client)
        async with _seed_for(db_session, user_id) as sc:
            job = await sc.job(watch=await sc.watch(await sc.item("Alpha")))
            job_id = job.id

        stranger = await make_client()
        await _sign_in(stranger, STRANGER)
        for path in (f"/api/jobs/{job_id}", f"/api/jobs/{job_id}/events"):
            res = await stranger.get(path)
            assert res.status_code == 404, path
            assert res.json()["error"]["code"] == "not_found"

    async def test_an_unknown_id_is_the_same_404(self, client):
        await _sign_in(client)
        res = await client.get("/api/jobs/9999")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"

    async def test_events_come_back_in_order_after_a_cursor(self, client, db_session):
        user_id = await _sign_in(client)
        async with _seed_for(db_session, user_id) as sc:
            job = await sc.job(watch=await sc.watch(await sc.item("Alpha")), status="running")
            for seq in (1, 2, 3):
                await sc.job_event(job, seq, message=f"line {seq}")
            job_id = job.id

        body = (await client.get(f"/api/jobs/{job_id}/events")).json()
        assert [e["seq"] for e in body["data"]] == [1, 2, 3]

        body = (await client.get(f"/api/jobs/{job_id}/events?after_seq=2")).json()
        assert [e["message"] for e in body["data"]] == ["line 3"]

    async def test_a_check_has_no_log_to_read(self, client, db_session):
        # its whole output is the price check it wrote
        user_id = await _sign_in(client)
        async with _seed_for(db_session, user_id) as sc:
            job = await sc.job(kind="recheck", watch=await sc.watch(await sc.item("Alpha")))
            job_id = job.id

        assert (await client.get(f"/api/jobs/{job_id}/events")).json()["data"] == []

    async def test_an_oversized_limit_is_a_422(self, client, db_session):
        user_id = await _sign_in(client)
        async with _seed_for(db_session, user_id) as sc:
            job = await sc.job(watch=await sc.watch(await sc.item("Alpha")))
            job_id = job.id

        res = await client.get(f"/api/jobs/{job_id}/events?limit=501")
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "validation_error"


# --- POST /api/jobs/{id}/cancel -------------------------------------------------


class TestCancel:
    async def test_cancelling_a_running_hunt_says_who_did_it(self, client, db_session):
        user_id = await _sign_in(client)
        async with _seed_for(db_session, user_id) as sc:
            job = await sc.job(watch=await sc.watch(await sc.item("Alpha")), status="running")
            job_id = job.id

        res = await client.post(f"/api/jobs/{job_id}/cancel", headers=CSRF)
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "cancelled"

        events = (await client.get(f"/api/jobs/{job_id}/events")).json()["data"]
        assert [(e["level"], e["message"]) for e in events] == [("warn", "Cancelled by you")]

    async def test_cancelling_a_pending_hunt_writes_no_epitaph(self, client, db_session):
        # nothing was happening, so there is nothing to tell the log
        user_id = await _sign_in(client)
        async with _seed_for(db_session, user_id) as sc:
            job = await sc.job(watch=await sc.watch(await sc.item("Alpha")), status="pending")
            job_id = job.id

        assert (await client.post(f"/api/jobs/{job_id}/cancel", headers=CSRF)).status_code == 200
        assert (await client.get(f"/api/jobs/{job_id}/events")).json()["data"] == []

    async def test_a_check_cannot_be_cancelled(self, client, db_session):
        user_id = await _sign_in(client)
        async with _seed_for(db_session, user_id) as sc:
            job = await sc.job(
                kind="recheck", watch=await sc.watch(await sc.item("Alpha")), status="running"
            )
            job_id = job.id

        res = await client.post(f"/api/jobs/{job_id}/cancel", headers=CSRF)
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "validation_error"

    async def test_a_finished_job_is_a_409(self, client, db_session):
        user_id = await _sign_in(client)
        async with _seed_for(db_session, user_id) as sc:
            job = await sc.job(watch=await sc.watch(await sc.item("Alpha")), status="done")
            job_id = job.id

        res = await client.post(f"/api/jobs/{job_id}/cancel", headers=CSRF)
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "job_finished"

    async def test_the_hunters_own_work_is_admin_only(self, client, db_session):
        """A `ground` job has no watch behind it, so nobody owns it — the same
        rule system runs had. Permission is checked before state."""
        user_id = await _sign_in(client)
        async with _seed_for(db_session, user_id) as sc:
            item = await sc.item("Alpha")
            await sc.watch(item)  # so the caller can SEE it
            job = await sc.job(kind="ground", watch=None, item_id=item.id, status="running")
            job_id = job.id

        # the first registered user is the admin, so demote them to test this
        async with db_session() as session:
            user = await session.get(User, user_id)
            user.role = "user"
            await session.commit()

        res = await client.post(f"/api/jobs/{job_id}/cancel", headers=CSRF)
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "forbidden"


# --- PATCH /api/sites/{id} — lifting a pause ------------------------------------


class TestResumeSite:
    async def test_null_lifts_the_pause_and_wakes_its_queue(self, client, db_session, sc):
        user_id = await _sign_in(client)
        site = await sc.site("eBay")
        site.paused_until = datetime.now(UTC) + timedelta(hours=1)
        site.paused_reason = "5 consecutive read errors: challenge page"
        site.consecutive_errors = 5
        watch = await sc.watch(await sc.item("Alpha"), user=await sc.db.get(User, user_id))
        waiting = await sc.job(
            watch=watch,
            status="pending",
            site_id=site.id,
            reason="paused",
            run_after=site.paused_until,
        )
        site_id, job_id = site.id, waiting.id
        await sc.commit()

        res = await client.patch(f"/api/sites/{site_id}", json={"paused_until": None}, headers=CSRF)
        assert res.status_code == 200, res.text
        assert res.json()["paused_until"] is None
        assert res.json()["paused_reason"] is None

        async with db_session() as session:
            refreshed = await session.get(Sites, site_id)
            # the counter goes too: leaving it at the threshold would trip the
            # breaker again on the very next failed read
            assert refreshed.consecutive_errors == 0
            job = await session.get(Jobs, job_id)
            assert job.run_after <= datetime.now(UTC)
            assert job.reason == "sweep"

    async def test_any_other_value_is_refused(self, client, sc):
        await _sign_in(client)
        site = await sc.site("eBay")
        site_id = site.id
        await sc.commit()

        res = await client.patch(
            f"/api/sites/{site_id}",
            json={"paused_until": "2026-01-01T00:00:00Z"},
            headers=CSRF,
        )
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "validation_error"
        assert "paused_until" in res.json()["error"]["fields"]
