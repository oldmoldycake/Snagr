# Snagr — Backend Requirements

This document is the API contract the frontend (`frontend/`) is built against. The frontend
currently runs against an MSW mock that implements everything below (`frontend/src/mocks/`), so
every endpoint here has been exercised by the real UI. The TypeScript mirror of this contract
lives at `frontend/src/api/types.ts` — keep the two in sync.

The backend is FastAPI + async SQLAlchemy + Postgres (already the stack in `agent/`). The agent
itself (LangGraph + Playwright MCP) runs server-side and is triggered through the run endpoints.

---

## 1. Conventions

- **Prices are decimal strings** in JSON (`"549.99"`), never floats. `Numeric(10,2)` in Postgres.
- **Timestamps** are ISO-8601 UTC strings (`"2026-07-01T09:12:44Z"`).
- **Errors** use one envelope, with an HTTP status to match:

  ```json
  { "error": { "code": "not_found", "message": "Item 42 does not exist" } }
  ```

  Validation errors (422) add a `fields` map:

  ```json
  { "error": { "code": "validation_error", "message": "Invalid input",
               "fields": { "target_price": "must be positive" } } }
  ```

- **Pagination**: `?page=1&per_page=50` →

  ```json
  { "data": [ ... ], "meta": { "page": 1, "per_page": 50, "total": 213 } }
  ```

  Sorting via `?sort=-created_at` (leading `-` = descending).

- **CSRF**: every mutating request (POST/PATCH/PUT/DELETE) carries the header `X-Snagr-Csrf: 1`.
  Reject mutations without it with 403. (A custom header forces a CORS preflight, which
  cross-site forms can't produce; combined with `SameSite=Lax` cookies this covers CSRF.)

- **Ownership**: user data (watches, listings, and the views derived from them) is private
  per-user; categories, sites, and the item catalog are shared (decision D1). Cross-user
  access is a 404, not a 403 (don't leak existence). `user_id` never appears in request
  bodies or responses, with one exception: `AgentRun.user_id` (`null` = system run) — the
  UI needs it to tell "yours" from "system"; see "Run privacy" in §7.

## 2. Auth model

JWT in **httpOnly cookies** (not Authorization headers — `EventSource` can't set headers, and
cookies make the SSE stream auth free since everything is same-origin behind nginx):

- `snagr_access` — JWT, ~15 min TTL, `HttpOnly; SameSite=Lax; Path=/api`.
- `snagr_refresh` — opaque rotating token, ~30 days, `HttpOnly; SameSite=Lax; Path=/api/auth/refresh`.
  Store hashed server-side; rotate on every refresh; revoke on logout.

Frontend behavior you must support: on any 401 (except `/api/auth/*`) it calls
`POST /api/auth/refresh` once (single-flight) and retries the original request; if refresh also
401s it redirects to `/login`.

**Registration**: open only while the instance has zero users; the first account gets
`role='admin'` and registration closes. After that, accounts are created via admin invites.

## 3. Schema changes (vs current `agent/config.py`)

1. `users` — add `password_hash TEXT NOT NULL`, `role TEXT NOT NULL DEFAULT 'user'`
   (`admin` | `user`), `is_active BOOLEAN NOT NULL DEFAULT true`, `ntfy_topic TEXT NULL`.
   (`email_verified` is unused by the frontend v1 — keep or drop.)
2. **New `invites`** — `id PK, token TEXT UNIQUE NOT NULL, email TEXT NULL,
   created_by INT FK users NOT NULL, expires_at timestamptz NOT NULL,
   accepted_at timestamptz NULL, created_at timestamptz DEFAULT now()`.
3. `categories` — add `user_id INT FK users NOT NULL`. Replace the global unique constraints
   with `UNIQUE(user_id, name)` and `UNIQUE(user_id, slug)`.
4. `sites` — add `user_id INT FK users NOT NULL`, `UNIQUE(user_id, base_url)`.
5. `site_categories` — **fix the missing-PK bug**: composite PK `(site_id, category_id)`;
   rename `categories_id` → `category_id`.
6. `items` — add `criteria TEXT NULL` (free-text natural-language criteria the agent evaluates
   listings against), `selection_mode TEXT NOT NULL DEFAULT 'cheapest'
   CHECK (selection_mode IN ('cheapest','best_match'))`, `max_listings INT NOT NULL DEFAULT 5
   CHECK (max_listings BETWEEN 1 AND 10)`. User scoping inherits through `category_id`
   (join-scope every query). Consider an index on `created_at`.
7. **New `item_sites`** junction — `item_id INT FK items, site_id INT FK sites,
   PK (item_id, site_id)`. Restricts an item's search to a subset of its category's sites
   ("Pokemon Emerald on eBay only"). **Zero rows = all category sites** (serialize as
   `site_ids: null`). Remove rows when a site is unlinked from the category.
8. `listings` — add `created_at timestamptz DEFAULT now()`,
   `discovered_by_run_id INT FK agent_runs NULL`, `title TEXT NULL` (agent-extracted listing
   title — required for telling multiple eBay listings apart), `match_score INT NULL
   CHECK (match_score BETWEEN 0 AND 100)`, and `match_summary TEXT NULL` (one-line rationale,
   e.g. "dry battery ✓, damaged case ✓, cart only"). `UNIQUE(site_id, url)` stays correct because
   sites are per-user — and note it deliberately ALLOWS many listings per site per item.
9. `price_checks` — add composite index `(listing_id, checked_at)`. `checked_at` needs a
   `server_default=now()` (currently none). Documented `status` values:
   `'ok' | 'sold' | 'ended' | 'error'` — a `sold`/`ended` check is terminal for its listing
   (the agent also sets `listings.active = false`; see §7).
10. `watches` — keep. **Auto-create** a watch (`notify=true`, `target_price=NULL`) whenever an
    item is created. `target_price NULL` means "inherit the item's target". The frontend uses the
    watch as the notify toggle plus optional per-user target override.
11. **New `agent_runs`** — `id PK, user_id INT FK users NULL` (**null = system run**,
    visible to everyone; `ON DELETE SET NULL` so deleting a user degrades their runs to
    system), `scope TEXT NOT NULL` (`global|category|site|item`), `scope_id INT NULL,
    scope_label TEXT NOT NULL, status TEXT NOT NULL`
    (`queued|running|succeeded|failed|cancelled`), `started_at timestamptz NULL,
    finished_at timestamptz NULL, stats JSONB NULL, error TEXT NULL,
    last_seq INT NOT NULL DEFAULT 0, created_at timestamptz DEFAULT now()`.
    One active run at a time, **instance-wide** (there is a single agent worker):
    checked in the API (409 `run_in_progress`), no DB-level guard.
12. **New `run_events`** — `id PK, run_id FK NOT NULL, seq INT NOT NULL` (monotonic per run),
    `ts timestamptz NOT NULL, level TEXT` (`info|success|warn|error`), `event_type TEXT`
    (`run_started|site_started|item_started|listing_check|price_found|listing_evaluated|listing_discovered|listing_ended|error|run_finished`),
    `message TEXT NOT NULL, payload JSONB NULL`. `UNIQUE(run_id, seq)`, index `(run_id, seq)`.
    The agent writes these as it works; the API tails them for SSE and backfill.
    `payload.item_id` / `payload.listing_id` are what event-level visibility keys on (§7).
13. **New `run_schedules`** — `id PK, user_id INT FK users NULL` (null = system;
    `ON DELETE SET NULL`), `scope / scope_id / scope_label` as on `agent_runs`,
    `next_due_at timestamptz NOT NULL, interval_minutes INT NULL` (NULL = one-shot),
    `enabled BOOLEAN NOT NULL DEFAULT true, last_fired_at timestamptz NULL,
    created_at timestamptz DEFAULT now()`. No CRUD endpoints yet (rows are seeded via
    SQL); when the agent's consume tick fires a due schedule, the schedule's `user_id`
    is copied onto the run it inserts.

Known bugs to fix while you're in there:
- `config.py`: `OLLAMA_MODEL = os.getenv("OLLAMA_URL", ...)` reads the wrong env var.
- `main.py`: logging format uses `%(messages)s` (should be `%(message)s`).
- `tools.py` `save_listing`: never returns the row it re-selects; `site_sku` annotated as `None`.
- Recommend `expire_on_commit=False` on the API's sessionmaker (returning ORM objects after
  commit will otherwise lazy-load on a closed session).

## 4. Endpoints

| # | Method | Path | Auth | Purpose |
|---|--------|------|------|---------|
| 1 | GET | `/api/instance` | public | Instance info: ntfy URL, `registration_open`, version |
| 2 | POST | `/api/auth/register` | public | First-user admin bootstrap; 403 `registration_closed` after |
| 3 | POST | `/api/auth/login` | public | Sets access+refresh cookies |
| 4 | POST | `/api/auth/refresh` | refresh cookie | Rotate refresh, issue new access cookie (204) |
| 5 | POST | `/api/auth/logout` | user | Clear cookies, revoke refresh token (204) |
| 6 | GET | `/api/auth/me` | user | Current user |
| 7 | GET | `/api/auth/invites/{token}` | public | Validate invite (404 invalid / 410 expired-or-used) |
| 8 | POST | `/api/auth/invites/{token}/accept` | public | Create user from invite, log them in |
| 9 | PATCH | `/api/me` | user | Update `email` / `ntfy_topic` |
| 10 | POST | `/api/me/password` | user | Change password (`current_password`, `new_password`) |
| 11 | POST | `/api/me/ntfy/test` | user | Send a test push to the user's topic (204; 422 `no_topic`) |
| 12 | GET / POST | `/api/categories` | user | List (with stats) / create `{name}` |
| 13 | PATCH / DELETE | `/api/categories/{id}` | user | Rename / delete (cascades items+listings+checks) |
| 14 | PUT | `/api/categories/{id}/sites` | user | Replace linked sites `{site_ids: [1,2]}` |
| 15 | GET / POST | `/api/sites` | user | List (with counts) / create `{name, base_url}` |
| 16 | PATCH / DELETE | `/api/sites/{id}` | user | Edit / delete (deactivates its listings) |
| 17 | GET | `/api/items` | user | Paged rollup list; filters `category_id, site_id, status, search, range, sort, page, per_page` |
| 18 | POST | `/api/items` | user | Create `{category_id, name, target_price, criteria?, selection_mode?, max_listings?, site_ids?}`; auto-creates watch |
| 19 | GET / PATCH / DELETE | `/api/items/{id}` | user | Detail incl. listings / edit name, target, criteria, mode, slots, sites / delete |
| 20 | PATCH | `/api/items/{id}/watch` | user | `{notify?, target_price?}` (target `null` = inherit item's) |
| 21 | PATCH | `/api/listings/{id}` | user | `{active: false}` — deactivate/reactivate |
| 22 | GET | `/api/items/{id}/price-checks` | user | Recent raw checks, `?limit=50` |
| 23 | GET | `/api/items/{id}/price-history` | user | Per-listing series, `?range&points` |
| 24 | GET | `/api/items/{id}/price-summary` | user | avg+best series, `?range&points` |
| 25 | GET | `/api/categories/{id}/price-change` | user | Per-item % change over `?range` |
| 26 | GET | `/api/dashboard/stats` | user | Stat tiles, `?range` |
| 27 | GET | `/api/dashboard/price-drops` | user | Recent drops, `?range&limit` |
| 28 | POST | `/api/runs` | user | Trigger run → 202 (stamps the caller as owner); 409 `run_in_progress` if one is active anywhere (instance-wide) |
| 29 | GET | `/api/runs` | user | History the viewer may see (own + system; admin: all), `?status&scope&page&per_page` |
| 30 | GET | `/api/runs/{id}` | user | Run detail with stats; 404 for unknown AND other users' runs (§7) |
| 31 | GET | `/api/runs/{id}/events` | user | Event backfill, `?after_seq=0&limit=500` — up to `limit` *visible* events (filter before limit, §7); 404 for unknown/hidden runs |
| 32 | POST | `/api/runs/{id}/cancel` | user | Cancel own queued/running run; admins cancel anything; system run → 403 `forbidden`, hidden run → 404 |
| 33 | GET | `/api/events` | user | **SSE** live stream (see §6) |
| 34 | GET | `/api/admin/users` | admin | List users with item counts |
| 35 | PATCH / DELETE | `/api/admin/users/{id}` | admin | `{is_active?, role?}` / delete user + their data |
| 36 | GET / POST | `/api/admin/invites` | admin | List pending / create `{email?}` |
| 37 | DELETE | `/api/admin/invites/{id}` | admin | Revoke invite |

`range` is one of `7d | 30d | 90d | 1y | all` (default `30d`). `points` is capped at 500.

### Representative payloads

`GET /api/instance`
```json
{ "version": "0.1.0", "ntfy_server_url": "https://ntfy.example.com", "registration_open": false }
```

`POST /api/auth/login` ← `{"email": "nolan@example.com", "password": "…"}` → 200 + cookies:
```json
{ "user": { "id": 1, "email": "nolan@example.com", "role": "admin",
            "ntfy_topic": "snagr-nolan-8f3a", "created_at": "2026-01-12T08:00:00Z" } }
```
Failure: `401 {"error": {"code": "invalid_credentials", "message": "Email or password is incorrect"}}`

`GET /api/categories`
```json
{ "data": [ { "id": 3, "name": "GPUs", "slug": "gpus", "site_ids": [1, 2, 4],
              "item_count": 4, "snagged_count": 1 } ] }
```

`GET /api/items?category_id=3&range=30d&page=1` — the rollup row every list view uses:
```json
{ "data": [ {
    "id": 42, "name": "Pokemon Emerald (GBA)",
    "category_id": 6, "category_name": "Retro Games", "category_slug": "retro-games",
    "target_price": "120.00", "currency": "USD",
    "criteria": "dry battery and damaged case preferred but not required — must be authentic",
    "selection_mode": "best_match", "max_listings": 5, "site_ids": [6],
    "best_price": "118.40", "best_listing_id": 7, "best_site_name": "ebay.com",
    "avg_price": "146.20", "active_listing_count": 4,
    "target_met": true, "pct_change_range": "-8.30",
    "last_checked_at": "2026-07-01T09:12:44Z", "created_at": "2026-05-17T00:00:00Z",
    "watch": { "id": 12, "notify": true, "target_price": null },
    "spark": ["129.99", "127.50", null, "121.00", "118.40"]
  } ],
  "meta": { "page": 1, "per_page": 50, "total": 12 } }
```
`spark` = ≤30 bucketed best-price points over the requested range (`null` = empty bucket).
`status` filter values: `all | snagged | above_target | no_listings`. `site_id` keeps only items
with a tracked listing on that site. `selection_mode`: `'cheapest' | 'best_match'`;
`site_ids: null` = all of the category's sites (from the `item_sites` junction: zero rows → null).
On create/update, `site_ids` must be a subset of the category's sites (422 otherwise); an empty or
full set normalizes to `null`. `max_listings` outside 1–10 → 422 with `fields.max_listings`.

`GET /api/items/42` — the summary shape above plus:
```json
{ "listings": [ {
    "id": 7, "site_id": 6, "site_name": "ebay.com",
    "url": "https://www.ebay.com/itm/187442198",
    "title": "Pokemon Emerald Version (GBA) Authentic — Dry Battery, Damaged Label",
    "site_sku": null,
    "active": true, "latest_price": "118.40", "in_stock": true, "latest_status": "ok",
    "match_score": 91,
    "match_summary": "dry battery ✓, damaged case ✓, authentic ✓ — cart only",
    "last_checked_at": "2026-07-01T09:12:44Z", "created_at": "2026-06-04T00:00:00Z",
    "discovered_by_run_id": 61
  },
  { "id": 9, "site_id": 6, "site_name": "ebay.com",
    "url": "https://www.ebay.com/itm/187442967",
    "title": "Pokemon Emerald Cart Only — Dead Battery, Cracked Shell",
    "site_sku": null,
    "active": false, "latest_price": "109.00", "in_stock": false, "latest_status": "sold",
    "match_score": 88,
    "match_summary": "dry battery ✓, damaged case ✓, authentic ✓",
    "last_checked_at": "2026-06-21T14:02:00Z", "created_at": "2026-06-04T00:00:00Z",
    "discovered_by_run_id": 61
  } ] }
```
`latest_status` is the `status` of the listing's most recent price check (`'ok' | 'sold' |
'ended' | 'error'`) — how the UI tells an agent-ended listing ("Sold · 10d ago") apart from one
the user toggled off. `match_score`/`match_summary` are null when the item has no criteria or the
listing was never evaluated.

`GET /api/items/42/price-history?range=90d&points=300`
```json
{ "item_id": 42, "target_price": "120.00", "currency": "USD", "range": "90d",
  "series": [ {
    "listing_id": 7, "site_name": "ebay.com",
    "title": "Pokemon Emerald Version (GBA) Authentic — Dry Battery, Damaged Label",
    "active": true,
    "points": [ { "ts": "2026-04-03T00:00:00Z", "price": "132.00", "in_stock": true },
                { "ts": "2026-06-29T00:00:00Z", "price": "118.40", "in_stock": true } ]
  } ] }
```

`GET /api/items/42/price-summary?range=30d&points=300`
```json
{ "item_id": 42, "target_price": "500.00", "currency": "USD", "range": "30d",
  "points": [ { "ts": "2026-06-02T12:00:00Z", "avg": "601.24", "best": "579.99" } ] }
```

`GET /api/categories/3/price-change?range=30d`
```json
{ "category_id": 3, "range": "30d",
  "items": [ { "item_id": 42, "name": "RTX 4070 Super", "pct_change": "-8.30",
               "old_best": "599.99", "new_best": "549.99" } ] }
```

`GET /api/dashboard/stats?range=30d` — `delta` compares against the previous equal-length period:
```json
{ "tracked_items":  { "value": 23, "delta": 3,  "spark": [18,19,19,20,21,23] },
  "active_listings": { "value": 71, "delta": 5,  "spark": [64,66,66,69,70,71] },
  "price_drops":     { "value": 9,  "delta": -2, "spark": [2,1,0,3,2,1] },
  "snagged":         { "value": 4,  "delta": 1,  "spark": [2,2,3,3,3,4] } }
```

`GET /api/dashboard/price-drops?range=30d&limit=8`
```json
{ "data": [ { "item_id": 42, "item_name": "RTX 4070 Super", "listing_id": 7,
              "site_name": "newegg.com", "old_price": "599.99", "new_price": "549.99",
              "currency": "USD", "pct_change": "-8.33",
              "checked_at": "2026-06-30T18:00:00Z" } ] }
```

`POST /api/runs` ← `{"scope": "category", "scope_id": 3}` → 202:
```json
{ "run": { "id": 88, "user_id": 7, "scope": "category", "scope_id": 3,
           "scope_label": "Category: GPUs",
           "status": "queued", "started_at": null, "finished_at": null, "stats": null,
           "error": null, "created_at": "2026-07-01T10:00:00Z", "last_seq": 0 } }
```
Conflict: `409 {"error": {"code": "run_in_progress", "message": "A run is already active", "run_id": 87}}`
`scope_label` is server-computed: `"Everything"`, `"Category: GPUs"`, `"Site: newegg.com"`, `"Item: RTX 4070 Super"`.

`GET /api/runs/88` (finished)
```json
{ "id": 88, "user_id": 7, "scope": "category", "scope_id": 3,
  "scope_label": "Category: GPUs",
  "status": "succeeded", "started_at": "2026-07-01T10:00:02Z",
  "finished_at": "2026-07-01T10:04:14Z",
  "stats": { "listings_checked": 34, "prices_found": 31, "new_listings": 2, "errors": 1 },
  "error": null, "created_at": "2026-07-01T10:00:00Z", "last_seq": 41 }
```

`GET /api/runs/88/events?after_seq=17`
```json
{ "data": [ { "run_id": 88, "seq": 18, "ts": "2026-07-01T10:01:11Z", "level": "success",
              "event_type": "price_found",
              "message": "newegg.com — RTX 4070 Super: $549.99 ✓",
              "payload": { "listing_id": 7, "item_id": 42, "price": "549.99" } } ] }
```

New event types for criteria evaluation (same envelope):
```json
{ "event_type": "listing_evaluated", "level": "info",
  "message": "ebay.com — \"Pokemon Emerald — Mint, Sealed\" — match 34, below threshold, skipped",
  "payload": { "item_id": 42, "url": "https://www.ebay.com/itm/187443001",
               "title": "Pokemon Emerald — Mint, Sealed",
               "match_score": 34, "match_summary": "condition too good — does not fit your criteria",
               "tracked": false } }

{ "event_type": "listing_ended", "level": "warn",
  "message": "ebay.com — \"Pokemon Emerald Cart Only — Dead Battery, Cracked Shell\" sold — slot freed",
  "payload": { "listing_id": 9, "item_id": 42 } }
```

`GET /api/admin/users`
```json
{ "data": [ { "id": 1, "email": "nolan@example.com", "role": "admin", "is_active": true,
              "created_at": "2026-01-12T08:00:00Z", "item_count": 23 } ] }
```

`POST /api/admin/invites` ← `{"email": "friend@example.com"}` → 201:
```json
{ "id": 5, "token": "b1946ac92492d2347c6235b4d2611184", "email": "friend@example.com",
  "expires_at": "2026-07-08T10:00:00Z", "created_at": "2026-07-01T10:00:00Z" }
```
The frontend builds the shareable link as `{origin}/invite/{token}`.

## 5. Aggregate semantics

- **Range cutoff**: series must include the last check *before* the cutoff as a synthetic first
  point (timestamp clamped to the cutoff) so step-lines don't start mid-air.
- **Downsampling**: if a listing has ≤ `points` checks in range, return them raw. Otherwise
  downsample per listing with LTTB (or equivalent), always preserving the first, last, min, and
  max points. `points` capped at 500.
- **Latest price per listing**: most recent `price_checks` row with a non-null price —
  `SELECT DISTINCT ON (listing_id) ... ORDER BY listing_id, checked_at DESC`.
- **Tracked listing** = `active = true`. Every rollup (`best_price`, `avg_price`,
  `active_listing_count`, spark, `target_met`, price-history default) computes over tracked
  listings only. An agent-ended listing is simply `active = false` with a terminal
  `sold`/`ended` price check — no separate state.
- **Item best/avg**: over *tracked* listings' latest prices only. With criteria, every tracked
  listing already passed the match bar, so "best price" remains "cheapest acceptable copy".
- **Effective target**: `COALESCE(watch.target_price, item.target_price)`.
  `target_met = best_price <= effective_target` (both non-null).
- **`pct_change_range`**: signed % between the best price as of range-start and the current best.
- **price-summary series**: bucket the range into ≤ `points` intervals; per bucket compute the
  avg and min of per-listing carried-forward latest prices (a listing's price holds until its
  next check — step semantics).
- **Price drops** (dashboard): a listing's latest price is lower than its previous distinct
  price within the range; suggested noise floor >3%. `price_drops` stat counts listings with a
  drop, not every wiggle.
- **Item list sparkline**: bucket the range into ≤30 intervals, take the min (best) price across
  the item's active listings per bucket, `null` for empty buckets.

## 6. SSE contract — `GET /api/events`

- `Content-Type: text/event-stream`, cookie-authenticated, one stream per viewer. Send
  `X-Accel-Buffering: no` and flush per event. **Every frame is per-viewer**: runs and
  events the viewer may not see (§7 Run privacy) are never sent on their stream.
- **On every connect/reconnect**, immediately send *that viewer's* snapshot — only runs
  they may see:

  ```
  event: run.snapshot
  data: {"active_runs": [{"id": 88, "user_id": 7, "status": "running", "scope": "category",
                          "scope_label": "Category: GPUs", "last_seq": 17}]}
  ```

- Per agent step (delivered only to viewers passing the event predicate, §7):

  ```
  event: run.event
  id: 88:18
  data: {"run_id": 88, "seq": 18, "ts": "...", "level": "success",
         "event_type": "price_found", "message": "newegg.com — RTX 4070 Super: $549.99 ✓",
         "payload": {"listing_id": 7, "item_id": 42, "price": "549.99"}}
  ```

- Lifecycle events: `run.started`, `run.finished`, `run.failed`, each with `data: {"run": {…}}`
  (the full AgentRun; `finished` includes `stats`). `run.finished` also fires for cancelled
  runs (status `cancelled`); `run.failed` only for status `failed`. Gated by run-row
  visibility (they carry `scope_label`).
- **Heartbeat**: comment line `: ping` every 15 seconds.
- **Reconnects**: the client does NOT rely on `Last-Event-ID` replay, and it does NOT
  infer gaps from seq arithmetic — under per-viewer filtering a viewer legitimately
  holds a sparse subset of seqs, so "my max seq < last_seq" means nothing. On every
  `run.snapshot` the client refetches `GET /api/runs/{id}/events?after_seq=<highest seq
  it holds>` and merges by seq; **the filtered response is authoritative**. `last_seq`
  in the snapshot is the run's *global* write cursor, metadata only.

## 7. Runs & the agent

- `POST /api/runs` inserts a `queued` `agent_runs` row stamped with the caller's
  `user_id`; the agent worker claims it. Return 202 immediately.
- One active run at a time, **instance-wide** (a single agent worker); concurrent
  trigger → 409 with the active `run_id` — even when the active run belongs to another
  user (the bare id leaks no metadata; the 409 itself already reveals a run is active).
- The agent, as it works: sets `status='running'` + `started_at`; appends `run_events` rows with
  monotonically increasing `seq` (fanned out per-viewer over SSE); writes `price_checks`
  (and new `listings` with `discovered_by_run_id`); finally sets terminal status + `finished_at`
  + `stats` `{listings_checked, prices_found, new_listings, errors}`.
- Scopes: `global` = every user's active listings + discovery/evaluation for every
  notify-enabled watch (this is why event-level filtering exists — a global run's log
  names items across all users); `category` = that category's items across their
  effective sites; `site` = all listings on that site; `item` = that item's listings
  (+ discovery/evaluation).
- Cancel: flip status to `cancelled`, stop the worker, emit a final `run_finished` event.

### Run privacy (peer privacy only)

A viewer sees only run activity about their own watches, enforced by ONE predicate on
every surface — the REST list/detail/backfill/cancel routes and the SSE snapshot,
event, and lifecycle frames alike:

- **Run rows**: a viewer sees their own runs, system runs (`user_id IS NULL`), and — as
  admin — everything. Another user's run is hidden *entirely*: absent from the list,
  and detail/events/cancel return 404 `not_found` (hidden ≡ nonexistent; never 403).
- **Events**, within a visible run: an event is visible iff it references nothing
  (lifecycle/sweep rows), OR `payload.item_id` is an item the viewer watches (two users
  watching the same catalog item both legitimately see its events), OR
  `payload.listing_id` belongs to one of the viewer's watches (listings are per-watch:
  exactly one owner). Admins see everything. The backfill filters **before** applying
  `limit`, so a filtered viewer always makes progress from their last visible seq.
- **Cancel**: owners cancel their own runs; admins cancel anything; system runs are
  admin-cancel-only (403 `forbidden` — permission is checked before the
  409 `not_active` state check).

**Honesty about scope**: this is as much separation as a shared instance can afford.
It protects users *from each other* — not from the instance operator, who can read the
database and the agent's logs directly. Known soft edges, accepted deliberately:

- The 409 `run_in_progress` response carries the active run's bare id even when that
  run is hidden from the caller (the activity panel it opens will simply be empty).
- Deleting a user flips their runs and schedules to system (`user_id` → NULL), making
  the run *metadata* — scope labels, stats — visible to everyone; per-item events stay
  filtered by the predicate.
- `Listing.discovered_by_run_id` can point at a run its owner cannot fetch (the run
  page shows "Run not found").

#### Event-emission audit (why the payload references suffice)

Every place a `run_events` row is written, and how the predicate classifies it:

| # | Emitter | Payload refs | Verdict |
|---|---------|--------------|---------|
| 1 | agent `run_started` | none; message embeds `scope_label` | Neutral-with-run-gated content: the label is run-row metadata already gated by run visibility (a user's run is hidden entirely; a system run's label was operator-chosen). |
| 2 | agent recheck failure | `{listing_id}` | Resolves to the listing's sole owner; the raw-exception message (may embed a URL) is therefore owner-only. |
| 3 | agent `item_started` | `{item_id, site_id}` | Shared-catalog rule: visible to all watchers of the item + admin. |
| 4 | agent discovery failure | `{item_id, site_id}` | Same as 3. |
| 5 | agent `run_finished` | none | Neutral. Success text is aggregate counts; failure text is infra-level by construction — per-item exceptions are caught at 2/4 and never bubble to the run-level handler. |
| 6 | backend cancel (`run_finished`) | none | Neutral ("Run cancelled"). |

### Per-item pipeline (criteria + slots)

For each item in scope:

1. **Re-check** the item's tracked listings (price, stock). A listing that has sold or
   disappeared: write a final price check with `status: 'sold' | 'ended'` (`price` null,
   `in_stock` false), set `listings.active = false`, emit `listing_ended` (warn). Its slot is
   now free. Price history is never deleted.
2. **Discover candidates** on the item's effective sites — `item_sites` rows if any, else all of
   the category's linked sites — by searching for the item name. Extract each candidate's
   `title`, price, and condition details from the listing page.
3. **Evaluate** each candidate against `items.criteria` with the LLM → `match_score` (0–100
   int) + `match_summary` (one line a human can skim, e.g. "dry battery ✓, damaged case ✓,
   missing manual"). Emit `listing_evaluated` per candidate with `tracked: true|false` in the
   payload. Items without criteria skip evaluation (scores stay null).
4. **Rank & fill slots** up to `max_listings` tracked listings:
   - `selection_mode = 'cheapest'`: rank candidates by price ascending; criteria (if present)
     is still scored for display but does not affect selection.
   - `selection_mode = 'best_match'`: rank by `match_score` descending, price ascending as the
     tiebreak. **Match floor**: discard candidates scoring below ~50 — slots may stay empty
     rather than tracking poor matches.
   - New tracked listings are inserted with `discovered_by_run_id`, `title`, match fields, and
     a first price check; emit `listing_discovered`.
5. **Re-score on criteria change**: if `items.criteria` changed since the listing was last
   evaluated, re-evaluate existing tracked listings too (update `match_score`/`match_summary`);
   in best_match mode a tracked listing that now scores below the floor may be dropped
   (`active = false`) in favor of better candidates.
6. Never reactivate a sold/ended listing; users may manually re-toggle `active` for listings
   they deactivated themselves.

## 8. ntfy notifications

- Instance-wide server URL from the env var `NTFY_SERVER_URL`; exposed read-only in
  `GET /api/instance` (`null` when unset — the frontend explains how to configure it).
- Each user sets their own `ntfy_topic` (PATCH `/api/me`).
- When a price check makes an item's `target_met` transition **false → true** and
  `watch.notify` is true, POST to `{NTFY_SERVER_URL}/{user.ntfy_topic}` with item name, price,
  site, and a link to the item page. Debounce per item so a flapping price doesn't spam.
- `POST /api/me/ntfy/test` sends a test message through the same path (422 `no_topic` if the
  user hasn't set a topic).

## 9. CORS / dev / deployment

- **Dev**: the Vite dev server proxies `/api` → `http://localhost:8000` (`frontend/vite.config.ts`),
  so no CORS config is needed. Optionally allow `http://localhost:5173` for direct API access.
- **Prod**: the frontend image (`frontend/Dockerfile`) is an nginx serving the static build and
  proxying `/api` to the `backend` service — same-origin, no CORS. The nginx config already sets
  `proxy_buffering off` + 24h read timeout for the SSE stream; replicate those if you put
  another proxy in front.
- **Compose services**: `db` (postgres), `backend` (FastAPI; env: `DATABASE_URL`, `JWT_SECRET`,
  `NTFY_SERVER_URL`, `PLAYWRIGHT_MCP_URL`, `OLLAMA_URL`, `OLLAMA_MODEL`), agent worker (or
  in-process background tasks), `ollama`, `playwright-mcp`, `frontend` (port 80).
- **k8s**: same images. Ingress routes `/` → frontend Service and `/api` → backend Service; for
  the SSE path set nginx-ingress annotations `nginx.ingress.kubernetes.io/proxy-buffering: "off"`
  and a long `proxy-read-timeout`.
- The frontend build accepts `VITE_USE_MOCKS` — `false` in production (set in the Dockerfile);
  `true` in dev until the backend exists.
