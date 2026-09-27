"""The API error envelope — every failure the frontend sees goes through here.

Contract (frontend/src/api/types.ts -> ApiErrorBody):
    { "error": { "code", "message", "fields"? } }

Usage in a route:
    raise err(404, "not_found", f"Item {id} does not exist")
    raise err(422, "validation_error", "Name is required", fields={"name": "Name is required"})
    raise err(409, "job_finished", "This job has already finished")

A database error needs no wrapping in a route: db_error_handler (registered
in main.py) answers the ones the request caused and the ones an outage caused,
and lets the rest through as the 500 they are.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

# SQLSTATE classes (the first two characters): 22 is a value the column can't
# hold — an id past int4, a negative LIMIT, a string too long; asyncpg raises
# 22000 itself for an argument out of its type's range. 08, 53 and 57 are the
# server gone, out of connections, or shutting down.
_BAD_VALUE = "22"
_UNAVAILABLE = ("08", "53", "57")


class ApiError(Exception):
    """An expected failure, rendered as the error envelope by api_error_handler."""

    def __init__(self, status: int, code: str, message: str, **extra):
        """Keep the parts of the envelope; `extra` keys land beside code and message."""
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra  # e.g. fields


def err(status: int, code: str, message: str, **extra) -> ApiError:
    """Terse constructor so routes read `raise err(404, "not_found", ...)`."""
    return ApiError(status, code, message, **extra)


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    """Render an ApiError as `{"error": {...}}` with its status code."""
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message, **exc.extra}},
    )


def db_error(exc: SQLAlchemyError) -> ApiError | None:
    """The envelope a database error answers with, or None for one that is a
    bug and should surface as a 500.

    A value the database can't store is the request's fault (422), and so is a
    constraint it trips — usually a row that went away mid-request (409). Only
    a lost connection, or a server refusing work, is 503 db_unavailable:
    calling bad input an outage sends the caller to check a database that is
    fine."""
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None) or ""
    if sqlstate.startswith(_BAD_VALUE):
        return err(422, "validation_error", "A value in this request is out of range")
    if isinstance(exc, IntegrityError):
        return err(409, "conflict", "The data changed while this request ran; reload and try again")
    if (
        isinstance(exc, PoolTimeoutError)
        or (isinstance(exc, DBAPIError) and exc.connection_invalidated)
        or sqlstate.startswith(_UNAVAILABLE)
    ):
        return err(503, "db_unavailable", "Could not reach the database")
    return None


async def db_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """Render a database error db_error() recognizes; re-raise any other."""
    api_error = db_error(exc)
    if api_error is None:
        raise exc
    return await api_error_handler(request, api_error)
