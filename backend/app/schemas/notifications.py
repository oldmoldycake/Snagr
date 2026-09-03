"""Notification channels — mirror the channel block of types.ts (Phase: notifications)."""

from typing import Literal

from pydantic import BaseModel

ChannelKind = Literal["ntfy", "webhook", "discord"]
# additive: channels with events=None receive new members of this union automatically
NotificationEvent = Literal["target.hit", "listing.new"]
KNOWN_EVENTS: tuple[str, ...] = ("target.hit", "listing.new")


class NotificationChannel(BaseModel):
    id: int
    kind: ChannelKind
    name: str
    url: str | None  # webhook/discord destination; None for ntfy
    topic: str | None  # ntfy topic; None for other kinds
    has_secret: bool  # webhook only: a signing secret is stored
    events: list[NotificationEvent] | None  # None = all events
    enabled: bool
    created_at: str


class NotificationChannelCreated(NotificationChannel):
    """POST /api/me/channels response — the one time a webhook's secret is shown."""

    secret: str | None


# kind/events are plain strings here: the mock's 422 validation_error envelope
# (fields.kind / fields.events) is the contract, so the router validates them
# itself instead of letting Pydantic answer with FastAPI's default detail shape.
class NotificationChannelCreateRequest(BaseModel):
    kind: str | None = None
    name: str | None = None
    url: str | None = None
    topic: str | None = None
    events: list[str] | None = None
    enabled: bool = True


class NotificationChannelUpdateRequest(BaseModel):
    """kind is immutable — delete and recreate to change a channel's kind."""

    name: str | None = None
    url: str | None = None
    topic: str | None = None
    events: list[str] | None = None
    enabled: bool | None = None


# --- ORM-row -> schema serializers -------------------------------------------
# (timestamps must go out as ISO-8601 strings, so plain model_validate won't do)


def channel_out(c) -> NotificationChannel:
    return NotificationChannel(
        id=c.id,
        kind=c.kind,
        name=c.name,
        url=c.url,
        topic=c.topic,
        has_secret=c.secret is not None,
        events=c.events,
        enabled=c.enabled,
        created_at=c.created_at.isoformat(),
    )


def channel_created_out(c, secret: str | None) -> NotificationChannelCreated:
    return NotificationChannelCreated(**channel_out(c).model_dump(), secret=secret)
