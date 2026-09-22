"""Shapes that exist only on the MCP surface. Everything else a tool returns
is the REST schema itself (schemas/*), so an agent and the UI see one shape."""

from pydantic import BaseModel

from app.schemas.auth import User
from app.schemas.jobs import Job, JobEvent


class Whoami(BaseModel):
    """The token's owner and what the token may do."""

    user: User
    scopes: list[str]


class JobDetail(Job):
    """A job with the tail of its log."""

    events: list[JobEvent]
