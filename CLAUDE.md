# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Snagr — a self-hosted price tracker. Four independently-deployed components in one repo, sharing **one Postgres database on the LAN** (not in `docker-compose.yml`; each component points at it via `DATABASE_URL`):

- **`agent/`** — the hunter. A daemon that claims jobs from a `jobs` table in Postgres and works them: hunting one (watch, site) pair with a LangChain agent over a headless browser (Playwright MCP), re-reading one listing's price (usually with no model at all), or refreshing an item's market stats. `main.py --serve`, or `--once` under cron.
- **`backend/`** — FastAPI (async SQLAlchemy 2.0 / asyncpg) JSON API under `/api`. Serves the frontend, queues work for the hunter, and exposes the same operations to agents as MCP tools at `POST /api/mcp` (`app/mcp/`).
- **`frontend/`** — React 19 + Vite + TS + Tailwind v4 SPA. Talks to the backend over same-origin `/api`.
- **`vision/`** — optional visual-authenticity sidecar (FastAPI + DINOv3 embeddings, sync psycopg, S3-compatible object store — MinIO under compose). Off unless `VISION_SIDECAR_URL` is set in `backend/.env` and the agent's env (D-V1); the compose `vision` profile only *starts* the sidecar, it does not switch the feature on.

## Read these first

The architecture is documented in depth — prefer reading them over re-deriving:

- `backend/STRUCTURE.md` — every backend file's job, the layer model, endpoint→file lookup, and the non-obvious domain rules. **Read before touching the backend.**
- `frontend/README.md` — frontend scripts, mock mode, structure.

Every route in `frontend/src/api/endpoints.ts` is implemented — no stubs remain
in `backend/app/`. Treat the frontend contract as the spec for anything new.

## Commands

`backend/`, `agent/`, and `vision/` each have their own `venv/` — invoke tools via `./venv/bin/<tool>` (don't assume a global install). Python style in all three is enforced by **ruff**:

```bash
./venv/bin/ruff check --fix && ./venv/bin/ruff format   # lint + autoformat — run on what you touched before calling it done
```
CI lints the whole repo with a pinned `ruff==0.16.2` (`.github/workflows/ci.yml`) — keep each venv on that version or local and CI results diverge.

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
npm run dev        # dev server on :5173 (proxies /api -> localhost:8000)
npm run build      # tsc -b + vite build; fails on type errors
npm run lint       # oxlint
```
To verify frontend changes in a real browser, use the **`frontend:verify`** skill (build + launch + drive), not the generic verify skill.

**Agent** (from `agent/`): `./venv/bin/python main.py --serve` — the daemon: LISTENs on `snagr_jobs`, claims work as it appears, and runs the scheduler (stale grounding, the job reaper, retention). `--once` queues what is due, drains the queue until empty and exits — the cron shape. There is no bare mode: argparse prints the usage and exits 2, so a typo can no longer start an expensive sweep silently. Both modes need the `AI_*` provider vars, `DATABASE_URL` and `PLAYWRIGHT_MCP_URL` (see `agent/.env.example`); the MCP server **must** run with `--isolated`.

**Vision** (from `vision/` — optional; the whole feature is off unless `VISION_SIDECAR_URL` is set in `backend/.env` + `agent/.env`, or `agent/.env.docker` with the value `http://vision:8100` under compose):
```bash
./venv/bin/uvicorn app:app --port 8100   # dev server (sync handlers by design — not the backend's async rule)
./venv/bin/pytest                         # tests: embedder + S3 stubbed, never downloads weights; needs Postgres
```
Real (non-degraded) scoring needs the DINOv3 weights loaded: they are license-gated, so accept the license and set `HF_TOKEN` in `vision/.env` for the first download. `/health` reports `degraded` whenever `embedder.load()` fails for *any* reason (no token, no network, a torch↔torchvision mismatch, a wrong `VISION_MODEL`) — `/check-images` and `/references` then answer 503 with the license help while `/images` and `/rescore` keep working. Degraded is a supported steady state, not a crash.

**Docker (dev)**: `docker compose up --build` → frontend on `:8081`, backend on `:8000`, plus the hunter (`main.py --serve` — this is what makes UI-triggered hunts and checks actually run). It needs `backend/.env`, `agent/.env` **and** `agent/.env.docker` to exist — the last is gitignored with no example file, and compose refuses to start without it. `docker compose --profile vision up --build` adds the vision sidecar (`:8100`) and its MinIO (in-network only, no published port), and needs `vision/.env` whose `S3_ACCESS_KEY`/`S3_SECRET_KEY` match the compose MinIO root credentials — plain `up` is unchanged without the profile. Postgres and the Playwright MCP are external. Editing `backend/app/**` hot-reloads; changing `requirements.txt`, frontend, or agent code needs `--build`.

## Testing model

`backend/tests/conftest.py` redirects `DATABASE_URL` to a throwaway `snagr_test` DB (same server, `/snagr_test` suffix) **before importing `app.*`**, so tests never touch live data — but they still need a reachable Postgres. Schema is built from `Base.metadata.create_all` (after `CREATE EXTENSION IF NOT EXISTS vector` — the test role must own its DB); each test starts from truncated tables. `pytest.ini` sets `asyncio_mode=auto` (no `@pytest.mark.asyncio` needed). Mutating requests in tests must carry the `CSRF` header (exported from `conftest`). `vision/tests/conftest.py` mirrors the same pattern with a `snagr_test_vision` DB; the embedder and S3 store are stubbed there so CI never downloads weights.

## The contract is the frontend (backend builds *to* it, doesn't design it)

There is no separate API spec — the frontend defines the exact contract the backend must satisfy:
- `frontend/src/api/endpoints.ts` — the route list: 58 functions covering 58 of the backend's 63 routes. The other five are never `fetch`ed — `/api/auth/refresh` (`client.ts`), `/api/events` (`EventSource`), `/api/vision/images/{key}` (`<img src>`), and the OIDC pair `/api/auth/oidc/login` + `/api/auth/oidc/callback` (plain browser navigation)
- `frontend/src/api/types.ts` — exact request/response JSON shapes; Pydantic schemas in `backend/app/schemas/` mirror these field-for-field
- `frontend/src/mocks/handlers.ts` — the behavioral oracle: status codes and `error.code` for every case. When in doubt about behavior, match what the mock does.

The frontend hits the real backend by default (`.env.development` sets `VITE_USE_MOCKS=false`, and `main.tsx` only starts MSW when the value is exactly `'true'`); run `VITE_USE_MOCKS=true npm run dev` for the full MSW mock. Unimplemented endpoints 404, which doubles as the visible build checklist.

## Backend architecture

Request flow: **router** (HTTP, validation, status codes) → **service** (multi-step logic, only where non-trivial) → **models/database** (SQL). `schemas/` are the JSON shapes; `core/` holds cross-cutting concerns (error envelope, auth deps, hashing/tokens); `config.py` is the *only* place env vars are read (via the `settings` singleton — never `os.getenv`). Thin CRUD routes may call the DB directly; only nine services exist, for real logic (item mapping + the read serializers, catalog serializers, aggregation math, the job queue's API side, SSE, OIDC login, the vision sidecar client + review/library flows, the notification outbox dispatcher, the API-token lookup) — the last few exist because the REST routers and the MCP tools in `app/mcp/` are two callers of the same logic.

Two things that will trip you up if you skip STRUCTURE.md:

1. **An API "item" is three tables.** `items` (shared catalog) + the caller's `watches` row (target_price, criteria, selection_mode, etc.) + `watch_sites` (the `site_ids` subset). `GET /api/items` lists the *user's watches*, not the global catalog. `POST /api/items` = find-or-create item + create watch + insert watch_sites.
2. **Many response fields are computed, not stored** — `best_price`, `avg_price`, `spark`, `pct_change_range`, dashboard tiles, `last_checked_at`, counts — all derived from `listings` + `price_checks` in `services/aggregates.py`. Don't add columns for them.

## Schema ownership (Decision D1)

The **backend owns the canonical schema and all Alembic migrations** (`backend/app/models.py` + `backend/migrations/`). The agent (`agent/database.py`) and the vision sidecar (`vision/db.py`) each keep a **column-compatible subset** of the same ORM models — do not restructure them, and never run `Base.metadata.create_all()` from either against the live DB. Schema changes go through a new Alembic revision. `# + api` comments in `models.py` mark columns the backend added on top of the agent's original schema. Since migration 009 the schema needs the **pgvector** extension (see README → Requirements); the migration prechecks `pg_extension` and fails with instructions rather than running `CREATE EXTENSION` itself (superuser-only).

## Cross-cutting invariants (from the contract; hold everywhere in the backend)

- **Prices are decimal strings** (`"549.99"`), never numbers. `null` for unknown, never `0`. (Stored `Numeric(10,2)`, serialized with `str()`.)
- **Timestamps are ISO-8601 UTC strings**; all DB datetimes are `timezone=True`.
- **Errors always use** `raise err(status, code, message, **extra)` → `{"error": {...}}`. Never FastAPI's default `{"detail": ...}`.
- **Paginated** = `{data, meta: {page, per_page, total}}`; **plain list** = `{data: [...]}`.
- **Mutations require the `X-Snagr-Csrf` header** (`csrf_guard`); reject with 403 if absent. The frontend always sends it.
- **`/api/auth/*` returns 401 directly** — it must not trip the client's refresh-retry loop (`frontend/src/api/client.ts` refreshes once + retries on 401 for all *other* paths).
- Auth is httpOnly-cookie sessions: short-lived access JWT (`snagr_access`) + DB-backed rotating refresh token (`sessions` table, `snagr_refresh` cookie). JS never sees the token.
- **Vision routes are gated on `settings.vision_enabled`**: with `VISION_SIDECAR_URL` unset, every mutation **and the image proxy** answer 503 `vision_unavailable`, the two GET lists return empty data, and `InstanceInfo.vision_enabled: false` hides every vision surface in the UI.
- **API tokens are the second credential** (`Authorization: Bearer snagr_pat_…`, minted in Settings → MCP & API, sha256 at rest): `current_user` accepts them next to the cookie, they are exempt from the CSRF header, scoped `read` (GET) / `write` (other methods) / `jobs` (queue + cancel), and never reach `/api/auth/me`, `/api/me/*`, `/api/admin/*` (403 `forbidden`). `POST /api/mcp` is bearer-only; its tools (`app/mcp/tools/`) call the same services as the routers and return the same schemas, with an `ApiError` surfacing as a tool error carrying the REST envelope. `MCP_ENABLED=false` switches all of it off.

## Writing code (house rules)

This is FOSS: optimize for the next reader, who has zero context and wrote none of it. Boring and explicit beats clever.

- **Match the neighbors.** ruff settles formatting; everything it can't see is settled by precedent. Before writing, open a sibling that does the same kind of job (the router next to your router, the test next to your test) and copy its idioms — naming, structure, how it's organized. New code should be indistinguishable from existing code. Keep diffs minimal and boring to review; don't churn lines you aren't otherwise changing.
- **Smallest change that satisfies the contract.** No speculative abstraction — a helper, base class, or *tenth* service needs a second real caller before it exists (thin CRUD living in routers is deliberate, not debt). No new dependencies without asking first: every dep is something self-hosters install and maintainers audit.
- **Every behavior change lands with a test.** Bug fix = reproduce with a failing test first, then fix. New endpoint = tests asserting status codes and `error.code` exactly as `handlers.ts` does — error paths included, not just the happy path. Backend tests run against the real throwaway DB, so don't mock the ORM; use the `conftest` fixtures (including the CSRF header). Where `handlers.ts` is silent on a case, mirror the closest existing endpoint and call the gap out — don't invent.
- **Fail loudly.** No bare `except`, no catch-log-continue, no quiet fallbacks: `raise err(...)` for expected failures, let the unexpected propagate to the error envelope. If something must stay unfinished, leave the route unregistered (it 404s, which is the build checklist) or `raise err(501, ...)` — never a silent fake. Nothing maps a bare `NotImplementedError` to anything but a 500. No stray TODOs — flag leftovers in your summary instead.
- **Async end-to-end** in the backend request path: no sync DB calls, `requests`, or `time.sleep` inside an `async def`. Type hints on everything public.
- **Comments earn their keep.** Explain *why* — domain rules, gotchas, decisions — never narrate what the code does. Preserve the `# + api` markers in `models.py`. Exception: docstrings in `agent/tools.py` are prompts the model reads (see Agent internals) — hold them to the same review bar as code and update them whenever tool behavior changes.
- **No drive-by fixes.** Unrelated problems get mentioned, not silently changed.

**Definition of done** — don't claim a change works until:
- Python (backend, agent & vision alike): `./venv/bin/ruff check` and `./venv/bin/ruff format --check` pass;
- backend: `./venv/bin/pytest` green, plus `./venv/bin/alembic check` if models moved;
- frontend: `npm run build` (the type gate) and `npm run lint` green; UI changes verified through `frontend:verify`;
- the diff reads like it was written by whoever wrote the file it touches.

## Agent internals

`main.py --serve` → `worker.serve()`: two pools claim jobs from `jobs` and work them. The check pool (`RECHECK_CONCURRENCY`, browser, a model only when it has to) runs `recheck` jobs; the hunt pool (`HUNT_CONCURRENCY`, model + browser) runs `hunt` and `ground` jobs. Wake-ups come from `LISTEN snagr_jobs` and a 30 s tick that runs the same drain, so nothing depends on a NOTIFY arriving. Every job opens and closes its own MCP session — with `--isolated` that is its own browser context, which is what lets "check prices now" overtake a hunt instead of queueing behind it. The scheduler task reaps abandoned jobs, queues due grounding and prunes terminal rows on the retention clocks.

**The queue is the design** (`agent/jobs.py`, `backend/app/services/jobs.py`, migration 015). A partial unique index allows at most one *open* job per target, so "check this listing now" is an UPDATE of the pending row rather than a second row, every insert is `ON CONFLICT DO NOTHING`, and `POST /api/jobs` never needs a 409. A listing always has exactly one recheck ahead of it: completing one inserts the next in the same transaction, and so does failing one — a listing that dropped out of the queue would silently stop being watched. `claim` is one `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED)` statement that is blind to paused sites. A watch is hunted when it is created and when a person asks; rechecks recur at the watch's own `recheck_interval_minutes`, else `RECHECK_INTERVAL_MINUTES`, never below `RECHECK_INTERVAL_FLOOR_MINUTES` (set both in `backend/.env` too — the UI reads the default from it and the API refuses an interval below the floor).

**Most rechecks never reach the model.** The first time the LLM confirms a listing's price, code — never the model — reads the page it is on, finds what holds that exact number, replays it once to verify, and stores it on the listing (`agent/locators.py`: `price_locator`, `locator_kind`, priority `jsonld → meta → microdata → css`). A recheck job then runs `recheck_deterministic` (`agent/recheck.py`) first: the static rung (a plain GET, when the learn-time probe proved the same locator works against raw HTML — `static_ok`, `agent/static.py`), then one browser page load and the read ladder (the listing's locator → the site's consensus locator → the structured fallbacks). The LLM is the fallback, and its read is what relearns a broken locator; `CHEAP_RECHECK=false` puts every recheck back through it. `price_checks.method` records which path read each price (`llm` | `jsonld` | `meta` | `microdata` | `locator`), and `§7 query 1` in `docs/design/perpetual-hunter.md` is how you measure it.

**A site that stops answering is left alone** (`agent/breaker.py`, decision 12). `SITE_BREAKER_ERRORS` consecutive read errors pause the site for `SITE_BREAKER_MINUTES`, doubling per trip to `SITE_BREAKER_CAP_MINUTES`; any successful read wipes the count. Paused means invisible — the claim query skips the site's work, its pending jobs are pushed out to the moment the pause lifts, and no model is spent on it — so a bot wall costs five reads instead of every listing every interval forever. The trip writes a `warn` job event on the job that caused it, and `PATCH /api/sites/{id}` with `paused_until: null` lifts it by hand.

**Nothing believes a page on sight** (`agent/validation.py`). `validate_observation` refuses a reading that is not a price at all (auction-only page, wrong shape) and *disbelieves* one outside the plausibility bands: it is recorded with `confirmed = false`, never notifies, and is excluded from every aggregate until a later read lands within 1% of it. `url_allowed` keeps a stored listing URL inside the site's own registrable domain and off the private network — and now guards every navigation too, through the thin `browser_navigate` wrapper the model is given instead of the real tool (the list also drops code execution, file upload and tab control). `clip_text` caps the model-typed strings that reach prompts and notification bodies. **One writer owns the observation**: `agent/observations.py::record_price_check` writes the check, takes the notify cooldown, queues the outbox row and — on a hunt — writes the job event, all in one transaction under a row lock on the watch, with the notification steps inside a savepoint: an observation beats a notification, always. A watch's `notify` flag gates alerting only — a muted watch is still hunted and rechecked, its finds just aren't announced. The DB-writing tools in `agent/tools.py` are exposed to the LLM — **their docstrings are the tool descriptions the model reads**, so keep them accurate and imperative. Which watch, item, site and (on a recheck) listing a tool call is about is bound by the orchestrator per unit (`observations.UnitContext` on the run config, read through the injected `ToolRuntime`), never a model-supplied argument; the unit also carries the job's id and its own stats tally, because several jobs run at once. **Notifications: the agent detects, the backend delivers.** `save_price_check` queues a `target.hit` and `save_listing` a `listing.new` into `notification_outbox` (migration 010's trigger wakes the backend dispatcher, `backend/app/services/notifications.py`, which fans out to the user's channels — ntfy/Discord/webhook — and owns retries). The agent writes events because it is the only writer of `price_checks`/`listings`; it never contacts a push service. `target.hit` is edge-triggered — only a price that *crosses* the watch's target enqueues, stamped on `watches.last_notified_at` at enqueue (`NOTIFY_COOLDOWN_HOURS` is the spam floor) — and never raises, because losing the observation to a failed enqueue would be worse than losing the notification.

**A job is never left `running` by a dead process:** the worker heartbeats `jobs.heartbeat_at`, the scheduler takes back any job silent past `JOB_STALE_AFTER_SECONDS` (`jobs.reap` — back to `pending`, or `failed` past `JOB_MAX_ATTEMPTS`), SIGTERM/SIGINT hand every in-flight job back in one statement on the way out (`main.py` → `_supervised` → `worker.serve`'s finally), and every unit is capped by `AGENT_MAX_STEPS` and `AGENT_UNIT_TIMEOUT_SECONDS`. **Hunts write job events, rechecks write none** — a recheck's whole output is its `price_checks` row, which migration 015's trigger turns into a `listing.checked` frame. The provider is pluggable via `AI_PROVIDER`/`AI_MODEL`/`AI_URL`/`AI_API_KEY` (any LangChain `init_chat_model` provider), built on demand by `agent/llm.py` so the check pool pays for a model only when it needs one. The knobs are all optional and all in `agent/.env.example`.
