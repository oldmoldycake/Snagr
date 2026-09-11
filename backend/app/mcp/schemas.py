"""Shapes that exist only on the MCP surface. Everything else a tool returns
is the REST schema itself (schemas/*), so an agent and the UI see one shape."""

from pydantic import BaseModel

from app.schemas.auth import User
from app.schemas.runs import AgentRun, RunEvent


class Whoami(BaseModel):
    """The token's owner and what the token may do."""

    user: User
    scopes: list[str]


class RunDetail(AgentRun):
    """A run with the tail of its log — the events the viewer may see."""

    events: list[RunEvent]
