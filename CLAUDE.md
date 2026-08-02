# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Snagr — a self-hosted price tracker. Three independently-deployed components in one repo, sharing **one Postgres database on the LAN** (not in `docker-compose.yml`; each component points at it via `DATABASE_URL`):

- **`agent/`** — the LLM price scraper. A batch job that drives a headless browser (Playwright MCP) via a LangChain agent to find and re-check marketplace listings, writing results to the DB. Run on a schedule, not a server.
- **`backend/`** — FastAPI (async SQLAlchemy 2.0 / asyncpg) JSON API under `/api`. Serves the frontend and (per the plan) enqueues agent runs.
- **`frontend/`** — React 19 + Vite + TS + Tailwind v4 SPA. Talks to the backend over same-origin `/api`.

## Read these first

The architecture is documented in depth — prefer reading them over re-deriving:

- `backend/STRUCTURE.md` — every backend file's job, the layer model, endpoint→file lookup, and the non-obvious domain rules. **Read before touching the backend.**
- `frontend/README.md` — frontend scripts, mock mode, structure.

The backend is a **work in progress**; routers and schemas may still be stubs
(`raise NotImplementedError` / `pass`). Treat the frontend contract as the spec.

## Commands

Both `backend/` and `agent/` have their own `venv/` — invoke tools via `./venv/bin/<tool>` (don't assume a global install). Python style in both is enforced by **ruff**:

```bash
./venv/bin/ruff check --fix && ./venv/bin/ruff format   # lint + autoformat — run on what you touched before calling it done
```

**Backend** (from `backend/`):
```bash
./venv/bin/uvicorn app.main:app --reload --port 8000   # dev server
./venv/bin/pytest                                       # all tests
./venv/bin/pytest tests/test_auth_flow.py -v            # one file
./venv/bin/pytest -k invite                             # tests matching a name
./venv/bin/alembic upgrade head                         # apply migrations
./venv/bin/alembic revision --autogenerate -m "msg"     # new migration (inspect before committing)
./venv/bin/alembic check                                # models vs. migrations agree
```

**Frontend** (from `frontend/`):
```bash
npm run dev        # dev server (proxies /api -> localhost:8000)
npm run build      # tsc -b + vite build; fails on type errors
npm run lint       # oxlint
```
To verify frontend changes in a real browser, use the **`frontend:verify`** skill (build + launch + drive), not the generic verify skill.

**Agent** (from `agent/`): `./venv/bin/python main.py` — runs one full scrape pass and exits. Needs `PLAYWRIGHT_MCP_URL`, the `AI_*` provider vars, and `DATABASE_URL` (see `agent/.env.example`).

**Docker (dev)**: `docker compose up --build` → frontend on `:8081`, backend on `:8000`. Postgres is external. Editing `backend/app/**` hot-reloads; changing `requirements.txt` or frontend code needs `--build`.

## Testing model

`backend/tests/conftest.py` redirects `DATABASE_URL` to a throwaway `snagr_test` DB (same server, `/snagr_test` suffix) **before importing `app.*`**, so tests never touch live data — but they still need a reachable Postgres. Schema is built from `Base.metadata.create_all`; each test starts from truncated tables. `pytest.ini` sets `asyncio_mode=auto` (no `@pytest.mark.asyncio` needed). Mutating requests in tests must carry the `CSRF` header (exported from `conftest`).

## The contract is the frontend (backend builds *to* it, doesn't design it)

There is no separate API spec — the frontend defines the exact contract the backend must satisfy:
- `frontend/src/api/endpoints.ts` — the route list (one function per route)
- `frontend/src/api/types.ts` — exact request/response JSON shapes; Pydantic schemas in `backend/app/schemas/` mirror these field-for-field
- `frontend/src/mocks/handlers.ts` — the behavioral oracle: status codes and `error.code` for every case. When in doubt about behavior, match what the mock does.

The frontend runs against a full MSW mock by default; set `VITE_USE_MOCKS=false` (already the case in `.env.development`) to hit the real backend. Unimplemented endpoints 404, which doubles as the visible build checklist.

## Backend architecture

Request flow: **router** (HTTP, validation, status codes) → **service** (multi-step logic, only where non-trivial) → **models/database** (SQL). `schemas/` are the JSON shapes; `core/` holds cross-cutting concerns (error envelope, auth deps, hashing/tokens); `config.py` is the *only* place env vars are read (via the `settings` singleton — never `os.getenv`). Thin CRUD routes may call the DB directly; only five services exist, for real logic (item mapping, aggregation math, run lifecycle, SSE, OIDC login).

Two things that will trip you up if you skip STRUCTURE.md:

1. **An API "item" is three tables.** `items` (shared catalog) + the caller's `watches` row (target_price, criteria, selection_mode, etc.) + `watch_sites` (the `site_ids` subset). `GET /api/items` lists the *user's watches*, not the global catalog. `POST /api/items` = find-or-create item + create watch + insert watch_sites.
2. **Many response fields are computed, not stored** — `best_price`, `avg_price`, `spark`, `pct_change_range`, dashboard tiles, `last_checked_at`, counts — all derived from `listings` + `price_checks` in `services/aggregates.py`. Don't add columns for them.

## Schema ownership (Decision D1)

The **backend owns the canonical schema and all Alembic migrations** (`backend/app/models.py` + `backend/migrations/`). The agent (`agent/database.py`) keeps a **column-compatible subset** of the same ORM models — do not restructure it, and never run `Base.metadata.create_all()` from the agent against the live DB. Schema changes go through a new Alembic revision. `# + api` comments in `models.py` mark columns the backend added on top of the agent's original schema.

## Cross-cutting invariants (from the contract; hold everywhere in the backend)

- **Prices are decimal strings** (`"549.99"`), never numbers. `null` for unknown, never `0`. (Stored `Numeric(10,2)`, serialized with `str()`.)
- **Timestamps are ISO-8601 UTC strings**; all DB datetimes are `timezone=True`.
- **Errors always use** `raise err(status, code, message, **extra)` → `{"error": {...}}`. Never FastAPI's default `{"detail": ...}`.
- **Paginated** = `{data, meta: {page, per_page, total}}`; **plain list** = `{data: [...]}`.
- **Mutations require the `X-Snagr-Csrf` header** (`csrf_guard`); reject with 403 if absent. The frontend always sends it.
- **`/api/auth/*` returns 401 directly** — it must not trip the client's refresh-retry loop (`frontend/src/api/client.ts` refreshes once + retries on 401 for all *other* paths).
- Auth is httpOnly-cookie sessions: short-lived access JWT (`snagr_access`) + DB-backed rotating refresh token (`sessions` table, `snagr_refresh` cookie). JS never sees the token.

## Writing code (house rules)

This is FOSS: optimize for the next reader, who has zero context and wrote none of it. Boring and explicit beats clever.

- **Match the neighbors.** ruff settles formatting; everything it can't see is settled by precedent. Before writing, open a sibling that does the same kind of job (the router next to your router, the test next to your test) and copy its idioms — naming, structure, how it's organized. New code should be indistinguishable from existing code. Keep diffs minimal and boring to review; don't churn lines you aren't otherwise changing.
- **Smallest change that satisfies the contract.** No speculative abstraction — a helper, base class, or *sixth* service needs a second real caller before it exists (thin CRUD living in routers is deliberate, not debt). No new dependencies without asking first: every dep is something self-hosters install and maintainers audit.
- **Every behavior change lands with a test.** Bug fix = reproduce with a failing test first, then fix. New endpoint = tests asserting status codes and `error.code` exactly as `handlers.ts` does — error paths included, not just the happy path. Backend tests run against the real throwaway DB, so don't mock the ORM; use the `conftest` fixtures (including the CSRF header). Where `handlers.ts` is silent on a case, mirror the closest existing endpoint and call the gap out — don't invent.
- **Fail loudly.** No bare `except`, no catch-log-continue, no quiet fallbacks: `raise err(...)` for expected failures, let the unexpected propagate to the error envelope. If something must stay unfinished, keep the loud-stub convention (`NotImplementedError` → 404), never a silent fake. No stray TODOs — flag leftovers in your summary instead.
- **Async end-to-end** in the backend request path: no sync DB calls, `requests`, or `time.sleep` inside an `async def`. Type hints on everything public.
- **Comments earn their keep.** Explain *why* — domain rules, gotchas, decisions — never narrate what the code does. Preserve the `# + api` markers in `models.py`. Exception: docstrings in `agent/tools.py` are prompts the model reads (see Agent internals) — hold them to the same review bar as code and update them whenever tool behavior changes.
- **No drive-by fixes.** Unrelated problems get mentioned, not silently changed.

**Definition of done** — don't claim a change works until:
- Python (backend & agent alike): `./venv/bin/ruff check` and `./venv/bin/ruff format --check` pass;
- backend: `./venv/bin/pytest` green, plus `./venv/bin/alembic check` if models moved;
- frontend: `npm run build` (the type gate) and `npm run lint` green; UI changes verified through `frontend:verify`;
- the diff reads like it was written by whoever wrote the file it touches.

## Agent internals

`main.py` → `agent.run()` does two passes per invocation: (1) re-check every active listing (`get_listed_items`) for price/availability; (2) scan sites for new listings for each notify-enabled `(watch, site)` pair (`get_watched_item_list`), skipping already-known and previously-rejected URLs (`listing_checks`). The DB-writing tools in `agent/tools.py` are exposed to the LLM — **their docstrings are the tool descriptions the model reads**, so keep them accurate and imperative. The provider is pluggable via `AI_PROVIDER`/`AI_MODEL`/`AI_URL`/`AI_API_KEY` (any LangChain `init_chat_model` provider).
