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
│   │   ├── runs.py         # AgentRun, RunEvent, RunStats + requests
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
│   │   ├── runs.py         # /api/runs[/{id}][/events|/cancel]
│   │   ├── events.py       # GET /api/events (SSE) — opened via EventSource, not in endpoints.ts
│   │   ├── admin.py        # /api/admin/users, /api/admin/invites
│   │   └── vision.py       # /api/vision/* (review queue, references, image proxy) + /api/items/{id}/references*
│   ├── mcp/               # the MCP endpoint (POST /api/mcp): Snagr as tools for agents
│   │   ├── server.py       # FastMCP instance, bearer verifier, the error-envelope conversion, app factory
│   │   ├── refs.py         # category by id|slug and site by id|name (404 unknown, 422 ambiguous)
│   │   ├── schemas.py      # MCP-only shapes (Whoami, RunDetail) — every other tool returns schemas/*
│   │   └── tools/          # one module per section: instance, catalog, items, charts, runs, vision (__init__.register() fans out to them)
│   └── services/          # logic that's more than one query — routers stay thin
│       ├── items.py        # the item↔watch↔watch_sites mapping — reads, writes, serializers (shared by the router and mcp/)
│       ├── catalog.py      # category/site reads, writes and serializers (shared by routers and mcp/)
│       ├── aggregates.py   # all price math: history buckets, dashboard stats, sparklines, deltas
│       ├── runs.py         # run enqueue/scope-label/409-active-check + visibility predicate
│       ├── oidc.py         # SSO: OIDC discovery, code exchange, ID-token validation, account linking
│       ├── events.py       # SSE broadcaster hub (Postgres LISTEN/NOTIFY)
│       ├── vision.py       # sidecar httpx client + authenticity batch lookup + confirm/revoke/upload flows
│       ├── notifications.py# outbox dispatcher: LISTEN + drain, ntfy/webhook/discord senders
│       └── tokens.py       # API-token lookup shared by REST bearer auth and the MCP verifier
├── tests/
│   ├── conftest.py         # DATABASE_URL → snagr_test redirect, create_all schema, per-test truncate, the CSRF header
│   ├── factories.py        # row builders shared by the API tests
│   └── test_*.py           # one module per router/service (16 files) — copy the nearest sibling's pattern
├── migrations/            # Alembic revisions 001–013 (linear chain); the backend owns the canonical schema (D1)
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
| `services/` | multi-step logic (item mapping, aggregation, run lifecycle, SSE) | knowing about HTTP/FastAPI |
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
| `triggerRun` `listRuns` `getRun` `getRunEvents` `cancelRun` | `runs.py` | 3 |
| *(EventSource `/api/events`)* | `events.py` | 3 |
| `listUsers` `updateUser` `deleteUser` `listInvites` `createInvite` `revokeInvite` | `admin.py` | 4 |
| `listReviewQueue` `confirmReviewEntry` `discardReviewEntry` `listReferences` `uploadReference` `revokeReference` `revokeAutoReferences` | `vision.py` | vision |
| *(`<img src>` `/api/vision/images/{key}`)* | `vision.py` | vision |
| *(MCP tools over `POST /api/mcp` — same services, same shapes)* | `mcp/tools/*.py` | mcp |

---

## Five things that aren't obvious (read before you touch the backend)

1. **An API "item" is three tables.** `items` (shared name/category) + the caller's
   `watches` row (target_price, criteria, selection_mode, max_listings,
   allow_reproductions, notify) + `watch_sites` (the `site_ids` subset). Handled in
   `services/items.py`. `GET /api/items` lists *the user's watches*, not the catalog.

2. **Lots of response fields are computed, not stored.** `best_price`, `avg_price`,
   `spark`, `pct_change_range`, `item_count`, `listing_count`, `last_checked_at`, the
   dashboard tiles — all derived from `listings` + `price_checks` at query time:
   the price math lives in `services/aggregates.py`, the grouped category/site
   counts in `services/catalog.py` (the admin user list keeps its own small
   grouped count in `routers/admin.py`). Don't add columns for them.

3. **The API schema sits on top of the agent-era tables.** Auth columns on `users`,
   plus `watch_sites`, `invites`, `sessions`, `agent_runs`, `run_events` — all added
   in migration 002, which also dropped the dead `job_runs` (superseded by
   `agent_runs`). Per-watch config (`criteria`, `selection_mode`, `max_listings`,
   `allow_reproductions`) lives on `watches`, not `items`: `items` stays a pure
   shared catalog row.

4. **Run visibility is per-user, enforced by ONE predicate** (`services/runs.py`):
   `run_visible` gates the run row (own runs + system runs with `user_id NULL` +
   admins see all; a hidden run 404s exactly like an unknown id), and — within a
   visible run — `event_visible` filters each `run_events` row by payload
   reference (`item_id` → that item's watchers, `listing_id` → the listing's sole
   owner, no reference → every viewer of the run), with `load_viewer_refs`
   fetching the two ownership sets. The same functions serve five surfaces:
   `GET /api/runs` (the rule in SQL form for pagination totals), run detail, the
   events backfill (filter **before** `limit`), cancel (404 → 403 for system
   runs → 409, permission before state), and the SSE hub (envelopes + snapshots
   gated per run row, `run.event` frames by the composed predicate). Reconnects
   never infer gaps from seq arithmetic — filtered viewers legitimately hold
   sparse seqs; the client refetches the backfill on every snapshot and the
   filtered response is authoritative. This is **peer privacy only**: the
   instance operator can always read the DB.

5. **Vision visibility splits three ways (D-V11), enforced in three places.**
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
