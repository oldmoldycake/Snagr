"""All ORM models for the Snagr schema — the single source of truth the
backend owns and migrates (see docs/superpowers/plans — Decision D1).

TO PORT (Phase 0): copy the models from agent/database.py verbatim so the
column definitions match the live tables the agent already writes to:
    User, Sites, Categories, SiteCategories, Items, Listings,
    PriceChecks, Watches, ListingChecks
Delete JobRuns — superseded by AgentRuns below.

TO ADD (Phase 0, per "Schema Gaps" in the plan):
    - User          + password_hash, role ('admin'|'user'), ntfy_topic
    - WatchSites     (watch_id, site_id) — the API's `site_ids` subset
    - Invites        (token, email?, role, expires_at, used_at, created_by)
    - Sessions       (user_id, refresh_hash, expires_at, revoked_at)
    - AgentRuns      (scope, scope_id, scope_label, status, stats jsonb, last_seq, ...)
    - RunEvents      (run_id, seq, ts, level, event_type, message, payload jsonb)

All models inherit Base from app.database.
"""

from app.database import Base  # noqa: F401  (re-exported so Alembic's env.py can import target metadata)

# TODO: define models here.
