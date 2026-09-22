# Activity page — the contract PR 2a builds to

Design-pass output for PR 2a of `perpetual-hunter.md` (decision 6). The prototype is the
artifact <https://claude.ai/artifact/EcDCpYbojknrDpSGtwcugn> (five screens, picker at the
top); its screenshots are in `activity-page/`. **This file is the contract**: the types,
endpoints, mock behaviours, SSE frames, routes, components, states and copy below are what
`frontend/src/api/types.ts`, `endpoints.ts`, `mocks/handlers.ts`, `mocks/sse.ts` and the
backend implement. Where it and `perpetual-hunter.md` differ, this file wins (the two known
differences are called out inline).

Approved by the user on 2026-09-19 ("I like this layout a lot").

| Screen | File | What it shows |
|---|---|---|
| 1 | `activity-page/live.png` | `/activity` while two hunts and three checks run, one site paused |
| — | `activity-page/live-phone.png` | the same at 400 px |
| 2 | `activity-page/idle.png` | `/activity` on a quiet night, plus the fresh-install empty state |
| 3 | `activity-page/detail.png` | `/activity/:id` for a live hunt; finished and failed headers |
| 4 | `activity-page/ticker.png` | the dashboard ticker's six states and the idle masthead |
| 5 | `activity-page/item.png` | the item-page header: buttons and the new facts line, six states |

---

## 1. The shape, in one paragraph

Runs are gone. The page that replaces them keeps the dashboard's three-beat flow: **a
sentence** (the hunter's presence: sweeping or quiet, and what happens next), **the live
work** (hunts have a voice — each live hunt is a row with its latest event; checks have a
pulse — a terminal tail of `listing.checked` frames held in the browser), then **the ledger**
(what is queued, then a paginated history that defaults to hunts). Kind is said in words, not
glyphs: `Game Boy Color × eBay` is a hunt, `Game Boy Color · check` a recheck,
`Game Boy Color · market price` a grounding job. Status keeps the run-page dots and glyphs
(pending ◌-ring, running pulsing lume dot, done ✓, failed ✗, cancelled ◌). The masthead's
"Run all" button is gone; the only masthead state is a lume pill while something runs, and it
opens the activity sheet. The item page gets two buttons, **Hunt now** and **Check prices**,
and one new facts line that says what the hunter will do next for that item.

## 2. Types — `frontend/src/api/types.ts`

Removed: `RunScope`, `RunStatus`, `RunStats`, `AgentRun`, `RunCreateRequest`,
`RunEventLevel`, `RunEventType`, `RunEvent`, `RunListParams`. Added:

```ts
export type JobKind = 'hunt' | 'recheck' | 'ground'
export type JobStatus = 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
/** what a user may ask for; the same vocabulary the run request used */
export type JobScope = 'global' | 'category' | 'site' | 'item'

export interface JobStats {
  /** hunt: candidates the model looked at · recheck: 1 · ground: sources read */
  listings_checked: number
  prices_found: number
  new_listings: number
  errors: number
  tokens_in: number
  tokens_out: number
  duration_ms: number | null
  /** recheck only: how the price was read — 'llm' | 'jsonld' | 'meta' | 'microdata' | 'locator' */
  method: string | null
  /** recheck only: 'static' = a plain GET, no browser · 'browser' */
  transport: 'static' | 'browser' | null
}

export interface Job {
  id: number
  kind: JobKind
  status: JobStatus
  /** who asked; null = the hunter queued it itself (perpetual sweep, scheduler) — shown as "system" */
  user_id: number | null
  watch_id: number | null
  item_id: number | null
  item_name: string | null
  site_id: number | null
  site_name: string | null
  listing_id: number | null
  /** "Game Boy Color × eBay" (hunt) · "Game Boy Color · check" (recheck) · "Game Boy Color · market price" (ground) */
  label: string
  priority: number
  /** ISO; the queue sorts pending jobs by this */
  run_after: string
  attempts: number
  started_at: string | null
  finished_at: string | null
  /** one sentence for a human, e.g. "eBay answered a challenge page instead of the listing." */
  error: string | null
  stats: JobStats | null
  /** why it was queued: 'user' | 'created' | 'slot_freed' | 'sweep' | 'paused' — the queue's grey text */
  reason: string | null
  /** highest event seq written so far (hunts and ground only; rechecks stay 0) */
  last_seq: number
  created_at: string
}

export interface JobCreateRequest {
  kind: 'hunt' | 'recheck'
  scope: JobScope
  /** required unless scope is 'global' */
  scope_id?: number
}

export interface JobListParams {
  page?: number
  per_page?: number
  /** one kind or a comma-separated list, e.g. 'hunt,ground' */
  kind?: string
  /** one status or a comma-separated list, e.g. 'done,failed,cancelled' */
  status?: string
  item_id?: number
}

/** the presence sentence, the ticker and the queue's checks line read this one object */
export interface JobsSummary {
  hunts_running: number
  checks_running: number
  checks_pending: number
  next_check_at: string | null
  next_hunt_at: string | null
  hunts_today: number
  listings_watched: number
  /** the most recent finished hunt visible to the viewer */
  last_hunt: Job | null
  paused_sites: PausedSite[]
}

export interface PausedSite {
  site_id: number
  site_name: string
  paused_until: string
  paused_reason: string
}

export type JobEventLevel = 'info' | 'success' | 'warn' | 'error'

export type JobEventType =
  | 'job_started'
  | 'listing_check'
  /** candidate scored against the item's criteria — payload: url, title, match_score, match_summary, tracked */
  | 'listing_evaluated'
  | 'price_found'
  | 'listing_discovered'
  /** tracked listing sold/ended; slot freed — payload: listing_id, item_id */
  | 'listing_ended'
  /** the breaker tripped on this job's site — payload: site_id, paused_until, paused_reason */
  | 'site_paused'
  | 'error'
  | 'job_finished'

export interface JobEvent {
  job_id: number
  seq: number
  ts: string
  level: JobEventLevel
  event_type: JobEventType
  message: string
  payload: Record<string, unknown> | null
}

/** one recheck result, as the SSE frame carries it */
export interface ListingChecked {
  listing_id: number
  item_id: number
  item_name: string
  site_name: string
  price: string | null
  currency: string
  status: string | null
  method: string | null
  confirmed: boolean
  /** true when this check ended or sold the listing and a slot opened */
  slot_freed: boolean
  checked_at: string
}
```

Changed elsewhere in `types.ts`:

```ts
// Listing
discovered_by_job_id: number | null          // replaces discovered_by_run_id

// ItemDetail (not ItemSummary — list queries stay cheap)
hunt: {
  running: boolean
  next_at: string | null
  last_at: string | null
  last_result: 'found' | 'nothing' | 'failed' | 'cancelled' | null
  slots_open: number
}
recheck: {
  running: number
  next_at: string | null
  /** minutes between checks for this item's listings; PR 2a = the instance default,
   *  PR 2b = the watch's own value after the site floor (supersedes the
   *  `effective_interval_minutes` name in perpetual-hunter §4.9) */
  interval_minutes: number
}

// Site / SiteUpdateRequest
paused_until: string | null                  // Site
paused_reason: string | null                 // Site
paused_until?: null                          // SiteUpdateRequest — the only accepted value; clears a pause

// ApiTokenScope
export type ApiTokenScope = 'read' | 'write' | 'jobs'   // 'jobs' = queue hunts/checks, cancel jobs
```

## 3. Endpoints — `frontend/src/api/endpoints.ts`

Removed: `triggerRun`, `listRuns`, `getRun`, `getRunEvents`, `cancelRun`. Added:

```ts
export const enqueueJobs = (body: JobCreateRequest) =>
  api<{ data: Job[] }>('/api/jobs', { method: 'POST', body })
export const listJobs = (params: JobListParams = {}) =>
  api<Paginated<Job>>('/api/jobs', { params: { ...params } })
export const getJobsSummary = () => api<JobsSummary>('/api/jobs/summary')
export const getJob = (id: number) => api<Job>(`/api/jobs/${id}`)
export const getJobEvents = (id: number, afterSeq = 0, limit = 200) =>
  api<{ data: JobEvent[] }>(`/api/jobs/${id}/events`, { params: { after_seq: afterSeq, limit } })
export const cancelJob = (id: number) => api<Job>(`/api/jobs/${id}/cancel`, { method: 'POST' })
```

`updateSite` gains `paused_until: null` in its body type. Query keys (`queries.ts`):
`jobs(params)`, `job(id)`, `jobEvents(id)`, `jobsSummary`; the `runs`/`run`/`runEvents` keys go.
Invalidate `['jobs']` on every `job.*` frame; invalidate `['jobs', 'summary']` and
`['items', 'detail', item_id]` on every `listing.checked` frame.

## 4. Behaviour — `frontend/src/mocks/handlers.ts` is the oracle

Every mutation needs the CSRF header (403 `csrf`) and a session or a bearer token; a token
without the `jobs` scope gets 403 `forbidden` on mutations. All list responses are owner-scoped:
a caller sees jobs for their own watches, `ground` jobs for items they watch, and admins see
everything. A job the caller may not see is a 404, never a 403.

| Route | Cases |
|---|---|
| `POST /api/jobs` | 422 `validation_error` for a kind outside `hunt`/`recheck`, a scope outside the four, or a missing `scope_id` on a non-global scope · 404 `not_found` for a scope id that does not exist or holds none of the caller's watches · **202** `{ data: Job[] }`. `hunt`: one job per (watch, site) in scope that has open slots; a pair with a pending hunt already is bumped to now and returned; a running one is returned untouched; a full watch yields nothing in PR 2a (PR 2b turns it into a swap hunt). `recheck`: every pending recheck of an active listing in scope is bumped to now with priority 100 and returned; running ones are left alone and not returned. An empty `data` is still 202. Never 409 (the unique index dedupes). |
| `GET /api/jobs` | 401 without a session · paginated, `per_page` default 20 max 100 · `kind` and `status` accept a comma-separated list · `item_id` filters · **order**: when `status` is exactly `pending`, by `run_after` ascending (a queue); otherwise by `created_at` descending. |
| `GET /api/jobs/summary` | 401 · the viewer's numbers (§2 `JobsSummary`); `hunts_today` counts hunts finished since local midnight; `last_hunt` is the newest terminal hunt visible to the viewer; `paused_sites` lists every site with `paused_until` in the future (sites are shared, so every viewer sees them). |
| `GET /api/jobs/{id}` | 404 `not_found` when missing or not visible · 200 `Job`. |
| `GET /api/jobs/{id}/events` | 404 as above · `after_seq` (default 0) · `limit` default 200, max 500, 422 above · `{ data: JobEvent[] }` · a recheck answers `{ data: [] }`. |
| `POST /api/jobs/{id}/cancel` | 404 as above · 403 `forbidden` unless the caller owns the job's watch or is an admin (a `system` job is admin-only, as system runs were) · 422 `validation_error` for a `recheck` ("checks finish in seconds and cannot be cancelled") · 409 `job_finished` when already terminal · **200** `Job` with `status: 'cancelled'`; a running hunt also gets a final `job_finished` event at level `warn`, "Cancelled by you". |
| `PATCH /api/sites/{id}` | `paused_until: null` clears `paused_until`, `paused_reason` and the error counter · any other value → 422 `validation_error` ("only null is accepted; the hunter sets pauses"). Needs `write`. |

Fixtures: seed one site paused (Reverb, `paused_until` one hour ahead, reason "5 consecutive
read errors: challenge page") so the banner and the ticker state are reachable in mock mode;
seed ~20 finished hunts and ~200 finished rechecks across three days so History paginates and
the Checks filter has rows; seed one pending hunt per demo watch with open slots.

## 5. SSE — `/api/events` (`mocks/sse.ts` mirrors the hub)

Per viewer, gated by the same visibility as the lists. `run.*` frames are removed.

| Frame | Data | When |
|---|---|---|
| `job.snapshot` | `{ jobs: Job[] }` — every non-terminal **hunt and ground** job visible to the viewer | on every (re)connect; the client rebuilds its live set from it and refetches backfills |
| `job.started` / `job.finished` / `job.failed` | `{ job: Job }` | status changes of hunt and ground jobs (from the `jobs` trigger). **Rechecks emit no lifecycle frames.** |
| `job.event` | `JobEvent`, SSE `id: "<job_id>:<seq>"` | every `job_events` row (hunts and ground) |
| `listing.checked` | `ListingChecked` | every `price_checks` row the agent writes, whichever path read it (from the `price_checks` trigger) |

Site pauses need no frame of their own: the tripping job writes a `site_paused` event, the
client invalidates `['jobs', 'summary']` and `['sites']` on it, and a resume is a mutation
that invalidates the same keys.

The mock's demo script: `startDemoHunt(job)` plays a hunt in real time (`job_started` →
`listing_check` / `listing_evaluated` / `listing_discovered` / `price_found` → `job_finished`
with stats), writing a real listing and price check into the fixture store. A demo check loop
runs while any stream is open: every ~20 s it picks an active listing, writes a real price check
(method cycling `jsonld` → `static` → `locator` → `llm`, one in twelve `confirmed: false`) and
emits `listing.checked`. Cancelling a demo hunt stops its timers.

## 6. Routes, nav, files

- `/activity` → `ActivityPage`; `/activity/:id` → `JobPage` (hunts and ground jobs; a recheck
  id renders "Checks have no page" with a link back). `/runs` and `/runs/:id` redirect to
  `/activity` so old bookmarks land somewhere.
- Nav item **Activity** replaces **Runs** (same slot, fourth).
- `frontend/src/features/runs/*` is deleted. `frontend/src/features/activity/`:

| File | Role |
|---|---|
| `JobsProvider.tsx` | the SSE client (replaces `RunEventsProvider`): `live: Job[]` from snapshot + lifecycle frames; `events: Map<jobId, JobEvent[]>` for live hunts; `checks: ListingChecked[]` ring buffer of the last 50; `connection`; `panelOpen`; `enqueue(body)` mutation. Invalidations per §3. |
| `ActivityPage.tsx` | the page: `HunterHero` · `PausedSiteBanner` · `LiveHunts` · `ChecksTail` · `NextUp` · `HistoryTable` |
| `HunterHero.tsx` | the presence sentence (§7) from `getJobsSummary` (poll 30 s, invalidated on frames) |
| `PausedSiteBanner.tsx` | one banner per paused site; **Resume now →** shown with `write` |
| `LiveHunts.tsx` | one row per live hunt/ground job: radar 22 · label · latest event line · elapsed · Cancel (owner/admin) · Open → |
| `ChecksTail.tsx` | the terminal tail of `checks` in a `well`; caption "Checks · N running · M due in the next 30 min" |
| `NextUp.tsx` | pending hunts and ground jobs (`listJobs({ status: 'pending', kind: 'hunt,ground' })`) + one summary line for checks from the summary |
| `HistoryTable.tsx` | `Segmented` Hunts · Checks · Grounding · All (default Hunts, remembered in `localStorage`); `listJobs({ kind, status: 'done,failed,cancelled', page })`; hunt rows navigate to `/activity/:id`; check rows expand inline (price · method · transport · took · error) |
| `JobPage.tsx` | the old run page reshaped (§7 screen 3) |
| `JobStatusDot.tsx` | `RunStatusDot` renamed; statuses pending / running / done / failed / cancelled |
| `HuntButton.tsx` | replaces `RunButton`: `scope`, `scopeId`, `label`; while a hunt for that scope is live it reads "Hunting…" with the pulsing dot and opens the sheet |
| `CheckPricesButton.tsx` | `enqueueJobs({ kind: 'recheck', scope, scope_id })`; on 202 it reads "✓ Queued N" for three seconds, then returns |
| `HunterTicker.tsx` | replaces `AgentTicker` (dashboard beat two, §7 screen 4) |
| `ActivitySheet.tsx` | kept: the slide-over the masthead pill opens — header "Live · 2 hunts · 3 checks", body = `LiveHunts` + `ChecksTail`, links to the page |

`components/layout/Masthead.tsx`: the pill `● 2 hunts · 3 checks` renders only while
`live.length > 0 || summary.checks_running > 0`; no button otherwise. `SitesPage` and
`CategoryPage` swap their run buttons for `HuntButton` ("Hunt this site", "Hunt this
category"). `ItemDetailPage`: §7 screen 5. Settings → API tokens: the third scope reads
**jobs** — "queue hunts and price checks, cancel jobs".

## 7. Screens, states, copy

Time phrasing everywhere: under a minute `in 0:42`; under an hour `in 12m`; under a day
`in 2h` / `in 4h 12m`; beyond that the clock time `15:04` or `yesterday`. Elapsed: `1m 12s`.
Tokens: `12.4k`. The word is **hunt** for discovery, **check** for a recheck, **the hunter**
for the daemon; the word "run" does not appear in the UI.

### Screen 1 · `/activity`, live

- Header: `ACTIVITY` (display, 26 px) · right: the connection dot + `live` / `reconnecting…`.
- **Hero** (lume-bordered card, radar 44 sweeping with the ⌖ glyph): display line
  `SWEEPING — 2 HUNTS · 3 CHECKS` (lume); mono sub-line `47 listings watched · next check in
  0:42 · 12 hunts today`. With hunts only: `SWEEPING — 2 HUNTS`; with checks only:
  `CHECKING — 3 LIVE`.
- **Paused-site banner** (warn border/fill, ⚠): `**eBay paused until 15:04** — 5 consecutive
  read errors (challenge page). Its checks and hunts wait; nothing is retried until then.`
  `RESUME NOW →` at the right (write scope). One banner per paused site.
- **Live hunts** (caption `LIVE HUNTS`, card, one row each): radar 22 · `Game Boy Color × Mercari`
  (× dim) · latest event with its glyph · elapsed · `Cancel` (rise) · `OPEN →`. On phones the
  actions wrap under the text.
- **Checks tail** (caption `CHECKS · 3 RUNNING · 44 DUE IN THE NEXT 30 MIN`, a `well`):
  `TerminalLog` lines `14:02:11 ✓ $549.99 · Game Boy Color · eBay · jsonld`. Glyph by result:
  ✓ ok · ⚠ unconfirmed (whole line dim, suffix `unconfirmed — the model is re-reading it`) ·
  ✗ ended/sold (suffix `slot freed`). The method tag is shown only when not `llm`; an `llm`
  read that relearned a locator says `llm · relearned`. Caption under it explains the tail is
  client-held.
- **Next up** (caption, card of rows): pending hunt/ground rows `◌ Game Boy Color × eBay ·
  hunt · waiting for eBay to resume · 15:04`; reasons map from `Job.reason`: `user` → "you
  asked at 13:58", `created` → "new item", `slot_freed` → "a slot freed at 14:01", `sweep` →
  "hunting on its own", `paused` → "waiting for {site} to resume". The last row is the
  checks summary: `44 checks · spread over the next 30 min · 3 on eBay wait for 15:04 · next in 0:42`.
- **History**: `HISTORY` + `128 hunts` · `Segmented` at the right. Table: status glyph · When
  · Hunt (`item` bold, `× site` dim, `system` meta when `user_id` is null) · Result · Took ·
  Tokens (Result/Took/Tokens hidden under 640 px). Result copy: done with finds `✚ 2 new ·
  4 seen · 3 slots left` (✚ lume); done empty `nothing new · 6 seen`; done full `✚ 1 new · 3
  seen · full`; failed = `Job.error` in rise; cancelled `cancelled by you · 1 seen` dim.
  Footer `1–20 of 128 ‹ ›` on a `well`. Checks filter rows: `✓ 14:02 · Game Boy Color · eBay ·
  $549.99 · jsonld · 1.8s`.

### Screen 2 · `/activity`, quiet

- No masthead pill. Hero has a hairline border and a static radar: `QUIET — NEXT CHECK IN
  12 MIN` (ink) · `47 listings watched · 12 hunts today · last hunt 2h ago: nothing new`. With
  a site paused the sub-line starts `⚠ eBay paused until 15:04 ·`.
- No Live hunts section. Checks tail keeps whatever the session has seen.
- Fresh install (no jobs at all): hero `QUIET — NOTHING YET` · `Add an item and the hunter
  starts looking for it.`; History shows the empty card `NOTHING HAS HAPPENED YET` / `Add an
  item and the hunter starts looking. Prices are re-checked every 30 minutes on their own.`

### Screen 3 · `/activity/:id`

- Live hunt: radar 44 · eyebrow `● RUNNING · Sep 18, 14:01 · you|system` · display title in lume
  `HUNTING — GAME BOY COLOR × MERCARI` · `1m 12s · live · 2 of 5 slots filled before this
  hunt` · `Cancel` (owner/admin). Four stat tiles: **Candidates seen** (`listings_checked`),
  **Saved** (`new_listings`, lume when > 0), **Rejected** (`listings_checked − new_listings −
  errors`), **Tokens**. Then the `TerminalLog` of events in a `well`, following the tail
  while live.
- Finished: no radar; eyebrow `✓ DONE`; title in ink `HUNTED — GAME BOY COLOR × EBAY`;
  sub-line `48s · ✚ 2 new · 4 seen · 3 slots left · 12.4k tokens`.
- Failed: eyebrow `✗ FAILED`; title is the label; the `Job.error` sentence in a rise alert
  under it.
- Ground job: same page, title `MARKET PRICE — GAME BOY COLOR`, tiles Sources read · Prices ·
  Median · Tokens.

### Screen 4 · the dashboard ticker (`HunterTicker`)

Same 44 px strip as today: radar 24 · state (mono, letter-spaced) · `│` · message · CTA.

| State | Radar | State text | Message | CTA |
|---|---|---|---|---|
| hunting (+ checks) | sweeping | `SWEEPING · 2 HUNTS · 3 CHECKS` (lume) | latest hunt event with glyph, e.g. `✚ new listing · Game Boy Color · Mercari · $189.00` · elapsed | `WATCH ↗` (opens the sheet) |
| checks only | sweeping | `CHECKING · 3 LIVE` (lume) | latest `listing.checked` line | `ACTIVITY →` |
| idle | static | `HUNTER IDLE` (dim) | `next check in 12 min · last hunt 2h ago, nothing new` | `ACTIVITY →` |
| idle, site paused | static | `HUNTER IDLE` | `⚠ eBay paused until 15:04 · next check in 12 min` | `ACTIVITY →` |
| nothing yet | static | `HUNTER IDLE` | `Add an item and the hunter starts looking for it.` | `ACTIVITY →` |
| hunting off (2b) | static | `HUNTING OFF` | `paused by the operator · prices are still checked every 30 min` | `ACTIVITY →` |

The dashboard's "once only" rule stands: counts of finds belong to the pulse line, so the
ticker never repeats them. Masthead right side: search · pill (live only) · avatar.

### Screen 5 · the item-page header

Buttons in the title row: **HUNT NOW** · **CHECK PRICES** · **EDIT** (all `default` variant,
`sm`). The existing facts line keeps its shape. One new mono line (11 px, ink-3) under it, two
halves split by `│`:

`checks every 30m · next in 18m │ hunting 2 of 5 slots open · next hunt in 1h · last hunt 2h ago, nothing new`

| State | Button | Facts line |
|---|---|---|
| A slots open | `HUNT NOW` | as above; "next hunt in 1h (backoff)" is PR 2b — in 2a the hunting half reads `2 of 5 slots open · last hunt 2h ago, nothing new` |
| B full | `HUNT FOR BETTER` (PR 2b; in 2a the button stays `HUNT NOW` and is disabled with title "All 5 slots are filled") | `hunting 5 of 5 slots filled · paused until a slot frees · last hunt 40m ago, nothing better` |
| C hunting now | `● Hunting…` (opens the hunt) | `● hunting Mercari now · 1m 12s · 2 of 5 slots open` in lume |
| D checks just queued | `✓ Queued 3` for 3 s | `checks every 30m · 3 running now │ …` |
| E site paused / hunting off by operator (2b) | disabled, title "Hunting is paused by the operator" | `⚠ eBay paused until 15:04 · Mercari next in 9m │ hunting paused by the operator` |
| F hunt off for this item (2b) | `HUNT NOW` | `hunting off — only when you press Hunt now · 3 of 3 slots open` |

`last_result` copy: found → "found N", nothing → "nothing new", failed → "failed", cancelled →
"cancelled"; on a full watch "nothing new" reads "nothing better".

## 8. Rules the build must keep

- Every semantic colour ships with its glyph (✓ ✗ ⚠ ✚ ◌ ●). Lume marks live and primary, never
  a result. Green ✓ is a successful read, not a price drop.
- Numerals, timestamps, eyebrows, button labels and every log line are IBM Plex Mono with
  `tnum`. Titles and the presence sentence are Big Shoulders Display, letter-spaced, uppercase.
- The checks tail and the queue's checks line are the only places rechecks appear on the
  live page. History's Checks filter exists for debugging a site; it is never the default.
- Nothing on the live page repeats a per-item fact the item page shows; the hero aggregates.
- Phone width: the hunt row's actions wrap under its text; the history table hides Result,
  Took and Tokens; nothing scrolls sideways.
