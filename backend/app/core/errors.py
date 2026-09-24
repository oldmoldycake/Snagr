"""The API error envelope — every failure the frontend sees goes through here.

Contract (frontend/src/api/types.ts -> ApiErrorBody):
    { "error": { "code", "message", "fields"? } }

Usage in a route:
    raise err(404, "not_found", f"Item {id} does not exist")
    raise err(422, "validation_error", "Name is required", fields={"name": "Name is required"})
    raise err(409, "job_finished", "This job has already finished")
"""

from fastapi import Request
from fastapi.responses import JSONResponse


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
