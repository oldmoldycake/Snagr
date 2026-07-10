"""The API error envelope — every failure the frontend sees goes through here.

Contract (frontend/src/api/types.ts -> ApiErrorBody):
    { "error": { "code", "message", "fields"?, "run_id"? } }

Usage in a route:
    raise err(404, "not_found", f"Item {id} does not exist")
    raise err(422, "validation_error", "Name is required", fields={"name": "Name is required"})
    raise err(409, "run_in_progress", "A run is already active", run_id=active.id)
"""

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra  # fields / run_id / etc.


def err(status: int, code: str, message: str, **extra) -> ApiError:
    """Terse constructor so routes read `raise err(404, "not_found", ...)`."""
    return ApiError(status, code, message, **extra)


async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message, **exc.extra}},
    )
