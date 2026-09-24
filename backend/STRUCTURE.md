# Backend Structure — What Goes Where

The map of every file in `backend/`.

**The contract lives in the frontend** — you build *to* it, you don't design it:
- `frontend/src/api/endpoints.ts` — the list of routes (one function = one route)
- `frontend/src/api/types.ts` — the exact JSON shapes (request + response)
- `frontend/src/mocks/handlers.ts` — the exact behavior (status codes + `error.code`)

Stack: FastAPI + async SQLAlchemy 2.0 (asyncpg) + Pydantic v2. Every file below
is implemented; each carries a docstring stating its job.

---

## Tree

```
backend/
├── app/
│   ├── main.py            # FastAPI app: error handler, every router, the MCP sub-app (when MCP_ENABLED), the two lifetime tasks
│   ├── config.py          # Settings (env/.env) — the ONE place env vars are read
│   ├── database.py        # async engine + session factory + get_db() dependency
│   ├── models.py          # ALL ORM models (owns the schema; mirrors agent/database.py + new tables)
│   ├── core/
│   │   ├── errors.py       # ApiError + the {"error":{...}} envelope handler  ← raise err(404, ...)
│   │   ├── security.py     # password hashing (argon2) + JWT/refresh/API-token minting + webhook secret & HMAC signing (no DB, no FastAPI)
│   │   ├── cookies.py      # the two auth cookie names + set/clear helpers (httpOnly, SameSite=Lax, Path=/)
│   │   └── deps.py         # FastAPI deps: current_user (cookie OR bearer), reject_bearer, require_scope, require_admin, csrf_guard
│   ├── schemas/           # Pydantic models — one file per contract section, mirror types.ts
│   │   ├── common.py       # Paginated[T], PageMeta
│   │   ├── auth.py         # InstanceInfo, User, login/register/invite, me-update, password + admin user/invite shapes
│   │   ├── catalog.py      # Category*, Site*
│   │   ├── items.py        # ItemSummary, ItemDetail, Listing, Watch, PriceCheck + requests
│   │   ├── charts.py       # price-history/summary, dashboard stats, price-drops
│   │   ├── jobs.py         # Job, JobStats, JobEvent, JobsSummary, ListingChecked + requests
│   │   ├── tokens.py       # ApiToken, ApiTokenCreated + create request (Settings → MCP & API)
│   │   ├── notifications.py# ChannelKind, NotificationEvent, NotificationChannel* + create/update requests
│   │   └── vision.py       # ReviewQueueEntry, ReferenceImage, AuthenticityRead + requests
│   ├── routers/           # one file per section of endpoints.ts — HTTP layer only
│   │   ├── instance.py     # GET /api/instance — public, no auth (the frontend's first call on boot)
│   │   ├── auth.py         # /api/auth/*  (login, register, refresh, me, invites, oidc login/callback)
│   │   ├── me.py           # /api/me, /api/me/password, /api/me/channels[/{id}][/test], /api/me/tokens[/{id}] — cookie-only
│   │   ├── categories.py   # /api/categories[/{id}][/sites]
│   │   ├── sites.py        # /api/sites[/{id}]
│   │   ├── items.py        # /api/items[/{id}], /api/items/{id}/watch, /api/listings/{id}, price-checks
│   │   ├── charts.py       # /api/items/{id}/price-*, /api/categories/{id}/price-change, /api/dashboard/*
│   │   ├── jobs.py         # /api/jobs[/summary|/{id}][/events|/cancel]
│   │   ├── events.py       # GET /api/events (SSE) — opened via EventSource, not in endpoints.ts
│   │   ├── admin.py        # /api/admin/users, /api/admin/invites
│   │   └── vision.py       # /api/vision/* (review queue, references, image proxy) + /api/items/{id}/references*
│   ├── mcp/               # the MCP endpoint (POST /api/mcp): Snagr as tools for agents
│   │   ├── server.py       # FastMCP instance, bearer verifier, the error-envelope conversion, app factory
│   │   ├── refs.py         # category by id|slug and site by id|name (404 unknown, 422 ambiguous)
│   │   ├── schemas.py      # MCP-only shapes (Whoami, JobDetail) — every other tool returns schemas/*
│   │   └── tools/          # one module per section: instance, catalog, items, charts, jobs, vision (__init__.register() fans out to them)
│   └── services/          # logic that's more than one query — routers stay thin
│       ├── items.py        # the item↔watch↔watch_sites mapping — reads, writes, serializers (shared by the router and mcp/)
│       ├── catalog.py      # category/site reads, writes and serializers (shared by routers and mcp/)
│       ├── aggregates.py   # all price math: history buckets, dashboard stats, sparklines, deltas
│       ├── jobs.py         # the queue's API side: enqueue, scope expansion, reads, cancel + the visibility predicate
│       ├── oidc.py         # SSO: OIDC discovery, code exchange, ID-token validation, account linking
│       ├── events.py       # SSE broadcaster hub (Postgres LISTEN/NOTIFY) — job.* frames + listing.checked
│       ├── vision.py       # sidecar httpx client + authenticity batch lookup + confirm/revoke/upload flows
│       ├── notifications.py# outbox dispatcher: LISTEN + drain, ntfy/webhook/discord senders
│       └── tokens.py       # API-token lookup shared by REST bearer auth and the MCP verifier
├── tests/
│   ├── conftest.py         # DATABASE_URL → snagr_test redirect, create_all schema + migration 015's triggers by hand, per-test truncate, the CSRF header
│   ├── factories.py        # row builders shared by the API tests
│   └── test_*.py           # one module per router/service (17 files) — copy the nearest sibling's pattern
├── migrations/            # Alembic revisions 001–018 (linear chain); the backend owns the canonical schema
├── requirements.txt       # deps — `pip install -r` then `pip freeze >` to pin
├── alembic.ini            # Alembic config (script location; migrations/env.py injects the URL from settings)
├── pytest.ini             # asyncio_mode=auto + the session loop scope
├── .env.example           # committed template (no secrets); copy to .env
├── Dockerfile             # 2-stage: build venv (with compilers) → slim runtime
└── .dockerignore
```

---

## Layer responsibilities (the mental model)

Request flow: **router** (HTTP, validation, status codes) → **service** (business
logic, only where non-trivial) → **models/database** (SQL). **schemas** define the
JSON in/out. **core** holds cross-cutting concerns (errors, auth, security).

| Layer | Owns | Never does |
|---|---|---|
| `routers/` | URL paths, request parsing, choosing status codes, calling a service or the DB | complex math, raw crypto |
| `services/` | multi-step logic (item mapping, aggregation, the job queue, SSE) | knowing about HTTP/FastAPI |
| `schemas/` | the exact request/response shapes (mirror `types.ts`) + the `*_out()` serializers that map a row to its shape | business logic, DB access |
| `models.py` | ORM tables (the schema) | request shapes |
| `core/` | error envelope, auth deps, hashing/tokens | domain logic |
| `config.py` | reading env | anything else |

**Rule of thumb:** a thin CRUD route (the admin user list, `routers/admin.py`)
can call the DB directly from the router. Reach for a `service` only when there's
real logic — that's why only nine services exist, not one per router.

---

## Endpoint → file lookup

Find any `endpoints.ts` function here:

| endpoints.ts function | Router file | Phase |
|---|---|---|
| `getInstance` | `instance.py` | 0 |
| `login` `register` `logout` `getMe` `validateInvite` `acceptInvite` (+ refresh) | `auth.py` | 2 |
| `updateMe` `changePassword` | `me.py` | 2 |
| `listChannels` `createChannel` `updateChannel` `deleteChannel` `testChannel` | `me.py` | notifications |
| `listTokens` `createToken` `revokeToken` | `me.py` | mcp |
| `listCategories` `createCategory` `updateCategory` `deleteCategory` `setCategorySites` | `categories.py` | 1 / 3 |
| `listSites` `createSite` `updateSite` `deleteSite` | `sites.py` | 1 / 3 |
| `listItems` `createItem` `getItem` `updateItem` `deleteItem` `updateWatch` `updateListing` `listPriceChecks` | `items.py` | 1 / 3 |
| `getPriceHistory` `getPriceSummary` `getCategoryPriceChange` `getDashboardStats` `getPriceDrops` | `charts.py` | 1 |
| `enqueueJobs` `listJobs` `getJobsSummary` `getJob` `getJobEvents` `cancelJob` | `jobs.py` | 3 |
| *(EventSource `/api/events`)* | `events.py` | 3 |
| `listUsers` `updateUser` `deleteUser` `listInvites` `createInvite` `revokeInvite` | `admin.py` | 4 |
| `listReviewQueue` `confirmReviewEntry` `discardReviewEntry` `listReferences` `uploadReference` `revokeReference` `revokeAutoReferences` | `vision.py` | vision |
| *(`<img src>` `/api/vision/images/{key}`)* | `vision.py` | vision |
| *(MCP tools over `POST /api/mcp` — same services, same shapes)* | `mcp/tools/*.py` | mcp |

---

## Five things that aren't obvious (read before you touch the backend)

1. **An API "item" is three tables.** `items` (shared name/category) + the caller's
   `watches` row (target_price, criteria, selection_mode, max_listings,
   allow_reproductions, recheck_interval_minutes, hunt, notify) + `watch_sites` (the `site_ids` subset). Handled in
   `services/items.py`. `GET /api/items` lists *the user's watches*, not the catalog.

2. **Lots of response fields are computed, not stored.** `best_price`, `avg_price`,
   `spark`, `pct_change_range`, `item_count`, `listing_count`, `last_checked_at`, the
   dashboard tiles — all derived from `listings` + `price_checks` at query time:
   the price math lives in `services/aggregates.py`, the grouped category/site
   counts in `services/catalog.py` (the admin user list keeps its own small
   grouped count in `routers/admin.py`). Don't add columns for them.

   **Every price read filters `price_checks.confirmed`** (migration 014). The
   agent records a reading it did not believe — one wildly out of line with the
   listing's history or the item's market value — so the checks log can show
   what was seen, but it must never become a best price, an average, a chart
   point or a target-met badge. `GET /api/items/{id}/price-checks` is the one
   deliberate exception: it *is* the log, and each row carries `confirmed` so
   the UI can ghost it. `last_checked_at` is not filtered either — a
   disbelieved reading is still a check that happened.

3. **The API schema sits on top of the agent-era tables.** Auth columns on `users`,
   plus `watch_sites`, `invites`, `sessions` — added in migration 002. The three
   run tables that came with them (`agent_runs`, `run_events`, `run_schedules`)
   were dropped by migration 015, which replaced them with `jobs` and
   `job_events`. Per-watch config (`criteria`, `selection_mode`, `max_listings`,
   `allow_reproductions`, `recheck_interval_minutes`, `hunt`) lives on `watches`, not
   `items`: `items` stays a pure shared catalog row.

4. **Job visibility is per-user, enforced by ONE predicate** (`services/jobs.py`):
   `visible_to(user_id, is_admin)` is a SQL clause — jobs for the viewer's own
   watches, plus `ground` jobs for items they watch; admins see everything; a
   hidden job 404s exactly like an unknown id. It is a clause rather than a
   function of a loaded row because `meta.total` has to count post-filter in the
   database and because the SSE hub holds only an identity. The same predicate
   serves six surfaces: `GET /api/jobs`, detail, the events backfill, the
   summary, cancel (404 → 403 → 422 → 409, permission before state) and every
   pushed frame (`services/events.py`), so push and backfill can never disagree.

   There is **no event-level rule**: a job belongs
   to one watch, so seeing the job is seeing its events. `listing.checked` frames
   are gated by listing ownership instead, which is the same person. Reconnects
   never infer gaps from seq arithmetic; the client refetches each visible
   backfill on every snapshot and the filtered response is authoritative. This is
   **peer privacy only**: the instance operator can always read the DB.

   **The queue's own rules live half here and half in the agent** (the agent's
   half: [`agent/STRUCTURE.md`](../agent/STRUCTURE.md)). Migration 015's
   partial unique index allows one *open* job per target, so every insert on both
   sides is `ON CONFLICT DO NOTHING` and `POST /api/jobs` answers 202 with
   whatever it queued or brought forward — never a 409 for a duplicate. Creating
   a watch queues its hunts and its grounding in the same transaction;
   untracking a listing cancels its pending check and stamps
   `inactive_reason = 'untracked'`.
   `ItemDetail.hunt` / `.recheck` are computed from the watch's jobs and exist
   on the detail shape only, so list queries stay cheap. `ItemSummary.hunt` is
   the watch's own switch (a boolean); on the detail the facts object takes
   its place and carries it as `hunt.enabled`.

   **Hunting is the agent's to run and the backend's to start and stop.** The
   agent chains each pair's hunts (at once after a save, a doubling backoff
   after an empty one) and sweeps hourly; the backend only touches the chain
   where a person does: a watch created with `hunt: false` queues no hunt,
   switching `hunt` off cancels every waiting hunt but a pending "hunt now"
   (by `reason`, since creation hunts carry the creator's id too), untracking
   a listing, raising `max_listings` or switching `hunt` back on wakes the
   watch's hunts with their backoff forgotten (`wake_hunts`, the twin of
   `agent/jobs.py::add_hunt_wakes`), and a user's "hunt now" forgets it too.
   On a full watch "hunt now" is still queued, flagged `payload.swap = true`:
   the swap hunt, the one hunt a full watch gets, which may trade its
   weakest listing for a better one (the agent does the trade).
   `HUNT_ENABLED` is the operator's kill switch,
   set in both env files: under `false` the agent claims no hunts, so
   `POST /api/jobs {kind: 'hunt'}` answers 409 `hunting_disabled` rather than
   queueing work nothing will claim, and a new watch queues none (the agent's
   sweep catches it up when the switch is back on).

   **The check interval is the agent's to keep and the backend's to report.**
   The agent schedules each successor at the watch's `recheck_interval_minutes`,
   else `RECHECK_INTERVAL_MINUTES`, never below `RECHECK_INTERVAL_FLOOR_MINUTES`;
   `services/jobs.py::effective_interval` is the same rule, for
   `ItemDetail.recheck.interval_minutes`. Both settings live in `backend/.env`
   *and* the agent's env with the same values (the `VISION_SIDECAR_URL`
   precedent): the backend needs the default for `InstanceInfo` and the floor
   for the 422. On `PATCH /api/items/{id}` this is the one field where an
   explicit null means something (back to the default — `model_fields_set`
   tells it from an absent key), and a shorter interval pulls the watch's
   pending checks forward in the same transaction.

5. **Vision visibility splits three ways, enforced in three places.**
   An item's reference *library* is communal — every watcher of the item reads
   the same gold references — but the *review queue* is scoped to the capturing
   watch's owner, **admins included**: you review what your own hunts captured,
   and a foreign queue entry 404s exactly like an unknown id (`services/vision.py`:
   `_own_queue_entry` and `list_review_queue`; the routers just forward the caller). A reference's `source_listing_url` is nulled in serialization
   unless the viewer captured it or is an admin (`schemas/vision.py` via the
   router's serializer). The image proxy (`GET /api/vision/images/{key}`) gates
   bytes with one query of two EXISTS branches: the key must belong to a non-revoked reference of
   an item the viewer watches, to a listing-image whose scan's watch is the
   viewer's, or the viewer is an admin. Don't "simplify" any of these into a
   single ownership rule — the asymmetry is the design.

---

## Conventions (enforced everywhere)

- **Prices** are decimal strings (`"549.99"`), never numbers. `null` for unknown, never `0`.
- **Timestamps** are ISO-8601 UTC strings.
- **Errors** always use `raise err(status, code, message, **extra)` → `{"error":{...}}`. Never FastAPI's default `{"detail":...}`.
- **Paginated** = `{data, meta:{page, per_page, total}}`; **plain list** = `{data:[...]}`.
- **Mutations** require the `X-Snagr-Csrf` header (`csrf_guard`) — the frontend always sends it; bearer (API-token) callers are exempt.
- **`/api/auth/*` returns 401 directly** — it must not trip the client's refresh-retry loop.
