# Backend Structure — What Goes Where

The map of every file in `backend/`.

**The contract lives in the frontend** — you build *to* it, you don't design it:
- `frontend/src/api/endpoints.ts` — the list of routes (one function = one route)
- `frontend/src/api/types.ts` — the exact JSON shapes (request + response)
- `frontend/src/mocks/handlers.ts` — the exact behavior (status codes + `error.code`)

Stack: FastAPI + async SQLAlchemy 2.0 (asyncpg) + Pydantic v2. Unimplemented
files below carry a docstring describing their job; fill them in against the
frontend contract.

---

## Tree

```
backend/
├── app/
│   ├── main.py            # FastAPI app: registers the error handler + mounts every router
│   ├── config.py          # Settings (env/.env) — the ONE place env vars are read
│   ├── database.py        # async engine + session factory + get_db() dependency
│   ├── models.py          # ALL ORM models (owns the schema; mirrors agent/database.py + new tables)
│   ├── core/
│   │   ├── errors.py       # ApiError + the {"error":{...}} envelope handler  ← raise err(404, ...)
│   │   ├── security.py     # password hashing (argon2) + JWT/refresh-token minting (no DB, no FastAPI)
│   │   └── deps.py         # FastAPI deps: current_user, require_admin, csrf_guard
│   ├── schemas/           # Pydantic models — one file per contract section, mirror types.ts
│   │   ├── common.py       # Paginated[T], PageMeta
│   │   ├── auth.py         # InstanceInfo, User, login/register/invite, me-update, password
│   │   ├── catalog.py      # Category*, Site*
│   │   ├── items.py        # ItemSummary, ItemDetail, Listing, Watch, PriceCheck + requests
│   │   ├── charts.py       # price-history/summary, dashboard stats, price-drops
│   │   └── runs.py         # AgentRun, RunEvent, RunStats + requests
│   ├── routers/           # one file per section of endpoints.ts — HTTP layer only
│   │   ├── instance.py     # GET /api/instance                       ← build this first (Task 0)
│   │   ├── auth.py         # /api/auth/*  (login, register, refresh, me, invites, oidc login/callback)
│   │   ├── me.py           # /api/me, /api/me/password, /api/me/ntfy/test
│   │   ├── categories.py   # /api/categories[/{id}][/sites]
│   │   ├── sites.py        # /api/sites[/{id}]
│   │   ├── items.py        # /api/items[/{id}], /api/items/{id}/watch, /api/listings/{id}, price-checks
│   │   ├── charts.py       # /api/items/{id}/price-*, /api/categories/{id}/price-change, /api/dashboard/*
│   │   ├── runs.py         # /api/runs[/{id}][/events|/cancel]
│   │   ├── events.py       # GET /api/events (SSE) — opened via EventSource, not in endpoints.ts
│   │   └── admin.py        # /api/admin/users, /api/admin/invites
│   └── services/          # logic that's more than one query — routers stay thin
│       ├── items.py        # the item↔watch↔watch_sites mapping + validation
│       ├── aggregates.py   # all price math: history buckets, dashboard stats, sparklines, deltas
│       ├── runs.py         # run enqueue/scope-label/409-active-check
│       ├── oidc.py         # SSO: OIDC discovery, code exchange, ID-token validation, account linking
│       └── events.py       # SSE broadcaster hub (Postgres LISTEN/NOTIFY)
├── tests/
│   ├── conftest.py         # async httpx client + (todo) throwaway-DB session fixtures
│   └── test_instance.py    # first test (in the plan) — copy its pattern per router
├── migrations/            # created by `alembic init migrations` (getting-started step 2)
├── requirements.txt       # deps — `pip install -r` then `pip freeze >` to pin
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
| `schemas/` | the exact request/response shapes (mirror `types.ts`) | logic |
| `models.py` | ORM tables (the schema) | request shapes |
| `core/` | error envelope, auth deps, hashing/tokens | domain logic |
| `config.py` | reading env | anything else |

**Rule of thumb:** a thin CRUD route (list categories) can call the DB directly
from the router. Reach for a `service` only when there's real logic — that's why
only five services exist, not one per router.

---

## Endpoint → file lookup

Find any `endpoints.ts` function here:

| endpoints.ts function | Router file | Phase |
|---|---|---|
| `getInstance` | `instance.py` | 0 |
| `login` `register` `logout` `getMe` `validateInvite` `acceptInvite` (+ refresh) | `auth.py` | 2 |
| `updateMe` `changePassword` `sendTestNotification` | `me.py` | 2 |
| `listCategories` `createCategory` `updateCategory` `deleteCategory` `setCategorySites` | `categories.py` | 1 / 3 |
| `listSites` `createSite` `updateSite` `deleteSite` | `sites.py` | 1 / 3 |
| `listItems` `createItem` `getItem` `updateItem` `deleteItem` `updateWatch` `updateListing` `listPriceChecks` | `items.py` | 1 / 3 |
| `getPriceHistory` `getPriceSummary` `getCategoryPriceChange` `getDashboardStats` `getPriceDrops` | `charts.py` | 1 |
| `triggerRun` `listRuns` `getRun` `getRunEvents` `cancelRun` | `runs.py` | 3 |
| *(EventSource `/api/events`)* | `events.py` | 3 |
| `listUsers` `updateUser` `deleteUser` `listInvites` `createInvite` `revokeInvite` | `admin.py` | 4 |

---

## Three things that aren't obvious (read before Phase 1)

1. **An API "item" is three tables.** `items` (shared name/category) + the caller's
   `watches` row (target_price, criteria, selection_mode, max_listings,
   allow_reproductions, notify) + `watch_sites` (the `site_ids` subset). Handled in
   `services/items.py`. `GET /api/items` lists *the user's watches*, not the catalog.

2. **Lots of response fields are computed, not stored.** `best_price`, `avg_price`,
   `spark`, `pct_change_range`, `item_count`, `listing_count`, `last_checked_at`, the
   dashboard tiles — all derived from `listings` + `price_checks` in
   `services/aggregates.py`. Don't add columns for them.

3. **The schema needs new tables before any of this runs.** Auth columns on `users`,
   plus `watch_sites`, `invites`, `sessions`, `agent_runs`, `run_events`. See
   "Schema Gaps" in the plan; apply via Alembic (getting-started step 2). `JobRuns`
   in the agent is dead — replaced by `agent_runs`.

---

## Conventions (enforced everywhere)

- **Prices** are decimal strings (`"549.99"`), never numbers. `null` for unknown, never `0`.
- **Timestamps** are ISO-8601 UTC strings.
- **Errors** always use `raise err(status, code, message, **extra)` → `{"error":{...}}`. Never FastAPI's default `{"detail":...}`.
- **Paginated** = `{data, meta:{page, per_page, total}}`; **plain list** = `{data:[...]}`.
- **Mutations** require the `X-Snagr-Csrf` header (`csrf_guard`) — the frontend always sends it.
- **`/api/auth/*` returns 401 directly** — it must not trip the client's refresh-retry loop.
