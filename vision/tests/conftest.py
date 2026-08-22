"""Environment shims + throwaway-DB fixtures for the sidecar suite.

config.py and db.py read the environment at import time, so DATABASE_URL is
force-rewritten to the throwaway `snagr_test_vision` database before any
module import — exactly like backend/tests/conftest.py, with its own suffix
so the two suites can run side by side. The embedder and the object store
are ALWAYS stubbed: CI must never download DINOv3 weights or need a minio —
tests pick similarities by picking angles (see `vec`).
"""

import math
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

from dotenv import dotenv_values

# --- MUST run before any sidecar-module import --------------------------------
_here = Path(__file__).resolve()


def _configured_url() -> str:
    """First usable URL: env var, vision/.env, then backend/.env (all suites
    share the one Postgres server)."""
    candidates = [
        os.environ.get("DATABASE_URL"),
        dotenv_values(_here.parents[1] / ".env").get("DATABASE_URL"),
        dotenv_values(_here.parents[2] / "backend" / ".env").get("DATABASE_URL"),
    ]
    for url in candidates:
        if url:
            return url
    return "postgresql+psycopg://snagr:snagr@localhost:5432/snagr"


# the sidecar is sync — a backend-style asyncpg URL is rewritten to psycopg
_live_url = _configured_url().replace("+asyncpg", "+psycopg")
_test_url = _live_url.rsplit("/", 1)[0] + "/snagr_test_vision"
assert _test_url != _live_url, "test DB must not be the live DB"
os.environ["DATABASE_URL"] = _test_url
# ------------------------------------------------------------------------------

import embedder
import fetcher
import numpy as np
import pytest
import storage
from app import app
from config import EMBEDDING_DIM, VISION_MODEL
from db import Base, Items, SessionLocal, Users, VisionReferences, Watches, engine
from fastapi.testclient import TestClient
from sqlalchemy import text

_ALL_TABLES = ", ".join(t.name for t in Base.metadata.sorted_tables)


def vec(theta_degrees: float) -> list[float]:
    """A unit vector in the 2D test plane: cosine(vec(a), vec(b)) == cos(a−b),
    so tests pick similarities by picking angles. Convention: gold-real refs
    sit at 0°, gold-fake refs at 90°."""
    theta = math.radians(theta_degrees)
    v = [0.0] * EMBEDDING_DIM
    v[0], v[1] = math.cos(theta), math.sin(theta)
    return v


def off_plane() -> list[float]:
    """A unit vector orthogonal to the test plane — 'far from everything'."""
    v = [0.0] * EMBEDDING_DIM
    v[2] = 1.0
    return v


class FakeStorage:
    """In-memory stand-in for storage.Storage — same interface, dict-backed."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def ensure_bucket(self) -> None:
        pass

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    def get(self, key: str) -> tuple[bytes, str] | None:
        return self.objects.get(key)

    def exists(self, key: str) -> bool:
        return key in self.objects

    def list_keys(self) -> list[str]:
        return list(self.objects)

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class FakeEmbedder:
    """bytes → vector registry driving the stubbed embed(); counts calls so
    dedup tests can prove pixels were embedded exactly once."""

    def __init__(self) -> None:
        self.registry: dict[bytes, list[float]] = {}
        self.calls = 0

    def embed(self, images: list[bytes]) -> np.ndarray:
        self.calls += 1
        return np.array([self.registry[data] for data in images], dtype=np.float32)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Create the full subset schema in snagr_test_vision once."""
    with engine.begin() as conn:
        # pgvector is a project-wide prerequisite (migration 009); same loud
        # failure contract as backend/tests/conftest.py.
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        except Exception as exc:
            raise RuntimeError(
                "Sidecar tests require the pgvector extension in snagr_test_vision and "
                "could not create it. Run `CREATE EXTENSION vector;` there as your "
                "Postgres admin (see README → Requirements), then re-run pytest."
            ) from exc
        Base.metadata.drop_all(conn)
        Base.metadata.create_all(conn)
    yield
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables():
    """Every test starts from an empty database."""
    yield
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {_ALL_TABLES} RESTART IDENTITY CASCADE"))


@pytest.fixture
def fake_store(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr(storage, "store", fake)
    return fake


@pytest.fixture
def fake_embedder(monkeypatch):
    """Stub the model as loaded at the schema's dim; tests register bytes →
    vectors on .registry."""
    fake = FakeEmbedder()
    monkeypatch.setattr(embedder, "load", lambda: EMBEDDING_DIM)
    monkeypatch.setattr(embedder, "_dim", EMBEDDING_DIM)
    monkeypatch.setattr(embedder, "embed", fake.embed)
    return fake


@pytest.fixture
def client(fake_embedder, fake_store):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def degraded_client(fake_store, monkeypatch):
    """A client whose startup found no weights — the D-V1 degraded mode."""
    monkeypatch.setattr(embedder, "load", lambda: None)
    monkeypatch.setattr(embedder, "_dim", None)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def graph():
    """user + item + watch — the smallest thing a scan can hang off."""
    with SessionLocal() as session:
        user = Users()
        item = Items()
        session.add_all([user, item])
        session.flush()
        watch = Watches(user_id=user.id, item_id=item.id)
        session.add(watch)
        session.commit()
        return SimpleNamespace(user_id=user.id, item_id=item.id, watch_id=watch.id)


@pytest.fixture
def add_reference():
    """Insert a gold reference row directly; returns its id."""

    def _add(
        item_id: int,
        label: str,
        embedding: list[float],
        provenance: str = "human",
        variant_tag: str | None = None,
        revoked_at=None,
        object_key: str | None = None,
    ) -> int:
        with SessionLocal() as session:
            reference = VisionReferences(
                item_id=item_id,
                label=label,
                variant_tag=variant_tag,
                provenance=provenance,
                embedding=embedding,
                model_name=VISION_MODEL,
                object_key=object_key or uuid.uuid4().hex,
                revoked_at=revoked_at,
            )
            session.add(reference)
            session.commit()
            return reference.id

    return _add


@pytest.fixture
def fetches(monkeypatch):
    """url → (bytes, content_type) map driving the stubbed fetcher; a missing
    url behaves like a failed fetch (skip)."""
    fetch_map: dict[str, tuple[bytes, str]] = {}
    monkeypatch.setattr(fetcher, "fetch_image", lambda url, referer=None: fetch_map.get(url))
    return fetch_map
