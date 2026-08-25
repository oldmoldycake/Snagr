"""Vision surfaces against the Phase-4 oracle (frontend/src/mocks/handlers.ts):
review queue, reference library, image proxy, thresholds, and listing
authenticity — status codes and error.code asserted exactly. The off-mode
(empty lists / 503 vision_unavailable) is the one behavior the mock can't
express and is pinned here instead.

The sidecar is faked at the HTTP layer: `sidecar` swaps httpx.AsyncClient
for a MockTransport-backed factory (explicit transports — the ASGI test
clients — pass through untouched), recording every request so tests can
prove a rescore fired without any live sidecar.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
import pytest
from app.config import settings
from app.models import Items, User, VisionListingImages, VisionReferences
from sqlalchemy import select

from tests.conftest import CSRF
from tests.factories import Scenario

OWNER = {"email": "vision@example.com", "password": "hunter2hunter2"}
OWNER_2 = {"email": "owner2@example.com", "password": "hunter2hunter2"}
PEER = {"email": "peer@example.com", "password": "hunter2hunter2"}

NOW = datetime.now(UTC)


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


@pytest.fixture
def vision_on(monkeypatch):
    monkeypatch.setattr(settings, "VISION_SIDECAR_URL", "http://vision.test")


class SidecarStub:
    """Answers the sidecar's routes; records every request it saw."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.rescore_fails = False
        self.upload_response = {
            "id": 4242,
            "item_id": 0,  # tests overwrite per call
            "label": "real",
            "variant_tag": None,
            "provenance": "upload",
            "object_key": "uploadedkey",
            "created_at": NOW.isoformat(),
        }

    def rescored_items(self) -> list[str]:
        return [
            r.url.path.removeprefix("/rescore/")
            for r in self.requests
            if r.url.path.startswith("/rescore/")
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.startswith("/rescore/"):
            if self.rescore_fails:
                return httpx.Response(500, json={"detail": "boom"})
            return httpx.Response(200, json={"rescored": 1})
        if request.url.path == "/references":
            return httpx.Response(201, json=self.upload_response)
        if request.url.path.startswith("/images/"):
            return httpx.Response(
                200, content=b"jpeg-bytes", headers={"content-type": "image/jpeg"}
            )
        return httpx.Response(404, json={"detail": "no such route"})


@pytest.fixture
def sidecar(monkeypatch):
    stub = SidecarStub()
    real_client = httpx.AsyncClient

    def _factory(**kwargs):
        # only the app's internal clients (no explicit transport) hit the stub;
        # the ASGI test clients pass their transport and go through untouched
        if "transport" not in kwargs:
            kwargs["transport"] = httpx.MockTransport(stub.handler)
        return real_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)
    return stub


async def _queue_graph(db_session, owner_id, **capture_overrides):
    """item + owner's watch + scan + one suggested capture; (item, entry) ids."""
    async with _seed_for(db_session, owner_id) as sc:
        item, watch = await sc.tracked("Emerald")
        scan = await sc.scan(
            watch, item, url="https://market.test/l1", llm_read="suspect", verdict="leans_fake"
        )
        capture = await sc.capture(scan, **capture_overrides)
        return item.id, capture.id


# --- review queue ---------------------------------------------------------------


async def test_queue_requires_a_session(client, vision_on):
    res = await client.get("/api/vision/review-queue")
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "unauthenticated"


async def test_queue_is_scoped_to_the_capturing_user(
    client, make_client, monkeypatch, db_session, vision_on
):
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
    await _sign_in(client)  # admin (first registrant)
    peer_client = await make_client()
    peer_id = await _sign_in(peer_client, PEER)

    item_id, entry_id = await _queue_graph(db_session, peer_id, fake_confidence="0.82")

    # the capturer sees their entry, with the full shape
    body = (await peer_client.get("/api/vision/review-queue")).json()
    assert body["meta"]["total"] == 1
    (entry,) = body["data"]
    assert entry["id"] == entry_id
    assert entry["item_id"] == item_id
    assert entry["item_name"] == "Emerald"
    assert entry["suggested_label"] == "fake"
    assert entry["confidence"] == "0.82"
    assert entry["llm_authenticity_read"] == "suspect"
    assert entry["image_url"].startswith("/api/vision/images/")

    # admins included (D-V11): you review what YOUR hunts captured — not theirs
    assert (await client.get("/api/vision/review-queue")).json()["meta"]["total"] == 0

    # item_id filter answers only that item
    filtered = (
        await peer_client.get("/api/vision/review-queue", params={"item_id": item_id + 1})
    ).json()
    assert filtered["meta"]["total"] == 0


async def test_queue_shows_the_real_side_confidence_for_real_suggestions(
    client, db_session, vision_on
):
    owner_id = await _sign_in(client)
    await _queue_graph(db_session, owner_id, suggested_label="real", fake_confidence="0.05")

    (entry,) = (await client.get("/api/vision/review-queue")).json()["data"]
    assert entry["suggested_label"] == "real"
    assert entry["confidence"] == "0.95"  # the confidence BACKING the suggestion


# --- confirm --------------------------------------------------------------------


async def test_confirm_unknown_and_foreign_entries_404(
    client, make_client, monkeypatch, db_session, vision_on, sidecar
):
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
    await _sign_in(client)
    peer_client = await make_client()
    peer_id = await _sign_in(peer_client, PEER)
    _, entry_id = await _queue_graph(db_session, peer_id)

    for target in (99999, entry_id):  # unknown, and another user's (hidden ≡ nonexistent)
        res = await client.post(
            f"/api/vision/review-queue/{target}/confirm", json={"label": "real"}, headers=CSRF
        )
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"


async def test_confirm_validates_the_label(client, db_session, vision_on, sidecar):
    owner_id = await _sign_in(client)
    _, entry_id = await _queue_graph(db_session, owner_id)

    res = await client.post(
        f"/api/vision/review-queue/{entry_id}/confirm", json={"label": "genuine"}, headers=CSRF
    )
    assert res.status_code == 422
    body = res.json()["error"]
    assert body["code"] == "validation_error"
    assert "label" in body["fields"]


async def test_confirm_creates_a_communal_reference_and_fires_a_rescore(
    client, db_session, vision_on, sidecar
):
    owner_id = await _sign_in(client)
    item_id, entry_id = await _queue_graph(db_session, owner_id, suggested_label="fake")

    # the label may flip the suggestion; the variant tag rides along
    res = await client.post(
        f"/api/vision/review-queue/{entry_id}/confirm",
        json={"label": "real", "variant_tag": "alternate art"},
        headers=CSRF,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["label"] == "real"
    assert body["variant_tag"] == "alternate art"
    assert body["provenance"] == "human"
    assert body["source_listing_url"] == "https://market.test/l1"  # confirmer captured it

    async with db_session() as session:
        reference = (await session.execute(select(VisionReferences))).scalar_one()
        assert reference.confirmed_by == owner_id
        image = (await session.execute(select(VisionListingImages))).scalar_one()
        assert image.review_state == "confirmed"
        assert image.reference_id == reference.id

    assert sidecar.rescored_items() == [str(item_id)]

    # a second confirm finds the entry already reviewed
    res = await client.post(
        f"/api/vision/review-queue/{entry_id}/confirm", json={"label": "real"}, headers=CSRF
    )
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "already_reviewed"


async def test_confirm_succeeds_even_when_the_rescore_fails(client, db_session, vision_on, sidecar):
    owner_id = await _sign_in(client)
    _, entry_id = await _queue_graph(db_session, owner_id)
    sidecar.rescore_fails = True

    res = await client.post(
        f"/api/vision/review-queue/{entry_id}/confirm", json={"label": "fake"}, headers=CSRF
    )
    assert res.status_code == 201  # the mutation is the source of truth


# --- discard --------------------------------------------------------------------


async def test_discard_removes_the_entry(client, db_session, vision_on, sidecar):
    owner_id = await _sign_in(client)
    _, entry_id = await _queue_graph(db_session, owner_id)

    res = await client.delete(f"/api/vision/review-queue/{entry_id}", headers=CSRF)
    assert res.status_code == 204
    async with db_session() as session:
        assert (await session.execute(select(VisionListingImages))).first() is None

    # the entry is gone — a second discard 404s
    res = await client.delete(f"/api/vision/review-queue/{entry_id}", headers=CSRF)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


# --- reference library ----------------------------------------------------------


async def test_references_404_without_a_watch_on_the_item(client, db_session, vision_on):
    await _sign_in(client)
    async with db_session() as session:  # an item the viewer does NOT watch
        sc = Scenario(session)
        item = await sc.item("Foreign")
        await sc.watch(item)  # someone else's watch
        await session.commit()
        item_id = item.id

    res = await client.get(f"/api/items/{item_id}/references")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"


async def test_reference_source_url_is_capturer_and_admin_only(
    client, make_client, monkeypatch, db_session, vision_on
):
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
    await _sign_in(client)  # admin
    peer_client = await make_client()
    peer_id = await _sign_in(peer_client, PEER)

    admin_id = (await client.get("/api/auth/me")).json()["id"]

    # a communal item both the admin and the peer watch; the peer captured one ref
    async with _seed_for(db_session, peer_id) as sc:
        item, _ = await sc.tracked("Shared")
        admin = await sc.db.get(User, admin_id)
        await sc.watch(item, user=admin)
        await sc.reference(
            item,
            label="fake",
            captured_by=peer_id,
            source_listing_url="https://market.test/src",
        )
        await sc.reference(item, provenance="auto", revoked=True)
        item_id = item.id

    peer_refs = (await peer_client.get(f"/api/items/{item_id}/references")).json()["data"]
    captured = next(r for r in peer_refs if r["label"] == "fake")
    assert captured["source_listing_url"] == "https://market.test/src"  # their own capture
    revoked = next(r for r in peer_refs if r["provenance"] == "auto")
    assert revoked["revoked"] is True

    admin_refs = (await client.get(f"/api/items/{item_id}/references")).json()["data"]
    assert next(r for r in admin_refs if r["label"] == "fake")["source_listing_url"] == (
        "https://market.test/src"
    )  # admins see it too

    # a third watcher sees the communal reference but not where it came from
    third_client = await make_client()
    third_id = await _sign_in(
        third_client, {"email": "third@example.com", "password": "hunter2hunter2"}
    )
    async with _seed_for(db_session, third_id) as sc:
        await sc.watch(await sc.db.get(Items, item_id), user=sc._user)
    third_refs = (await third_client.get(f"/api/items/{item_id}/references")).json()["data"]
    assert next(r for r in third_refs if r["label"] == "fake")["source_listing_url"] is None


async def test_upload_validations(client, db_session, vision_on, sidecar):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item, _ = await sc.tracked("Uploadable")
        item_id = item.id

    res = await client.post(
        f"/api/items/{item_id}/references",
        files={"file": ("x.png", b"png-bytes", "image/png")},
        data={"label": "genuine"},
        headers=CSRF,
    )
    assert res.status_code == 422
    assert "label" in res.json()["error"]["fields"]

    res = await client.post(
        f"/api/items/{item_id}/references",
        files={"file": ("x.html", b"<html>", "text/html")},
        data={"label": "real"},
        headers=CSRF,
    )
    assert res.status_code == 422
    assert "file" in res.json()["error"]["fields"]

    res = await client.post(
        f"/api/items/{item_id}/references",
        files={"file": ("x.png", b"x" * (10 * 1024 * 1024 + 1), "image/png")},
        data={"label": "real"},
        headers=CSRF,
    )
    assert res.status_code == 422
    assert "file" in res.json()["error"]["fields"]


async def test_upload_forwards_to_the_sidecar(client, db_session, vision_on, sidecar):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item, _ = await sc.tracked("Uploadable")
        item_id = item.id
    sidecar.upload_response["item_id"] = item_id

    res = await client.post(
        f"/api/items/{item_id}/references",
        files={"file": ("unit.png", b"png-bytes", "image/png")},
        data={"label": "real", "variant_tag": "boxed"},
        headers=CSRF,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["id"] == 4242
    assert body["provenance"] == "upload"
    assert body["image_url"] == "/api/vision/images/uploadedkey"
    assert body["source_listing_url"] is None

    upload = next(r for r in sidecar.requests if r.url.path == "/references")
    payload = upload.read()
    assert b'name="user_id"' in payload and str(owner_id).encode() in payload
    assert b'name="variant_tag"' in payload
    assert str(item_id) == sidecar.rescored_items()[-1]


async def test_revoke_is_soft_and_idempotent(client, db_session, vision_on, sidecar):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item, _ = await sc.tracked("Revokable")
        reference = await sc.reference(item)
        item_id, ref_id = item.id, reference.id

    res = await client.delete(f"/api/vision/references/{ref_id}", headers=CSRF)
    assert res.status_code == 204
    async with db_session() as session:
        row = await session.get(VisionReferences, ref_id)
        assert row.revoked_at is not None
    assert sidecar.rescored_items() == [str(item_id)]

    # revoking again is a harmless no-op (and fires nothing new)
    res = await client.delete(f"/api/vision/references/{ref_id}", headers=CSRF)
    assert res.status_code == 204
    assert sidecar.rescored_items() == [str(item_id)]

    # a reference on an unwatched item is invisible
    res = await client.delete("/api/vision/references/99999", headers=CSRF)
    assert res.status_code == 404


async def test_revoke_auto_counts_only_live_auto_references(client, db_session, vision_on, sidecar):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item, _ = await sc.tracked("Drifted")
        await sc.reference(item, provenance="human")
        await sc.reference(item, provenance="upload")
        await sc.reference(item, provenance="auto")
        await sc.reference(item, provenance="auto")
        await sc.reference(item, provenance="auto", revoked=True)
        item_id = item.id

    res = await client.post(f"/api/items/{item_id}/references/revoke-auto", headers=CSRF)
    assert res.status_code == 200
    assert res.json() == {"revoked": 2}

    # everything auto is now revoked — a second sweep finds nothing
    res = await client.post(f"/api/items/{item_id}/references/revoke-auto", headers=CSRF)
    assert res.json() == {"revoked": 0}


# --- image proxy ----------------------------------------------------------------


async def test_image_proxy_entitlement(
    client, make_client, monkeypatch, db_session, vision_on, sidecar
):
    monkeypatch.setattr(settings, "REGISTRATION_OPEN", True)
    await _sign_in(client)  # admin
    owner_client = await make_client()
    owner_id = await _sign_in(owner_client, OWNER_2)
    peer_client = await make_client()
    peer_id = await _sign_in(peer_client, PEER)

    async with _seed_for(db_session, owner_id) as sc:
        item, watch = await sc.tracked("Guarded")
        scan = await sc.scan(watch, item)
        await sc.capture(scan, object_key="own-capture")
        await sc.reference(item, object_key="live-ref")
        await sc.reference(item, object_key="revoked-ref", revoked=True)
    assert peer_id  # the peer stays graph-less on purpose: no watch, no relation

    # the capturer streams their own capture; watchers stream communal refs
    res = await owner_client.get("/api/vision/images/own-capture")
    assert res.status_code == 200
    assert res.content == b"jpeg-bytes"
    assert (await owner_client.get("/api/vision/images/live-ref")).status_code == 200
    # a revoked reference no longer entitles anyone
    assert (await owner_client.get("/api/vision/images/revoked-ref")).status_code == 404

    # a peer with no relation to the item sees nothing (hidden ≡ nonexistent)
    assert (await peer_client.get("/api/vision/images/own-capture")).status_code == 404
    assert (await peer_client.get("/api/vision/images/live-ref")).status_code == 404

    # admins stream anything
    assert (await client.get("/api/vision/images/own-capture")).status_code == 200


# --- off-mode (the behavior the mock can't express) -----------------------------


async def test_off_mode_lists_empty_and_mutations_503(client, db_session, sidecar):
    owner_id = await _sign_in(client)
    item_id, entry_id = await _queue_graph(db_session, owner_id)

    assert (await client.get("/api/instance")).json()["vision_enabled"] is False

    body = (await client.get("/api/vision/review-queue")).json()
    assert body == {"data": [], "meta": {"page": 1, "per_page": 25, "total": 0}}
    assert (await client.get(f"/api/items/{item_id}/references")).json() == {"data": []}

    for method, path, kwargs in (
        ("post", f"/api/vision/review-queue/{entry_id}/confirm", {"json": {"label": "real"}}),
        ("delete", f"/api/vision/review-queue/{entry_id}", {}),
        (
            "post",
            f"/api/items/{item_id}/references",
            {"files": {"file": ("x.png", b"p", "image/png")}, "data": {"label": "real"}},
        ),
        ("delete", "/api/vision/references/1", {}),
        ("post", f"/api/items/{item_id}/references/revoke-auto", {}),
    ):
        res = await getattr(client, method)(path, headers=CSRF, **kwargs)
        assert res.status_code == 503, path
        assert res.json()["error"]["code"] == "vision_unavailable"

    assert (await client.get("/api/vision/images/somekey")).status_code == 503


# --- thresholds on /api/me ------------------------------------------------------


async def test_new_users_carry_the_default_thresholds(client):
    await _sign_in(client)
    me = (await client.get("/api/auth/me")).json()
    assert me["vision_auto_reject_fake"] == "0.85"
    assert me["vision_auto_promote_real"] == "0.90"
    assert me["vision_auto_promote_fake"] == "0.90"


async def test_threshold_update_and_bounds(client):
    await _sign_in(client)

    res = await client.patch("/api/me", json={"vision_auto_reject_fake": "0.75"}, headers=CSRF)
    assert res.status_code == 200
    assert res.json()["vision_auto_reject_fake"] == "0.75"
    assert (await client.get("/api/auth/me")).json()["vision_auto_reject_fake"] == "0.75"

    for bad in ("0.49", "1.01", "abc"):
        res = await client.patch("/api/me", json={"vision_auto_promote_real": bad}, headers=CSRF)
        assert res.status_code == 422, bad
        body = res.json()["error"]
        assert body["code"] == "validation_error"
        assert "vision_auto_promote_real" in body["fields"]


# --- listing authenticity -------------------------------------------------------


async def test_listings_carry_their_authenticity_read(client, db_session, vision_on):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item, watch = await sc.tracked("Scanned")
        scanned = await sc.listing(watch, item, tag="scanned")
        await sc.listing(watch, item, tag="unscanned")
        scan = await sc.scan(
            watch, item, url=scanned.url, verdict="leans_fake", fake_confidence="0.72"
        )
        await sc.capture(scan, review_state="none", suggested_label=None)
        await sc.capture(scan, review_state="none", suggested_label=None)
        item_id = item.id

    listings = (await client.get(f"/api/items/{item_id}")).json()["listings"]
    by_url = {ln["url"]: ln["authenticity"] for ln in listings}
    read = by_url["https://example.test/scanned"]
    assert read["verdict"] == "leans_fake"
    assert read["fake_confidence"] == "0.72"
    assert read["image_count"] == 2
    assert read["checked_at"]
    assert by_url["https://example.test/unscanned"] is None


async def test_authenticity_is_null_when_vision_is_off(client, db_session):
    owner_id = await _sign_in(client)
    async with _seed_for(db_session, owner_id) as sc:
        item, watch = await sc.tracked("OffMode")
        listing = await sc.listing(watch, item, tag="off")
        await sc.scan(watch, item, url=listing.url, verdict="leans_fake", fake_confidence="0.9")
        item_id = item.id

    (listing_row,) = (await client.get(f"/api/items/{item_id}")).json()["listings"]
    assert listing_row["authenticity"] is None
