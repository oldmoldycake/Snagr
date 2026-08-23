# Snagr — Agent Instructions

## Repo layout

Three independently-deployed components sharing **one Postgres on the LAN** (not in `docker-compose.yml`; each points at it via `DATABASE_URL`):

- `agent/` — headless-browser scraper (Playwright MCP + LangChain). One-shot batch job, not a server.
- `backend/` — FastAPI async API (SQLAlchemy 2.0 + asyncpg). Entrypoint: `app.main:app`.
- `frontend/` — React 19 + Vite + TS + Tailwind v4 SPA. Entrypoint: `src/`.

## Environments & commands

Each `backend/` and `agent/` has its own `venv/`. Always use `./venv/bin/<tool>` from the respective directory.

**Backend** (run from `backend/`):
```bash
./venv/bin/uvicorn app.main:app --reload --port 8000
./venv/bin/pytest                        # all tests
./venv/bin/pytest tests/test_auth_flow.py -v
./venv/bin/alembic upgrade head          # apply migrations
./venv/bin/alembic revision --autogenerate -m "msg"
./venv/bin/alembic check                 # models ↔ migrations agree
```

**Frontend** (run from `frontend/`):
```bash
npm run dev        # :5173, proxies /api → :8000
npm run build      # tsc -b + vite build; fails on type errors
npm run lint       # oxlint
```

**Docker**: `docker compose up --build` → frontend `:8081`, backend `:8000`, plus the agent ticker (checks the run queue every minute). Postgres and the Playwright MCP are external.

## The contract lives in the frontend

`frontend/src/api/endpoints.ts` defines routes; `frontend/src/api/types.ts` defines request/response shapes; `frontend/src/mocks/handlers.ts` defines expected status codes and `error.code` values. Backend schemas mirror these field-for-field. Unimplemented endpoints 404 — this doubles as a build checklist.

## Backend architecture

Request flow: **router → service → models/database**. `schemas/` are JSON shapes; `core/` holds cross-cutting concerns. Thin CRUD routes can call the DB directly; use a `service/` only for real logic (5 services exist).

### Key invariants

- **Prices are decimal strings** (`"549.99"`), never numbers. `null` for unknown, never `0`.
- **Timestamps are ISO-8601 UTC**. All DB datetimes are `timezone=True`.
- **Errors always use** `raise err(status, code, message, **extra)` → `{"error": {...}}`. Never FastAPI's default `{"detail": ...}`.
- **Mutations require the `X-Snagr-Csrf` header** (CSRF guard). No mutation without it.
- **Auth** is httpOnly-cookie sessions: short-lived JWT (`snagr_access`) + DB-backed rotating refresh token (`snagr_refresh` cookie). JS never sees tokens.
- **`/api/auth/*` returns 401 directly** — it must not trip the client's refresh-retry loop.

### An API "item" is three tables

`items` (shared catalog) + the caller's `watches` row (target_price, criteria, selection_mode…) + `watch_sites` (the `site_ids` subset). `GET /api/items` lists *the user's watches*, not the global catalog. `POST /api/items` = find-or-create item + create watch + insert watch_sites.

### Computed fields are not stored

`best_price`, `avg_price`, `spark`, `pct_change_range`, dashboard tiles, `last_checked_at` — all derived from `listings` + `price_checks` in `services/aggregates.py`. Do not add columns for them.

## Testing

- `backend/tests/conftest.py` redirects `DATABASE_URL` to `snagr_test` (same server, `/snagr_test` suffix) **before importing `app.*`** — tests never touch live data.
- Tests need a reachable Postgres.
- Schema is built from `Base.metadata.create_all`; each test starts from truncated tables.
- `pytest.ini` sets `asyncio_mode=auto` — no `@pytest.mark.asyncio` needed.
- Mutating requests in tests must carry the `X-Snagr-Csrf` header.

## Schema ownership

The backend owns the canonical schema and all Alembic migrations (`backend/app/models.py` + `backend/migrations/`). The agent (`agent/database.py`) keeps a column-compatible subset — do not restructure it, and never run `Base.metadata.create_all()` from the agent against the live DB. Schema changes go through a new Alembic revision.

## Implementation status

`services/aggregates.py` is the current build front. `price_summary`, `item_rollups`, `dashboard_stats`, `price_drops`, `category_price_change` are **stubs** (`pass`); only `price_history` is implemented. Routers that depend on them `raise NotImplementedError`. Build against the frontend contract — unimplemented endpoints 404, which doubles as the checklist.

## Important files to read first

- `CLAUDE.md` — in-depth architecture, layer model, endpoint→file lookup
- `backend/STRUCTURE.md` — every backend file's job and the layer model
- `frontend/src/api/endpoints.ts` + `types.ts` — the contract
- `frontend/src/mocks/handlers.ts` — behavioral oracle for status codes and error codes
