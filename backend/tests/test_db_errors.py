"""The database-error envelope (core/errors.py's db_error_handler), which every
route relies on — none wraps its own database errors.

A value the database can't hold is the request's fault, 422 validation_error;
a constraint it trips is 409 conflict; only a lost or refused connection is
503 db_unavailable. Anything else is a bug and stays the 500 it is.
"""

import pytest
from app.services import items as items_service
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from tests.conftest import CSRF

OWNER = {"email": "errors@example.com", "password": "hunter2hunter2"}

# one past the largest value an int4 id column holds
TOO_BIG = 2**31


async def _sign_in(client, creds=OWNER):
    """Register (which also signs in) and return the new user's id."""
    res = await client.post("/api/auth/register", json=creds, headers=CSRF)
    assert res.status_code == 201, res.text
    return res.json()["user"]["id"]


class _Orig(Exception):
    """A DBAPI error as the asyncpg dialect raises one: it carries the SQLSTATE."""

    def __init__(self, sqlstate: str):
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def _failing(exc: Exception):
    """A stand-in for a service call that raises `exc`."""

    async def fail(*args, **kwargs):
        raise exc

    return fail


# --- the request's fault ------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"/api/items/{TOO_BIG}"),
        ("GET", f"/api/items/{TOO_BIG}/price-history?range=30d"),
        ("GET", f"/api/items/{TOO_BIG}/price-summary?range=30d"),
        ("GET", f"/api/items/{TOO_BIG}/price-checks"),
        ("GET", f"/api/categories/{TOO_BIG}/price-change?range=30d"),
        ("GET", f"/api/items?category_id={TOO_BIG}"),
        # past a LIMIT's int8 as well
        ("GET", f"/api/dashboard/price-drops?range=30d&limit={10**20}"),
        ("DELETE", f"/api/items/{TOO_BIG}"),
        ("DELETE", f"/api/me/tokens/{TOO_BIG}"),
    ],
)
async def test_a_value_past_what_the_column_holds_is_a_422(client, method, path):
    await _sign_in(client)

    res = await client.request(method, path, headers=CSRF)

    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "validation_error"


async def test_a_constraint_the_write_trips_is_a_409(client, monkeypatch):
    await _sign_in(client)
    exc = IntegrityError("INSERT", {}, _Orig("23503"))
    monkeypatch.setattr(items_service, "list_items", _failing(exc))

    res = await client.get("/api/items")

    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "conflict"


# --- an outage ----------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        DBAPIError("SELECT 1", {}, Exception("gone"), connection_invalidated=True),
        DBAPIError("SELECT 1", {}, _Orig("08006")),  # connection failure
        DBAPIError("SELECT 1", {}, _Orig("57P01")),  # admin shutdown
        DBAPIError("SELECT 1", {}, _Orig("53300")),  # too many connections
        PoolTimeoutError("QueuePool limit reached"),
    ],
    ids=["invalidated", "08006", "57P01", "53300", "pool-timeout"],
)
async def test_a_lost_connection_is_a_503(client, monkeypatch, exc):
    await _sign_in(client)
    monkeypatch.setattr(items_service, "list_items", _failing(exc))

    res = await client.get("/api/items")

    assert res.status_code == 503, res.text
    assert res.json()["error"]["code"] == "db_unavailable"


# --- a bug --------------------------------------------------------------------


async def test_any_other_database_error_is_not_dressed_up(client, monkeypatch):
    """A missing table is nobody's input and no outage: it surfaces as the
    500 it is, not as a 503 that sends someone to check the database."""
    await _sign_in(client)
    exc = ProgrammingError("SELECT 1", {}, _Orig("42P01"))
    monkeypatch.setattr(items_service, "list_items", _failing(exc))

    with pytest.raises(ProgrammingError):
        await client.get("/api/items")
