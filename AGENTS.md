# AGENTS.md

The working guide for anyone — person or coding agent — changing code in this repo. `CLAUDE.md` imports this file; edit this one.

## What this is

Snagr — a self-hosted price tracker. Four independently-deployed components in one repo, sharing **one Postgres database** (pgvector required; not in `docker-compose.yml` — each component points at it via `DATABASE_URL`):

- **`agent/`** — the hunter. A daemon that claims jobs from a `jobs` table in Postgres and works them: hunting one (watch, site) pair with a LangChain agent over a headless browser (Playwright MCP), re-reading one listing's price (usually with no model at all), or refreshing an item's market stats (plain HTTP + SearXNG, with a model to parse what it fetched). `main.py --serve`, or `--once` under cron.
- **`backend/`** — FastAPI (async SQLAlchemy 2.0 / asyncpg) JSON API under `/api`. Serves the frontend, queues work for the hunter, delivers notifications, and exposes the same operations to agents as MCP tools at `POST /api/mcp` (`app/mcp/`).
- **`frontend/`** — React 19 + Vite + TS + Tailwind v4 SPA. Talks to the backend over same-origin `/api`.
- **`vision/`** — optional visual-authenticity sidecar (FastAPI + DINOv3 embeddings, sync psycopg, S3-compatible object store — MinIO under compose). Off unless `VISION_SIDECAR_URL` is set in `backend/.env` and the agent's env.

External services the stack needs but doesn't ship: Postgres, a Playwright MCP server, a SearXNG instance (market-price grounding), an LLM provider.

## Read these first

The architecture is documented in depth — prefer reading these over re-deriving:

- [`backend/STRUCTURE.md`](backend/STRUCTURE.md) — every backend file's job, the layer model, endpoint→file lookup, and the non-obvious domain rules. **Read before touching the backend.**
- [`agent/STRUCTURE.md`](agent/STRUCTURE.md) — every agent module's job, the job lifecycle, the queue/hunting/recheck rules, and the full env reference. **Read before touching the agent.**
- [`frontend/README.md`](frontend/README.md) — scripts, mock mode, structure, and the "Night Hunt" design system.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup, the test contract, the conventions CI enforces.
- [`docs/design/`](docs/design/) — the design records behind the hunter (`perpetual-hunter.md`, with its numbered decisions) and the Activity page. Their "current state" sections describe the code *as it was* when the design was written; the STRUCTURE docs describe it as it is.

## Commands

`backend/`, `agent/` and `vision/` each have their own `venv/` — invoke tools via `./venv/bin/<tool>` (don't assume a global install). Runtime floors: **Python 3.14** (the backend and agent both use 3.14-only syntax, e.g. unparenthesized `except A, B:`) and **Node 22**.

| | Run | Test | Lint / format |
|---|---|---|---|
| `backend/` | `./venv/bin/uvicorn app.main:app --reload --port 8000` | `./venv/bin/pytest` | `./venv/bin/ruff check --fix && ./venv/bin/ruff format` |
| `agent/` | `./venv/bin/python main.py --serve` (or `--once`) | `./venv/bin/pytest` | same |
| `vision/` | `./venv/bin/uvicorn app:app --port 8100` | `./venv/bin/pytest` | same |
| `frontend/` | `npm run dev` (`:5173`, proxies `/api` → `:8000`) | `npm test` (vitest) | `npm run lint` (oxlint) + `npm run build` (the type gate) |

CI lints the whole repo with a pinned `ruff==0.16.2` (`.github/workflows/ci.yml`) — keep each venv on that version or local and CI results diverge.

Backend extras (from `backend/`):
```bash
./venv/bin/pytest tests/test_auth_flow.py -v            # one file
./venv/bin/pytest -k invite                             # tests matching a name
./venv/bin/alembic upgrade head                         # apply migrations
./venv/bin/alembic revision --autogenerate -m "msg"     # new migration (inspect before committing)
./venv/bin/alembic check                                # models vs. migrations agree
```

**Agent:** there is no bare mode — `main.py` without `--serve`/`--once` prints usage and exits 2, so a typo can't start an expensive sweep silently. Both modes need the `AI_*` provider vars, `DATABASE_URL` and `PLAYWRIGHT_MCP_URL` (plus `SEAR_XNG_URL` for grounding; see `agent/.env.example`); the MCP server **must** run with `--isolated`.

**Vision:** handlers are sync by design (not the backend's async rule). Real scoring needs the license-gated DINOv3 weights (`HF_TOKEN` in `vision/.env` for the first download). `/health` reports `degraded` whenever `embedder.load()` fails for *any* reason — `/check-images` and `/references` then answer 503 while `/images` and `/rescore` keep working. Degraded is a supported steady state, not a crash.

### Testing model

Every Python suite redirects `DATABASE_URL` to a throwaway database on the same server **before importing app code**, and asserts the rewrite changed the URL — tests never touch live data, but they need a reachable Postgres with pgvector.

- **`backend/` and `agent/` share `snagr_test`**, and both truncate it. **Never run the two suites at the same time** against one server. `vision/` uses its own `snagr_test_vision`.
- The test role must own its databases (the backend and vision suites run `CREATE EXTENSION IF NOT EXISTS vector`) and needs `CREATEDB`: `backend/tests/test_migrations.py` builds a scratch `snagr_test_migrations` DB to run the real Alembic chain.
- Schema comes from `Base.metadata.create_all`, which knows nothing about triggers or expression indexes — so `backend/tests/conftest.py` and `agent/tests/conftest.py` each hand-copy migration 015's triggers and the open-job partial index. **A migration that adds a trigger or such an index must update both conftests.**
- Backend: `pytest.ini` sets `asyncio_mode=auto`; mutating requests must carry the `CSRF` header exported from `conftest`. Agent: the suite is sync, and `tests/fixtures/` holds captured marketplace pages (see its README). Vision: the embedder and S3 store are stubbed, so CI never downloads weights.
- Frontend: vitest over `src/**/*.test.ts` — pure logic only (e.g. `features/items/rail.test.ts`); behavior at the browser surface is verified by driving the app.

### Docker (dev)

`docker compose up --build` → frontend on `:8081`, backend on `:8000`, plus the hunter (`main.py --serve` — this is what makes UI-triggered hunts and checks actually run). The README's [Quick start](README.md#quick-start) is the walkthrough; the gotchas:

- It needs `backend/.env`, `agent/.env` **and** `agent/.env.docker` — the last is gitignored with no example file, and compose refuses to start without it. It re-points `DATABASE_URL` / `PLAYWRIGHT_MCP_URL` (and `VISION_SIDECAR_URL=http://vision:8100` under the vision profile) at hosts the container can reach.
- The agent image's baked-in command is `main.py --once` (the cron shape); compose overrides it with `--serve`.
- `docker compose --profile vision up --build` adds the sidecar (`:8100`) and its MinIO (in-network only). The profile only *starts* the sidecar — it does not switch the feature on; `vision/.env`'s `S3_ACCESS_KEY`/`S3_SECRET_KEY` must match the compose MinIO root credentials.
- Running compose from a git worktree? Pass `-p snagr`, or compose names the project after the worktree directory and starts a second stack.
- Postgres and the Playwright MCP are external. Editing `backend/app/**` hot-reloads; changing `requirements.txt`, frontend, or agent code needs `--build`.

## The contract is the frontend (the backend builds *to* it, doesn't design it)

There is no separate API spec — the frontend defines the exact contract the backend must satisfy:

- `frontend/src/api/endpoints.ts` — the route list: 58 functions covering 58 of the backend's 63 REST routes. The other five are never `fetch`ed — `/api/auth/refresh` (`client.ts`), `/api/events` (`EventSource`), `/api/vision/images/{key}` (`<img src>`), and the OIDC pair `/api/auth/oidc/login` + `/api/auth/oidc/callback` (plain browser navigation). `POST /api/mcp` sits outside the REST surface entirely (bearer-only, for agents).
- `frontend/src/api/types.ts` — exact request/response JSON shapes; Pydantic schemas in `backend/app/schemas/` mirror these field-for-field.
- `frontend/src/mocks/handlers.ts` — the behavioral oracle: status codes and `error.code` for every case. When in doubt about behavior, match what the mock does.

The frontend hits the real backend by default (`.env.development` sets `VITE_USE_MOCKS=false`; `main.tsx` starts MSW only when the value is exactly `'true'`). `VITE_USE_MOCKS=true npm run dev` runs the full mock (sign in `demo@snagr.dev` / `snagr`). New API work starts in `types.ts` + `handlers.ts`, then the backend follows.

## The backend in one screen

Request flow: **router** (HTTP, validation, status codes) → **service** (multi-step logic, only where non-trivial) → **models/database** (SQL). `schemas/` are the JSON shapes; `core/` holds cross-cutting concerns (error envelope, auth deps, hashing/tokens); `config.py` is the *only* place env vars are read (via the `settings` singleton — never `os.getenv`). Thin CRUD routes may call the DB directly; only nine services exist, for real logic — several because the REST routers and the MCP tools in `app/mcp/` are two callers of the same logic.

Two things that will trip you up (the full list is STRUCTURE.md's "Five things that aren't obvious"):

1. **An API "item" is three tables.** `items` (shared catalog) + the caller's `watches` row (target_price, criteria, selection_mode, max_listings, hunt, …) + `watch_sites` (the `site_ids` subset). `GET /api/items` lists the *user's watches*, not the global catalog.
2. **Many response fields are computed, not stored** — `best_price`, `avg_price`, `spark`, `pct_change_range`, dashboard tiles, `last_checked_at`, counts — derived from `listings` + `price_checks` in `services/aggregates.py`, and every price read filters `price_checks.confirmed`. Don't add columns for them.

Invariants that hold everywhere (details in STRUCTURE.md → Conventions):

- **Prices are decimal strings** (`"549.99"`), never numbers; `null` for unknown, never `0`. **Timestamps are ISO-8601 UTC**; DB datetimes are `timezone=True`.
- **Errors always** `raise err(status, code, message, **extra)` → `{"error": {...}}`, never FastAPI's `{"detail": ...}`. **Paginated** = `{data, meta: {page, per_page, total}}`; **plain list** = `{data: [...]}`.
- **Mutations require the `X-Snagr-Csrf` header** (`csrf_guard`, 403 without it); bearer callers are exempt. **`/api/auth/*` returns 401 directly** — it must not trip the client's refresh-retry loop.
- **Auth** is httpOnly-cookie sessions (short-lived `snagr_access` JWT + DB-backed rotating `snagr_refresh`); JS never sees a token. **API tokens** (`Authorization: Bearer snagr_pat_…`, sha256 at rest) are the second credential: scoped `read` / `write` / `jobs`, never reach `/api/auth/me`, `/api/me/*` or `/api/admin/*` (403 `forbidden`). `MCP_ENABLED=false` switches bearer auth and `/api/mcp` off.
- **Vision routes are gated on `settings.vision_enabled`**: unset, every mutation and the image proxy answer 503 `vision_unavailable`, the two GET lists return empty data, and `InstanceInfo.vision_enabled: false` hides every vision surface.

## Schema ownership

The **backend owns the canonical schema and all Alembic migrations** (`backend/app/models.py` + `backend/migrations/`, a linear chain currently ending at 019). The agent (`agent/database.py`) and the vision sidecar (`vision/db.py`) each keep a **column-compatible subset** of the same ORM models — don't restructure them, and never run `Base.metadata.create_all()` from either against the live DB. Schema changes go through a new Alembic revision (and, if it adds triggers, the two conftests — see Testing model). `# + api` comments in `models.py` mark columns the backend added on top of the agent's original schema. Migration 009 needs the **pgvector** extension and prechecks `pg_extension`, failing with instructions rather than running `CREATE EXTENSION` itself (superuser-only).

## The agent in one screen

`main.py --serve` → `worker.serve()`: a check pool runs `recheck` jobs (browser, a model only when it has to) and a hunt pool runs `hunt` (model + browser) and `ground` (HTTP + SearXNG + a model, no browser) jobs. Wake-ups come from `LISTEN snagr_jobs` plus a 30 s tick; every job opens its own MCP session (its own browser context under `--isolated`). A housekeeping task reaps abandoned jobs, queues due grounding, sweeps for watches whose hunt chain dropped, and prunes old rows. Most rechecks never reach the model: a learned price locator (or a plain HTTP GET) reads the price, and the LLM is the fallback. [`agent/STRUCTURE.md`](agent/STRUCTURE.md) has the whole of it; the rules you must not break:

- **The queue is the design.** One *open* job per target (migration 015's partial unique index); every insert is `ON CONFLICT DO NOTHING`; "check now" updates the pending row. **A listing always has exactly one recheck ahead of it** — completing *or* failing one inserts the next in the same transaction, or the listing silently stops being watched.
- **Paused sites are invisible.** The claim query skips jobs on a site the circuit breaker paused, so nothing spends a model on a bot wall.
- **Tool docstrings in `agent/tools.py` are prompts** — they are the tool descriptions the model reads. Hold them to code-review standard and update them whenever tool behavior changes.
- **The model never chooses what it may write to.** Which watch, item and site a tool call is about is bound per unit by the orchestrator (`observations.UnitContext`, read through the injected `ToolRuntime`); a `listing_id` the model passes is checked against that unit (`observations.assert_writable`) before anything is written.
- **One writer owns the observation.** `observations.record_price_check` writes the check, the notify cooldown, the outbox row and the hunt's job event in one transaction, notifications inside a savepoint: an observation beats a notification, always.
- **Nothing believes a page on sight.** `agent/validation.py` refuses non-prices, disbelieves implausible ones (recorded with `confirmed = false` and kept out of every aggregate; the next read, if within 1% of it, is believed), and keeps every URL on the site's own domain and off the private network.
- **The agent detects, the backend delivers.** The agent only writes `notification_outbox` rows; it never contacts a push service.

## Writing code (house rules)

This is FOSS: optimize for the next reader, who has zero context and wrote none of it. Boring and explicit beats clever.

- **Match the neighbors.** ruff settles formatting; everything it can't see is settled by precedent. Before writing, open a sibling that does the same kind of job (the router next to your router, the test next to your test) and copy its idioms — naming, structure, how it's organized. New code should be indistinguishable from existing code. Keep diffs minimal and boring to review; don't churn lines you aren't otherwise changing.
- **Smallest change that satisfies the contract.** No speculative abstraction — a helper, base class, or *tenth* service needs a second real caller before it exists (thin CRUD living in routers is deliberate, not debt). No new dependencies without asking first: every dep is something self-hosters install and maintainers audit.
- **Every behavior change lands with a test.** Bug fix = reproduce with a failing test first, then fix. New endpoint = tests asserting status codes and `error.code` exactly as `handlers.ts` does — error paths included, not just the happy path. Backend tests run against the real throwaway DB, so don't mock the ORM; use the `conftest` fixtures (including the CSRF header). Where `handlers.ts` is silent on a case, mirror the closest existing endpoint and call the gap out — don't invent.
- **Fail loudly.** No bare `except`, no catch-log-continue, no quiet fallbacks: `raise err(...)` for expected failures, let the unexpected propagate to the error envelope. If something must stay unfinished, leave the route unregistered (it 404s) or `raise err(501, ...)` — never a silent fake. Nothing maps a bare `NotImplementedError` to anything but a 500. No stray TODOs — flag leftovers in your summary instead.
- **Async end-to-end** in the backend request path: no sync DB calls, `requests`, or `time.sleep` inside an `async def`. Type hints on everything public.
- **Comments earn their keep.** Explain *why* — domain rules, gotchas, decisions — never narrate what the code does or how it got that way (no "used to", no PR/phase labels, no bare decision codes). Full rules in `CONTRIBUTING.md` → Comments & docstrings. Preserve the `# + api` markers in `models.py`. Exception: docstrings in `agent/tools.py` are prompts (above).
- **No drive-by fixes.** Unrelated problems get mentioned, not silently changed.

**Definition of done** — don't claim a change works until:
- Python (backend, agent & vision alike): `./venv/bin/ruff check` and `./venv/bin/ruff format --check` pass, and that component's `./venv/bin/pytest` is green (plus `./venv/bin/alembic check` if models moved);
- frontend: `npm run build` (the type gate), `npm run lint` and `npm test` green; UI changes verified by driving the app in a real browser;
- the diff reads like it was written by whoever wrote the file it touches.

## Workflow

- **Branch off `main`; one PR per self-contained change.** PRs are squash-merged, so the **PR title is the commit history**: it must be a conventional commit (`feat|fix|refactor|test|docs|style|chore|ci|build|perf|revert`, free-form scope, e.g. `feat(agent): …`) and `.github/workflows/pr-title.yml` rejects anything else.
- **Releases are release-please's job.** `feat` bumps the minor, `fix` the patch, and each title becomes a CHANGELOG line; the release PR bumps `version.txt` and the `APP_VERSION` marker in `backend/app/config.py`. Don't edit either by hand.
- **CI is path-gated per component**: jobs for parts you didn't touch report "skipped", which satisfies the required checks. CodeQL is not path-gated, and touching `.github/workflows/**`, `ruff.toml` or `docker-compose.yml` un-skips every job. The `migrations` job runs `alembic upgrade head` + `alembic check` on a fresh database.
- **Dependency pins are Dependabot's** — don't hand-bump them in a feature PR (exceptions: `torch` in `vision/requirements.txt`, and `ruff`, whose version of record is the CI pin).
