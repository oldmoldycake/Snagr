# Perpetual hunter — learned price locators, a jobs daemon, and the end of runs

Design doc and phased plan, **v2** (2026-09-15, revised after review).
Investigation only: no code has been changed. Facts below were read from
`main` at `602df94` and, where it says "measured", probed against the live
Playwright MCP container (`mcr.microsoft.com/playwright/mcp` 0.0.79) and two
throwaway copies of the same image. Line numbers are from that commit;
re-grep before relying on them.

v1 of this doc kept `agent_runs`, `run_schedules`, a schedules UI, token
budgets and a notification overhaul. The review on 2026-09-15 cut all of
that: **runs are retired, schedules are dropped, and the build is five PRs**, four of them designed here and one reserved.
§1 records every decision so nobody re-litigates them. The 2026-09-14 brief
(`~/.claude/plans/snagr-schedules-and-hunt.md`) is fully superseded,
including its schedules PR.

---

## 0. The short version

Snagr stops being a batch job you trigger and becomes a hunter that is
always on. The agent is a small daemon (`main.py --serve`) that claims work
from a `jobs` table in Postgres. There are three kinds of work:

- **Hunt** — find listings for one (watch, site) pair with the LLM and the
  browser. **A watch spans every site in its `site_ids`**; the (watch, site)
  pair is only the unit of browser work, one search page per job, and all
  of a watch's hunts share its one slot budget (`max_listings` in total,
  never per site — PR #31). A hunt exists only while the watch has open
  slots. A hunt that finds nothing backs off; a freed slot or a user's "hunt
  now" wakes it. A full watch costs nothing, and a "hunt now" on a full
  watch is a **swap hunt**: it looks for something better than the weakest
  tracked listing and replaces it (§4.6).
- **Recheck** — re-read one known listing's price and availability with no
  model in the loop. The first time the LLM confirms a listing's price, code
  captures *where on that page* the price lives and stores that locator on
  the listing. Every later recheck goes straight to it; the LLM is only
  called when the locator, the page's structured data and the availability
  signals all fail, and it relearns the locator when it does. When the
  learn-time probe shows the same price is in the raw HTML, the recheck is a
  plain HTTP GET with no browser at all. Each watch sets how often its
  listings are re-read.
- **Ground** — refresh an item's market price stats (today's `--ground-only`).

Whichever path observed a price, one function `record_price_check()` writes
the observation, decides the target edge, takes the cooldown and queues the
notification in a single transaction, so ntfy / Discord / webhooks fire from
deterministic reads exactly as they do from LLM reads today.

The **run** concept goes away: no Runs page, no run button, no
`agent_runs`. Jobs are what the UI shows (an Activity page, a masthead
ticker with "N hunts · M checks live", hunt/check facts on the item page)
and what the API and MCP expose.

---

## 1. Decisions locked on 2026-09-15

| # | Question | Decision | Consequence |
|---|---|---|---|
| 1 | What is a run in a perpetual world? | **Retire runs entirely.** | `agent_runs`, `run_events`, `run_schedules` dropped; Runs page, `RunButton`, `ActivitySheet`, `AgentTicker`, `RunDetailPage`, `RunEventsProvider` replaced by an Activity page over jobs; SSE `run.*` frames become `job.*` + `listing.checked`; MCP `trigger_run` / `cancel_run` / run lists become job tools. |
| 2 | Keep schedules as a "scheduled mode"? | **Drop them.** | No `/api/schedules`, no UI. Perpetual hunting + backoff + a per-watch `hunt` toggle replace them. Cron users get `main.py --once`. |
| 3 | Scope of v1 | **Five PRs** (§5). | PR 1 locators + deterministic rechecks · PR 2a jobs daemon + Activity page · PR 2b perpetual hunting · PR 3 cheap scans (reserved; designed after 2b ships) · PR 4 parallel hunts + pacing. Token budgets and the notification enrichment (edge split, per-listing cooldown, digest) are deferred (§6). |
| 4 | "An option for probing for the users" | **A per-watch recheck interval**, and notifications fire from deterministic reads. | `watches.recheck_interval_minutes` (null = instance default), floored by the site's pacing. No new notification machinery. |
| 5 | Locator priority | **Structured data first, visible element as fallback.** | `jsonld` → `meta` → `microdata` → `css`. All per listing, all learned by code at LLM-confirm time, all verified by replay before saving. |
| 6 | Activity page | **Short design pass before PR 2a.** | A Night Hunt prototype artifact + the `types.ts` / `handlers.ts` / `mocks/sse.ts` contract, then the backend builds to it. |
| 7 | The three run tables | **Drop them** in PR 2a's migration (downgrade recreates them empty). | Only `run_events` references `agent_runs`; nothing else depends on them. |
| 8 | The `runs` API-token scope | **Rename to `jobs`** with a migration rewriting stored scopes. | `ApiTokenScope = 'read' \| 'write' \| 'jobs'`; presets, mock, MCP auth and README updated. |
| 9 | What does the hunter do when a watch's slots are full? | **Stop hunting when full.** | A full watch has no perpetual hunt jobs; zero cost until a slot frees. The list is the first N found, kept fresh by rechecks. |
| 10 | Should swaps (replace the weakest tracked listing with a better find) apply in both selection modes? | **Both modes.** | Read together with 9: swapping happens only when a hunt runs on a full watch anyway, i.e. a user's **"hunt now"**. That hunt looks for something better than the weakest tracked listing and swaps it in; cheapest = strictly lower price (code-verified), best match = better fit judged by the model, price as tiebreak. §4.6. |
| 11 | "Cheap scrape" still means a Chromium page load per recheck. | **Static-fetch probe at learn time (PR 1).** | When the locator is learned, one plain GET of the listing checks whether the same `jsonld`/`meta` locator yields the same price in the raw HTML. If so, that listing's rechecks are a GET parsed with the standard library, no browser. §4.2 step 6, §4.3. |
| 12 | A bot wall under a daemon becomes a token fire (every listing → LLM fallback → fails → repeats every interval). | **Per-site circuit breaker (PR 2a).** | N consecutive read errors pause the site's jobs and its LLM fallback for 1 h, doubling to 24 h, stored on the site row and shown in the UI. §4.4. |
| 13 | With budgets deferred, what is the panic button? | **`HUNT_ENABLED` kill switch + the effective check interval shown in the UI (PR 2b).** | §4.6. |
| 14 | Apply the locator idea to discovery too? | **Reserve "cheap scans" as PR 3, before parallel hunts.** | A hunt captures its search URL and result-card shape; a scan fetches, diffs links against known listings, and the model judges only new candidates. Sketch only in §5; designed properly after PR 2b. Parallel hunts become PR 4. |
| 15 | The extractor JS is untested in CI (only its captured outputs are). | **Not in v1.** | Browser-marked local tests were offered and declined; recorded as a known gap in §6. |
| 16 | Does a global "Hunt all" survive in the masthead? | **Dropped** (2026-09-16). | Per-item, per-site and per-category hunt buttons only; the masthead holds the ticker. One fewer state for the design pass. |
| 17 | The §8 defaults: jobs API shape, bare `main.py`, job visibility, unconfirmed anomalous reads, bands, the URL guard, no recheck events, ground in the hunt pool, `JOB_*` renames, breaker thresholds, swaps on manual hunts only, the swap guards, static-probe details, 409 on the kill switch. | **All confirmed as written** (2026-09-16). | Nothing in §8 blocks a PR. Items 10, 11 and 17 there stay open and none is needed before PR 3. |

Two clarifications from the same review, so the doc says them the user's way:

- **"Save the HTML tag ID for the price."** That is what §4.2 does: at the
  moment the model confirms a price on a page, the exact element (or the
  exact structured-data field) holding that price is identified, stored on
  that listing, and replayed with no guessing on every later check. Most
  marketplace price elements carry no `id` attribute (eBay: a span inside a
  div with only classes; Mercari: hashed React classes), so the stored value
  is the shortest path that uniquely reaches the element, not a literal id.
  When the same page also carries the price in a JSON-LD block, the stored
  locator points there, because that copy survives restyles; it is still
  per listing and still verified exact.
- **The model never types the locator.** Code reads the page the model is
  on, finds the element whose text equals the confirmed price, and replays
  the derived locator once before trusting it. Asking the model for a
  selector is where hallucinated selectors and page-steered choices would
  come from.

---

## 2. Current state (what the code does today)

### 2.1 Runs, the ticker, heartbeats, the reaper

- Three entry modes, matched by `sys.argv` membership (`agent/main.py:56-76`):
  bare = one global sweep, `--consume` = claim one queued run or fire one due
  schedule, `--ground-only` = refresh stale market prices. All run under
  `_supervised` (`main.py:32-53`), which turns SIGTERM/SIGINT into
  cancellation so the run in flight is failed cleanly.
- Under compose the agent is `ticker.sh` (`agent/ticker.sh:34-42`): a
  `--consume` tick every 60 s, `--ground-only` every 15th tick, serial. There
  is no nightly sweep unless someone seeds `run_schedules` by SQL.
- Claiming (`agent/database.py:1091-1128`): `SELECT … FOR UPDATE SKIP LOCKED`
  on the oldest `queued` row. One active run instance-wide:
  `backend/app/services/runs.py:131-160` answers 409 `run_in_progress`.
- Execution (`agent/agent.py:294-412`): grounding pre-pass, then pass 1
  re-checks every active listing through a full agentic LLM unit
  (`recheck_listing`, `:175-213`), then pass 2 scans one (watch, site) pair
  per unit (`scan_pair`, `:216-277`), skipping full watches (`:374-380`).
  Units are bounded by `AGENT_MAX_STEPS` and `AGENT_UNIT_TIMEOUT_SECONDS`.
- Heartbeat (`agent.py:415-421`) + reaper (`database.py:1371-1403`, migration
  013). Cancellation is cooperative (`get_run_status` between units).
- Run stats are a module-level dict (`agent/tools.py:41`), reset per run —
  only valid because one process drives one run at a time.

### 2.2 Grounding

`agent/pricing.py:805-830` `ground_stale()` picks items whose market stats
are missing or older than `MARKET_PRICE_TTL_HOURS`, fetches price-guide
pages and SearXNG snippets, runs one `llm.ainvoke` extraction per source,
upserts `market_prices`. It uses **synchronous `requests`** inside
coroutines (`pricing.py:130, 349`) and sleeps 5 s / 900 s (`:68-69`) —
harmless in a one-shot, fatal inside a daemon next to browser workers.

### 2.3 Price and listing writes

All writes happen in the LLM-exposed tools (`agent/tools.py`), bound to a
`UnitContext` per unit (`:55-66`, read via `ToolRuntime`, `:73-78`):
`save_listing` (`:105-234`), `save_price_check` (`:237-328`, validates
*shape* only — status, price > 0, currency format — inserts the row,
commits, then calls `notify_target_met` in a separate transaction),
`disable_listing` (`:331-370`), `log_listing_check` (`:373-420`),
`check_images` (`:423-550`). **Nothing validates plausibility**: the number
the model types is the number stored, and if it is at or below target it
can notify.

### 2.4 Notifications

The agent detects, the backend delivers, and the code matches: `agent/notify.py:20-76`
does the edge test, the `NOTIFY_COOLDOWN_HOURS` check, `enqueue_notification`
(`database.py:627-653`) and `mark_watch_notified` (`:596-624`) in three
transactions, never raising. Migration 010's trigger wakes the backend
dispatcher (`backend/app/services/notifications.py:322-366`), which fans out
per channel and retries. `listing.new` comes from `save_listing` via
`enqueue_new_listing` (`database.py:656-722`), gated on `watches.notify`.

### 2.5 Live progress (SSE)

Migration 007's triggers announce `run_events` inserts and `agent_runs`
status changes on `snagr_run_events`; the hub (`backend/app/services/events.py`)
fans out `run.snapshot` / `run.event` / `run.started` / `run.finished` /
`run.failed` per viewer. `RunEventsProvider.tsx` holds one `activeRun`.
The agent writes four of the ten contract event types.

### 2.6 Browser plumbing

`build_pass_agents` (`agent/agent.py:127-157`) opens one MCP session per run
because the server runs a persistent `--user-data-dir /profile` (no
`--isolated`, no `--blocked-origins`), and a second session is refused.

### 2.7 Doc ↔ code mismatches (fixed along the way)

| Where | Doc says | Code does | Fixed in |
|---|---|---|---|
| `agent/prompt.py:288-291` vs `agent.py:151` | Scan prompt: after sold/ended call `disable_listing` | Scan toolset has no `disable_listing` | PR 1 |
| `types.ts:216`, `schemas/items.py:71`, `services/items.py:153` | `Listing.discovered_by_run_id` | Hard-coded `None`, no column | PR 2a: becomes `discovered_by_job_id` and real |
| `types.ts:479-492` | Ten run event types | Four written | PR 2a: hunts emit the per-listing types as job events |
| `README.md:9` | "no versioned releases yet (0.1.0)" | `version.txt` = 0.2.1 | PR 2a docs sweep |
| `agent/tools.py:39-41` | "one process drives one run at a time" | True today | PR 4: tally moves onto `UnitContext` |
| `backend/app/schemas/items.py:94` vs `models.py:177` | `max_listings` default 5 / DB default 3 | Harmless, noted in code | — |
| `backend/app/services/items.py:355-361` | validations "not enforced yet"; `site_ids` not applied on update | As stated | Unrelated; you will be in `create_item` for the hunt-on-create hook |
| `agent/notify.py:4-5` | "the agent is the only writer of price_checks" | True | Wording → "the agent process" |

### 2.8 Security review of the current code

Marketplace pages are untrusted; the model reads them and then types tool
arguments.

| # | Path | What page content can influence | Severity | Fixed in |
|---|---|---|---|---|
| S1 | `save_price_check(price=…)` | The stored price and therefore a `target.hit`. A page (or a mis-read) that says "$4.49" for a $449 item notifies a buying bot. | **High** | PR 1 (`validate_observation` + the confirm rule, §4.3) |
| S2 | `save_listing(url=…)`, later navigated to on every recheck | Any http(s) URL is accepted, including `http://snagr-postgres:5432/`, `http://vision:8100/rescore`, `http://backend:8000/api/…`. The MCP has no origin restrictions. | **High** (SSRF via the browser) | PR 1: URL host must match the site's registrable domain and must not resolve to loopback/private/link-local. PR 2a: `--blocked-origins` on the MCP (defense in depth; "does not affect redirects"). |
| S3 | `check_images(image_urls=…)` → `vision/fetcher.py:31-47` | The sidecar fetches any URL, follows redirects, no private-address guard. | Medium | Separate small vision PR (§6). |
| S4 | `log_listing_check(reason, notes)` → rendered into every future scan prompt (`prompt.py:190-202`) | A stored prompt-injection channel. | Medium | PR 1: length caps, newline strip, delimited data block. |
| S5 | `save_listing(title, match_summary)` → `listing.new` payload → ntfy/Discord/webhook + UI | Model-typed text reaches notification bodies. | Low | PR 1: caps; README documents them as untrusted display text. |
| S6 | Scan and recheck prompts | No "page content is untrusted DATA" paragraph (the extraction prompt has one, `:569-571`). | Medium | PR 1 (overlaps the fraud-signals plan's PR 4 — do it once). |
| S7 | Playwright MCP | `browser_run_code_unsafe` is exposed to the LLM; no `--blocked-origins`. | Medium | PR 2a: filter the tool list handed to `create_agent`; operator flag. |
| S8 | `agent/pricing.py:342-356` | Fetches search-result URLs with plain `requests`, no guard. | Low | PR 2a, when `pricing.py` moves to httpx. |
| S9 | Webhook destinations | User-supplied, no IP blocklist — documented as deliberate. | Accepted | — |

---

## 3. Measured facts

### 3.1 Rendered HTML through Playwright MCP — zero tokens when code calls it

- `browser_evaluate` (`function`, optional `element`/`ref`) returns
  `### Result\n<JSON>\n### Ran Playwright code\n…`. On an 828 KB page a full
  `outerHTML` came back **untruncated, 860,174 chars in 0.64 s**; a compact
  extractor (JSON-LD blocks + OG/microdata metas + leaf elements containing
  digits) returned **2.2 KB in 0.52 s**. Navigate took 1.07 s.
- Also present: `browser_network_requests` (the document's status code —
  the 404/410 signal), `browser_find`, `browser_snapshot` with `depth`,
  `browser_wait_for`.
- The LangChain adapter returns `StructuredTool`s that code can
  `await tool.ainvoke({...})` with no model involved; the text never enters a
  prompt. **The LLM must never be handed raw HTML** (that page would be
  ~200k tokens). The extractor JS is a fixed constant the model cannot
  author and whose output it does not see.
- Parsing the `### Result` wrapper is version-coupled: pin the MCP image tag,
  unit-test the parser against a captured sample.
- Plain `httpx` GET of listing pages was considered and rejected for v1: the
  locator is learned from the *rendered* DOM the model confirmed. A per-site
  "static" flag is a later optimisation once §7 shows which sites qualify.

### 3.2 Browser isolation — `--isolated` works; the persistent profile does not

| Server flags | Session A | Session B (concurrent) | RSS |
|---|---|---|---|
| `--user-data-dir` (today) | ok 0.51 s | **refused**: "Browser is already in use … use --isolated" | 88 MiB |
| `--isolated` | ok 0.80 s | **ok 0.23 s** | 112 MiB |

In HTTP mode the server keeps one Chromium process and, with `--isolated`,
calls `browser.newContext()` per MCP session (`coreBundle.js:73071-73112`).
N workers = N `client.session("playwright")` contexts. Budget ~60–120 MiB
per open context on a heavy marketplace page; 4 hunt + 4 check contexts
≈ 0.6–1 GiB. An isolated context starts with no cookies: `--storage-state
<file>` seeds consent-banner state; sites that need a login are a follow-up.
`PLAYWRIGHT_MCP_ISOLATED=true` is the env equivalent for operators who cannot
edit the command.

### 3.3 Other blockers

- Module-level side effects (`agent/agent.py:82-87`, `pricing.py:44-47`:
  `assert PLAYWRIGHT_MCP_URL`, `llm = init_chat_model(...)`) → factories
  `build_llm()` / `open_browser_session()` so the check pool can run with no
  model (PR 2a).
- `tools.run_stats` global → per-job tally on `UnitContext` (PR 4).
- Slot race under parallel hunts → `SELECT … FOR UPDATE` on the watch inside
  `save_listing` (PR 4; the `SLOTS FULL:` refusal itself lands with swap
  hunts in PR 2b).
- Sync `requests` in `pricing.py` → `httpx.AsyncClient` (PR 2a prerequisite).
- **No new dependencies** in any PR. Selector derivation and JSON-LD parsing
  are stdlib + JS the browser already runs.

---

## 4. Target design

### 4.1 Process topology

```
backend (uvicorn, unchanged role)        agent daemon: python main.py --serve
  routers → services/jobs.py enqueue       ┌ scheduler task: perpetual-hunt sweep, stale
  SSE hub: job.* + listing.checked         │   grounding, job reaper, retention prune
  notification dispatcher (unchanged)      ├ check pool  (RECHECK_CONCURRENCY, browser, no LLM)
                                           ├ hunt pool   (HUNT_CONCURRENCY, LLM + browser; also ground)
        Postgres: jobs (+ trigger) ────────┤ LISTEN snagr_jobs → wake pools
                                           └ per-site gates (PR 4)
Playwright MCP (--isolated): one context per worker session
```

- The backend never drives a browser or a model. It inserts `jobs` rows and
  serves what the agent wrote. "The agent detects, the backend delivers" and
  the D1 schema split stay intact.
- One daemon process. `main.py --serve` replaces `ticker.sh` under compose.
  `main.py --once` enqueues due work, drains the queue until empty and exits
  (the cron mode; it folds in `--ground-only`). No flag prints usage and
  exits 2 — `argparse`, so a typo no longer runs a full sweep silently.
  `--consume` and `--ground-only` are removed.
- Idle cost: one LISTEN connection, a 30 s safety-net tick, no open browser
  contexts (sessions are opened per job and closed after).

### 4.2 Per-listing price locators

**Capture moment.** The only time we have a confirmed price *and* the page
it came from is when the LLM calls `save_price_check` with `status="ok"`.

1. `UnitContext` gains a `browser` handle (orchestrator-built, wrapping the
   session's `browser_evaluate` / `browser_navigate` tools; never a model
   argument). Inside `save_price_check`, after validation and before the DB
   write, the tool runs `PAGE_EXTRACTOR_JS` on the current page and checks
   `location.href` is the listing's URL (same host + path). If the model has
   navigated away, learning is skipped and the orchestrator does a
   **post-unit learn**: navigate to the URL, extract, match; if the price is
   no longer there, learn next time.
2. `PAGE_EXTRACTOR_JS` (a fixed constant in `agent/locators.py`) returns one
   JSON object: `{url, title, jsonld: [raw script bodies], meta: {…},
   microdata: [{itemprop, content|text, selector}], candidates: [{text,
   selector}], markers: {auction, buy_now, sold, ended}}`. Candidates are
   leaf elements whose text contains a currency-formatted number; the JS
   derives one selector per candidate by priority `[itemprop=price]` →
   `[data-testid="…"]` → `#id` (skipped when it looks generated) →
   `[aria-label="…"]` → a ≤4-level `tag.stableClass:nth-of-type(n)` path,
   where a class is "stable" unless it matches a hashed pattern
   (`css-1x9kz3q`, `sc-abc123`, `jss42`, `_xyz9k`).
3. **Code selects (decision 5).** Python parses every candidate with the
   same `parse_price()` the validator uses and keeps those equal to the
   confirmed price. Priority: a JSON-LD `Offer`/`AggregateOffer` whose
   `price` matches (`locator_kind='jsonld'`, locator = JSON path, e.g.
   `offers[0].price`) → `product:price:amount` (`meta`) → `[itemprop=price]`
   (`microdata`) → the highest-priority `css` candidate. Ties: first in DOM
   order. If nothing matches, no locator is learned and the next LLM read
   tries again.
4. **Verify before saving**: run `RUN_LOCATOR_JS` (the second constant,
   templated with the locator as a `json.dumps` string literal, so quotes,
   backslashes and U+2028 are escaped and the selector is data, never code)
   and require `parse_price(result) == confirmed price`. Only then write
   `listings.price_locator`, `locator_kind`, `locator_verified_at`,
   `locator_failures = 0`.
5. **Site consensus** (no table): the most common verified `(kind, locator)`
   among the site's listings, computed with one `GROUP BY` at read time. It
   is what a listing with no locator of its own, or a broken one, tries
   before the LLM. A marketplace has one page template; when it changes, one
   relearn should fix the whole site.
6. **Static probe** (decision 11): with a `jsonld` or `meta` locator
   verified, the learn step also performs one plain `httpx` GET of the
   listing URL (browser-like UA, `Accept-Language`, no redirects followed,
   through the site gate and the S2 URL guard) and runs the same locator
   over the raw HTML with `agent/static.py` (`html.parser` for
   `<script type="application/ld+json">` bodies and `<meta>` tags; no new
   dependency). An exact price match sets `listings.static_ok = true`;
   anything else leaves it false. `css` and `microdata` kinds never probe:
   Python has no DOM. This is the moment the LLM run pays for every
   browserless recheck after it. Structured data exists for crawlers, so
   on most marketplaces the probe succeeds.

Locators are data read by fixed code. Nothing built from one is `eval`-ed in
Python; in the browser it only lands inside `document.querySelector(<json
literal>)` or a JSON path walk, and a hostile selector can at worst select
the wrong element, which step 4's exact-match check refuses.

### 4.3 The recheck path, validation, and the confirm rule

```
static rung (only when listing.static_ok): httpx GET, no redirects
  ├ 404/410 or a redirect ......................................... → browser path below (confirm there)
  ├ same locator over the raw HTML, parse_price, validate ........... → record(method=<kind>, transport=static)
  └ anything else (no block, no match, challenge page, anomalous) ... → browser path below
open session → navigate(listing.url)
  ├ transport: document 404/410, final URL off the listing host/path .. → availability path
  ├ extractor JSON (one browser_evaluate)
  │   markers.sold / ended / JSON-LD availability ................... → availability path
  │   markers.auction && !markers.buy_now .......................... → auction → disable (as today)
  ├ read ladder: listing locator → site consensus → jsonld → meta → microdata
  │   (each: parse_price, then validate_observation)
  │   first non-anomalous success ................................. → record(method=<kind>)
  │   anomalous ................................................... → LLM read now (same job)
  └ nothing validated ............................................. → LLM fallback (existing
                                                                       agentic recheck; relearns)
```

- **Static rung** (decision 11): the GET goes through the site gate and the
  S2 guard like a navigation. Its result is trusted only for a price that
  the same locator finds and `validate_observation` accepts; a 404/410, a
  redirect, a challenge page or a mismatch all fall through to the browser,
  which confirms availability itself. If the browser then succeeds with the
  same locator, `static_ok` is cleared (the rendered page and the raw page
  differ for this listing) and the next LLM learn re-probes. Success records
  `jobs.stats.transport = 'static'`, so §7 can show how many rechecks never
  opened a browser. `STATIC_FETCH=false` disables the rung.
- **`validate_observation(price, currency, listing, market, markers)`**
  (`agent/validation.py`, shared by both paths): decimal with two places;
  `0 < price < 10^8`; currency equals `EXPECTED_CURRENCY` (a different
  currency is recorded, `notifiable=False`, today's "recorded, never mixed"
  stance); no auction markers; **plausibility bands** against the listing's
  last priced check (ratio in `[0.2, 5]`) and, when market stats are `ok`,
  against the watch's condition-tier median or the lowest tier (ratio
  ≥ 0.1). Outside a band = **anomalous**, not rejected. Bands are
  `PRICE_BAND_LOW` / `PRICE_BAND_HIGH` / `PRICE_MARKET_FLOOR`; 0 disables.
- **The confirm rule** (S1, simplified from v1 — no `confirm` job kind):
  - An anomalous *locator* read is not recorded. The job performs an LLM read
    of the same page immediately, and that read becomes the observation.
  - An anomalous *LLM* read is recorded with `confirmed = false`, does not
    notify, and does not enter the aggregates (`services/aggregates.py`
    filters on `confirmed`). Under the daemon the listing's next recheck is
    bumped to `now() + 5 min`; under PR 1's run model it waits for the next
    run. A following read within 1 % of it is recorded `confirmed = true`
    and notifies; a disagreeing read is recorded as its own confirmed
    observation and the unconfirmed row stays excluded forever. No
    retroactive flips.
  - Ordinary reads are `confirmed = true` on insert and notify at once.
    Cost of the rule: a genuine 80 %-off deal waits one extra read. Cost of
    not having it: a buying bot acts on "$4.49".
- **Method recorded on every check** (`price_checks.method`: `locator` for
  a replayed css locator, `jsonld`, `meta`, `microdata`, `llm`). Existing
  rows backfill `llm`, which is true.
- **Failure accounting**: a locator that returns nothing or fails validation
  bumps `listings.locator_failures`; past `LOCATOR_MAX_FAILURES` (3) it is
  cleared so the next LLM read relearns. The per-site relearn semaphore (one
  LLM relearn, then every waiting listing of that site retries the ladder
  with the fresh consensus first) lands with parallelism in PR 4.
- **Availability path**: `ended` (gone / redirected) or `sold` (markers or
  JSON-LD `SoldOut`/`Discontinued`), recorded with the method that saw it,
  then `disable_listing` exactly as the LLM would. Ambiguous pages go to the
  LLM, which the recheck prompt already tells it to resolve.

### 4.4 The work queue

Migration 015 (numbering: §4.10):

```
jobs
  id            bigserial PK
  kind          text NOT NULL        -- hunt | recheck | ground
  user_id       int  FK users NULL   -- who asked; NULL = system (perpetual sweep, scheduler)
  watch_id      int  FK watches NULL -- hunt, recheck (denormalised from the listing for cheap ownership filters)
  site_id       int  FK sites NULL   -- hunt
  listing_id    int  FK listings NULL ON DELETE CASCADE -- recheck
  item_id       int  FK items NULL   -- ground
  status        text NOT NULL        -- pending | running | done | failed | cancelled
  priority      int  NOT NULL DEFAULT 0          -- user-triggered = 100
  run_after     timestamptz NOT NULL DEFAULT now()
  attempts      int  NOT NULL DEFAULT 0
  locked_by     text NULL, heartbeat_at timestamptz NULL
  started_at    timestamptz NULL, finished_at timestamptz NULL
  error         text NULL
  payload       jsonb NULL   -- chain state: {"backoff_minutes": 30}, {"reason": "user"}
  stats         jsonb NULL   -- {"method": "jsonld", "duration_ms": 1830, "tokens_in": 0, "tokens_out": 0,
                             --  "listings_checked": 1, "prices_found": 1, "new_listings": 0, "errors": 0}
  last_seq      int  NOT NULL DEFAULT 0
  created_at    timestamptz NOT NULL DEFAULT now()

job_events   -- the run_events shape, FK jobs ON DELETE CASCADE; written by hunts only
  id, job_id, seq, ts, level, event_type, message, payload

UNIQUE INDEX uq_jobs_open ON jobs (kind, coalesce(listing_id,0), coalesce(watch_id,0),
                                    coalesce(site_id,0), coalesce(item_id,0))
  WHERE status IN ('pending','running')
INDEX ix_jobs_due   ON jobs (run_after, priority DESC) WHERE status = 'pending'
INDEX ix_jobs_watch ON jobs (watch_id, created_at DESC)
TRIGGER jobs_notify        AFTER INSERT OR UPDATE OF status ON jobs   → pg_notify('snagr_jobs', {id, kind, status})
TRIGGER job_events_notify  AFTER INSERT ON job_events                 → pg_notify('snagr_job_events', {job_id, seq})
TRIGGER price_checks_notify AFTER INSERT ON price_checks              → pg_notify('snagr_job_events', {check: id})
```

- **Claim** (one statement, `SKIP LOCKED`, the house idiom):
  `UPDATE jobs SET status='running', locked_by=:worker, locked_at=now(),
  heartbeat_at=now(), started_at=now(), attempts=attempts+1 WHERE id =
  (SELECT id FROM jobs WHERE status='pending' AND kind = ANY(:kinds) AND
  run_after <= now() ORDER BY priority DESC, run_after, id FOR UPDATE SKIP
  LOCKED LIMIT 1) RETURNING *`.
- **Wake-up**: the daemon LISTENs on `snagr_jobs`; every wake and a 30 s idle
  tick run the same "claim until empty" loop, like the dispatcher's drain.
  Nothing depends on a NOTIFY arriving.
- **One pending recheck per listing, always.** Completing a recheck inserts
  the next one (`run_after = now() + effective interval`) in the same
  transaction; the partial unique index makes a duplicate impossible, so
  "check now" is `UPDATE … SET run_after = now(), priority = 100 WHERE
  kind='recheck' AND listing_id = :l AND status = 'pending'` (a running one
  is left alone; the request still answers 202).
- **Reaper** (scheduler task, every 60 s): `running` rows with `heartbeat_at`
  older than `JOB_STALE_AFTER_SECONDS` (300) go back to `pending`, or to
  `failed` past `JOB_MAX_ATTEMPTS` (3). A failed recheck still inserts its
  successor so a listing is never orphaned.
- **Retention** (scheduler task, hourly): terminal `recheck`/`ground` jobs
  older than `JOB_RETENTION_DAYS` (7) and terminal `hunt` jobs older than
  `HUNT_RETENTION_DAYS` (90) are deleted; `job_events` cascade. At 50
  listings on a 30-minute interval that is ~2,400 recheck rows a day, ~17k
  retained. Listing history lives in `price_checks`, not in jobs.
- **Site circuit breaker** (decision 12): the daemon counts consecutive read
  errors per site across rechecks and hunts (`sites.consecutive_errors`; any
  success resets it). At `SITE_BREAKER_ERRORS` (5) it sets
  `sites.paused_until = now() + SITE_BREAKER_MINUTES` (60, doubling per trip
  up to `SITE_BREAKER_CAP_MINUTES`, 1440) and `paused_reason` ("5
  consecutive read errors: challenge page"). While paused, the claim query
  skips the site's jobs (their `run_after` is pushed to `paused_until`), no
  LLM fallback runs for it, and the Activity page and the site row show the
  pause. A bot wall or a restyle then costs at most five reads before going
  quiet, instead of every listing every interval forever. The trip writes a
  `warn` job event on the job that tripped it. Manual clear: `PATCH
  /api/sites/{id}` with `paused_until: null` (write scope).
- **Who enqueues what**:

| Event | Job(s) | Written by |
|---|---|---|
| watch created (`services/items.py:create_item`) | `hunt` per (watch, site) with `user_id` = the caller; `ground` for the item if never grounded | backend, same transaction as the watch |
| listing saved (`save_listing`) | `recheck` at `now() + interval` | agent, same transaction |
| recheck done | next `recheck` | agent, same transaction |
| listing deactivated (user `PATCH /api/listings/{id}` or agent `disable_listing`) | its pending `recheck` cancelled; `hunt` for every site of the watch when slots open and `watches.hunt` (PR 2b) | backend / agent |
| user "hunt now" / "check prices" (`POST /api/jobs`, §4.5) | `hunt` per (watch, site) with open slots in scope, priority 100, backoff reset; or every pending `recheck` in scope bumped to now | backend `services/jobs.py::expand_scope` |
| perpetual sweep (PR 2b) | `hunt` for every (watch, site) with open slots, `hunt = true`, and no open hunt job | agent scheduler task, hourly + on wake |
| stale market price | `ground` | agent scheduler task, hourly (`select_grounding_work`) |
| anomalous LLM read | that listing's pending `recheck` bumped to `now() + 5 min`, priority 90 | agent, inside `record_price_check` |

- **Ground jobs run in the hunt pool**: they carry LLM calls and no browser,
  and the hunt pool is the LLM-bearing one. Household scale; revisit if
  grounding ever starves behind hunts.

### 4.5 What replaces runs

**API** (all under the `jobs` token scope for mutations, `read` for GETs;
CSRF as everywhere; owner-scoped — a caller sees jobs for their own watches
and for items they watch; admins see everything):

| Route | Replaces | Behaviour |
|---|---|---|
| `POST /api/jobs` `{kind: 'hunt' \| 'recheck', scope: RunScope, scope_id?}` | `POST /api/runs` | 202 `{ data: Job[] }` — the jobs created or bumped. `hunt` = hunts for every (watch, site) with open slots in scope, backoff reset; `recheck` = bump every pending recheck in scope. Never 409: the unique index dedupes. 404 `not_found` for an unknown scope id, 422 for a bad kind/scope. |
| `GET /api/jobs?status=&kind=&item_id=&page=&per_page=` | `GET /api/runs` | Paginated, newest first. |
| `GET /api/jobs/{id}` | `GET /api/runs/{id}` | One job. |
| `GET /api/jobs/{id}/events?after_seq=&limit=` | `GET /api/runs/{id}/events` | Backfill; hunts only (rechecks have no events). |
| `POST /api/jobs/{id}/cancel` | `POST /api/runs/{id}/cancel` | Pending → `cancelled`; running hunts poll and stop between LLM steps; a running recheck finishes (it is seconds). 409 `job_finished` for a terminal job. |

**SSE** (`/api/events`, per viewer): `job.snapshot` on connect (every
non-terminal job visible to the viewer), `job.started` / `job.finished` /
`job.failed` (the `Job` row, from the status trigger), `job.event` (hunts),
and `listing.checked` `{listing_id, item_id, price, status, checked_at,
method, confirmed}` from the `price_checks` trigger, gated by listing
ownership. The item page invalidates its queries on it.

**Contract types**: `Job {id, kind, status, user_id, watch_id, site_id,
listing_id, item_id, item_name, site_name, scope_label, priority, run_after,
attempts, started_at, finished_at, error, stats, last_seq, created_at}`,
`JobEvent` (the `RunEvent` shape keyed by `job_id`), `JobKind`, `JobStatus`,
`JobCreateRequest`. `RunScope` is kept as the scope vocabulary (renamed
`JobScope`). `ItemDetail` gains `hunt: {enabled, next_at, last_at,
backoff_minutes}` and `recheck: {interval_minutes, next_at}` (computed from
jobs; not on `ItemSummary`, to keep list queries cheap).
`Listing.discovered_by_run_id` → `discovered_by_job_id`, real.

**MCP** (`app/mcp/tools/jobs.py`): `enqueue_jobs`, `list_jobs`, `get_job`,
`cancel_job`, same service calls, same schemas; `auth=JOBS`.

**Token scope**: `ApiTokenScope = 'read' | 'write' | 'jobs'`; migration 015
rewrites `'runs'` → `'jobs'` in stored scopes; presets in
`ApiSettingsPage.tsx:170`; `require_scope("jobs")`.

**UI** (design pass first — decision 6). The pass must produce: the Activity
page (live jobs with a hunt's event feed and the checks as a compact
counter/list, the queue with `run_after`, paginated history filtered by kind
and item); the masthead ticker states (idle with "next check in 12m", and
"N hunts · M checks live"); the item-page facts line ("checked 12m ago ·
next in 18m · hunting, backoff 1h" with **Hunt now** and **Check prices**
buttons); "Hunt this site" / "Hunt this category" where the run buttons are
today (`SitesPage.tsx:203`, `CategoryPage.tsx:143`); no global "Hunt all"
(decision 16: the masthead holds the ticker only); the effective check cadence on the
item page ("every ~12m, eBay limit") and the "hunting paused by the
operator" state; a paused-site banner ("eBay paused until 15:04 after 5
failed reads"); and the `types.ts` / `handlers.ts` / `mocks/sse.ts`
changes. The Night Hunt design system has no "N live" state
yet — that is the design question.

**Removed**: `frontend/src/features/runs/*` (six files), `backend/app/routers/runs.py`,
`services/runs.py`, `schemas/runs.py`, `mcp/tools/runs.py`, `agent/ticker.sh`,
the `agent_runs` / `run_events` / `run_schedules` models and the agent's
mirror of them, the `--consume` mode, `RUN_*` env vars (renamed `JOB_*`).

### 4.6 Perpetual hunting (PR 2b)

- **Trigger = slots.** A hunt job for (watch, site) exists whenever the watch
  has open slots, `watches.hunt` is true, and no open hunt job for that pair
  exists (the unique index). Sources: watch created, slot freed, backoff
  timer, user "hunt now", the hourly sweep (safety net for missed wakes).
- **Backoff on empty**: a hunt that saves nothing reschedules itself with
  `payload.backoff_minutes = min(2 × previous, HUNT_BACKOFF_CAP_MINUTES)`,
  starting at `HUNT_BACKOFF_MIN_MINUTES` (15 → 30 → 60 → … → 360). Any save,
  any freed slot, or a user "hunt now" resets it. A watch with no open slots
  has no hunt jobs at all.
- **A full watch has no perpetual hunt jobs** (decision 9). The tracked list
  is the first N found; rechecks keep it fresh; a slot frees when a listing
  sells, ends, or the user untracks it, and the freed slot wakes the hunt.
- **Swap hunts** (decision 10): a user's "hunt now" on a full watch is the
  one hunt that runs with no open slots, and its job is to improve the list.
  `expand_scope` includes full watches for a user-triggered `hunt` with
  `payload.swap = true`; the perpetual sweep never does.
  - **Prompt.** The `TRACKING SLOTS: 0 open` block is replaced by a
    `TRACKED LISTINGS` block: the watch's active listings with site, last
    confirmed price and match score, the weakest first under the watch's
    selection mode (cheapest: highest price; best match: lowest score, price
    as tiebreak). The rule: save a candidate only if it beats the weakest;
    call `disable_listing(<weakest id>, reason="replaced")` first, then
    `save_listing`; at most one swap per site per hunt. Leftover good
    candidates are still not rejections.
  - **Code verifies.** `save_listing` on a full watch refuses with
    `SLOTS FULL:` unless a `replaced` disable happened in this unit (tracked
    on `UnitContext`), and in cheapest mode unless the new listing's price
    is strictly lower than the replaced listing's last confirmed price. The
    model proposes, code checks; a swap can never over-fill or trade sideways
    on price. Cross-site swaps work because a scan unit may already write any
    listing of its watch (`_listing_mismatch`).
  - **Replaced is not rejected.** `disable_listing` today only logs its
    reason; migration 016 adds `listings.inactive_reason` (`sold` | `ended` |
    `auction` | `replaced` | `untracked`, the last written by
    `PATCH /api/listings/{id}`). A `replaced` listing stays in the
    known-URL skip set for 24 h (churn guard against two similar listings
    flip-flopping), then becomes findable again; `save_listing` on a URL
    whose row is `replaced` **reactivates that row** (history intact)
    instead of skipping it, unlike PR #57's sold/ended rows, which are
    terminal. The Activity feed shows a swap as `listing_ended`
    (`reason: replaced`) followed by `listing_discovered`.
- **`watches.hunt bool NOT NULL DEFAULT true`** (migration 016): the
  per-watch toggle. Off = the watch is only hunted by an explicit "hunt now";
  rechecks continue regardless (they are cheap). Exposed as
  `ItemSummary.hunt`, optional on create/update, the `allow_reproductions`
  pattern.
- **`watches.recheck_interval_minutes int NULL`** (migration 016; decision 4):
  null = `RECHECK_INTERVAL_MINUTES` (30). Floor `RECHECK_INTERVAL_FLOOR_MINUTES`
  (5; 422 below it). Effective interval per listing = `max(watch interval,
  site floor)` where the site floor (PR 4) = `active_listings_on_site ×
  min_gap × 1.2`. Exposed on `ItemSummary` and the create/update requests;
  `InstanceInfo.recheck_interval_default` for the form's placeholder.
  **The UI shows the effective cadence, not the requested one** (decision
  13): `ItemDetail.recheck.effective_interval_minutes` is derived by the
  backend from what the agent actually scheduled (the gap between the last
  check and the next pending recheck's `run_after`), so no interval formula
  is duplicated across the two components and the site stretch from PR 4
  shows up on its own.
- **Kill switch** (decision 13): `HUNT_ENABLED=false` stops the perpetual
  sweep and makes every hunt enqueue refuse — the sweep skips, and `POST
  /api/jobs {kind: 'hunt'}` answers 409 `hunting_disabled` so nothing sits
  queued as a silent fake. Rechecks continue. `InstanceInfo.hunt_enabled`
  lets the UI say "hunting paused by the operator". Set in both
  `backend/.env` and the agent's env, the `VISION_SIDECAR_URL` precedent.
  This is the panic button that token budgets would otherwise be.
- **Budget**: none in v1 (deferred, §6). The existing per-unit caps
  (`AGENT_MAX_STEPS`, `AGENT_UNIT_TIMEOUT_SECONDS`) and backoff bound the
  cost; `jobs.stats.tokens_*` (from `usage_metadata`) makes the spend
  visible so a budget can be sized later.

### 4.7 Parallel hunts, isolation, pacing (PR 4)

- `HUNT_CONCURRENCY` (default 1, raise after measuring) bounds the hunt pool;
  each hunt job opens its own MCP session (its own isolated context), builds
  its scan agent from that session's tools, runs `scan_pair`, closes the
  session. `RECHECK_CONCURRENCY` (3) does the same for checks, so a hung page
  never blocks a neighbour. `--isolated` is required from PR 2a because
  "check now" cannot wait behind a hunt.
- **Pacing** in one `SiteGate` per site: `min_gap_seconds` with ±30 % jitter
  and `max_concurrency` (defaults `SITE_MIN_GAP_SECONDS=8`,
  `SITE_MAX_CONCURRENCY=1`, per-site overrides in nullable `sites` columns,
  migration 018). Every navigation goes through the gate: the check worker
  calls it directly; the hunt agent's `browser_navigate` is wrapped in a thin
  tool that awaits the gate before delegating and refuses hosts outside the
  site's registrable domain or in private ranges (S2/S7 belt and braces).
- **Rapid has a ceiling set by the sites.** 50 listings at 30 min = 2,400
  page loads a day; at 5 min = 14,400; at 1 min = 72,000. With an 8 s gap one
  site sustains ~10,800 loads a day before the gap alone stretches the
  interval. Thirty minutes is the default; the per-watch interval is for
  tightening the few items that matter.
- **Local models**: `HUNT_CONCURRENCY` stays 1 unless the operator says the
  server batches (Ollama queues; vLLM/SGLang batch).

### 4.8 Notifications

- **One writer**: `agent/observations.py::record_price_check(session, unit,
  *, price, currency, in_stock, status, method, confirmed)`. Both the
  `save_price_check` tool and the check worker call it. In **one
  transaction**: `SELECT … FROM watches WHERE id = :w FOR UPDATE` (serialises
  every writer of this watch), verify the listing belongs to the unit, insert
  the `price_checks` row, compute the watch's best-before excluding the new
  row, decide the edge (today's rule: best-before above target or unknown,
  new price at/below), take the cooldown with the conditional `UPDATE
  watches SET last_notified_at = now() WHERE id = :w AND (last_notified_at
  IS NULL OR last_notified_at < now() - :cooldown) RETURNING id`, insert the
  outbox row when a row came back, write the `price_found` / `listing_ended`
  job event when the unit is a hunt, commit. Notification-only steps stay
  behind the validated, non-raising decision function so a notification bug
  can never lose an observation. The tool keeps returning `Error:` strings;
  the worker raises on DB failure like the claim helpers do.
- **Payload**: today's `target.hit` fields plus `method` and `confirmed`
  (additive; README "Webhooks" says unknown fields are ignored). A consumer
  that only buys on `confirmed: true` is protected by the confirm rule.
- Edge split per channel, per-listing cooldown, richer payload
  (market ratio, authenticity, slots) and digests are deferred (§6).

### 4.9 Contract changes per PR (frontend first, per house rules)

| PR | `types.ts` / `endpoints.ts` / `handlers.ts` / `mocks/sse.ts` |
|---|---|
| 1 | `PriceCheck.method` and `PriceCheck.confirmed` (additive; the checks log can show a glyph and ghost unconfirmed points). |
| 2a | The §4.5 job types and endpoints; run types and endpoints removed; `ApiTokenScope` `runs` → `jobs`; SSE `job.*` + `listing.checked`; `ItemDetail.hunt` / `.recheck`; `Listing.discovered_by_job_id`; `Site.paused_until` / `Site.paused_reason` (read) and `paused_until: null` on `SiteUpdateRequest` (the manual clear). Design pass output. |
| 2b | `ItemSummary.hunt`, `ItemSummary.recheck_interval_minutes`, both optional on create/update (422 rules); `ItemDetail.recheck.effective_interval_minutes`; `InstanceInfo.recheck_interval_default`, `InstanceInfo.hunt_enabled`; `POST /api/jobs {hunt}` 409 `hunting_disabled`. |
| 3 | Designed with the PR (reserved). Expected: `Site.listing_url_pattern` (read), a `scan` job kind in `JobKind`, `ItemDetail.hunt.search_url_learned`. |
| 4 | `Site.min_gap_seconds`, `Site.max_concurrency` (`number \| null`) on `Site` / create / update; UI for several live hunts (the design pass should sketch it). |

### 4.10 Schema (Alembic, backend-owned; agent mirrors the subset it reads)

Head is `013`. The fraud-signals plan reserved 014–016; **first to merge
wins, the other renumbers on rebase.**

| Rev | PR | Change |
|---|---|---|
| 014 | 1 | `listings.price_locator text`, `locator_kind text`, `locator_verified_at timestamptz`, `locator_failures int NOT NULL DEFAULT 0`, `static_ok bool NOT NULL DEFAULT false`; `price_checks.method text` (backfill `'llm'`), `price_checks.confirmed bool NOT NULL DEFAULT true`. |
| 015 | 2a | `jobs`, `job_events`, the three triggers (DDL also copied into `backend/tests/conftest.py::_NOTIFY_DDL` like 007/010); `listings.discovered_by_job_id bigint FK jobs NULL ON DELETE SET NULL`; `sites.consecutive_errors int NOT NULL DEFAULT 0`, `sites.paused_until timestamptz NULL`, `sites.paused_reason text NULL`; **drop** `run_events`, `agent_runs`, `run_schedules` (downgrade recreates them empty); `api_tokens` scopes `'runs'` → `'jobs'`. |
| 016 | 2b, step 1 | Data only: queue a first recheck for every tracked listing saved before 015 created the queue. |
| 017 | 2b, step 2 | `watches.recheck_interval_minutes int NULL`, `listings.inactive_reason text NULL` (backfill: existing inactive rows → `'ended'`; CHECK `ck_listings_inactive_reason` on the five values). |
| 018 | 2b, step 3 | `watches.hunt bool NOT NULL DEFAULT true`; `jobs.payload jsonb NULL` (PR 2a shipped `jobs.reason` rather than the §4.4 payload column, so the chain state `{"backoff_minutes": 30}` gets its column here). |
| — | 3 | Numbered when it lands. Reserved for cheap scans (expected: `watch_sites.search_url` + `search_url_verified_at`, `sites.listing_url_pattern`); designed with the PR. |
| — | 4 | Numbered when it lands. `sites.min_gap_seconds int NULL`, `sites.max_concurrency int NULL`. |

Agent mirror (`agent/database.py`): `Listings` gains the locator columns,
`static_ok` and `discovered_by_job_id`; `PriceChecks` gains `method` /
`confirmed`; `Watches` gains `hunt`, `recheck_interval_minutes`; `Sites`
the breaker columns and later the pacing columns; new `Jobs`, `JobEvents`;
`AgentRuns` / `RunEvents` / `RunSchedules` removed. `vision/db.py` mirrors
none of these.

### 4.11 Configuration (read only in `agent/config.py` / `backend/app/config.py`)

Agent, new: `CHEAP_RECHECK=true` (kill switch: `false` = every recheck is the
LLM, as today), `LOCATOR_MAX_FAILURES=3`, `PRICE_BAND_LOW=0.2`,
`PRICE_BAND_HIGH=5`, `PRICE_MARKET_FLOOR=0.1`, `RECHECK_INTERVAL_MINUTES=30`,
`RECHECK_INTERVAL_FLOOR_MINUTES=5`, `RECHECK_CONCURRENCY=3`,
`HUNT_CONCURRENCY=1`, `HUNT_BACKOFF_MIN_MINUTES=15`,
`HUNT_BACKOFF_CAP_MINUTES=360`, `JOB_STALE_AFTER_SECONDS=300`,
`JOB_MAX_ATTEMPTS=3`, `JOB_HEARTBEAT_INTERVAL_SECONDS=30`,
`JOB_RETENTION_DAYS=7`, `HUNT_RETENTION_DAYS=90`, `SITE_MIN_GAP_SECONDS=8`,
`SITE_MAX_CONCURRENCY=1`, `STATIC_FETCH=true`, `SITE_BREAKER_ERRORS=5`,
`SITE_BREAKER_MINUTES=60`, `SITE_BREAKER_CAP_MINUTES=1440`,
`HUNT_ENABLED=true`. Renamed: `RUN_STALE_AFTER_SECONDS` →
`JOB_STALE_AFTER_SECONDS`, `RUN_HEARTBEAT_INTERVAL_SECONDS` →
`JOB_HEARTBEAT_INTERVAL_SECONDS` (no aliases; called out in the PR and
`.env.example`). Unchanged: `AGENT_*`, `NOTIFY_COOLDOWN_HOURS`,
`EXPECTED_CURRENCY`, `MARKET_PRICE_TTL_HOURS`, the `AI_*` provider vars.

Backend, new: `RECHECK_INTERVAL_MINUTES` (for `InstanceInfo` and the 422
floor) and `HUNT_ENABLED` (for `InstanceInfo` and the 409). Both are set
in `backend/.env` *and* the agent's env with the same value, the
`VISION_SIDECAR_URL` precedent; the two components do not share a file.

Operator (README + `.env.example` + compose comments): the Playwright MCP
must run with `--isolated` (optionally `--storage-state`) and should run with
`--blocked-origins` for private ranges and the compose service names.

---

## 5. The five PRs — each ships and works on its own

House rules for every PR: contract first (`types.ts` → `handlers.ts` →
backend), match the neighbours, every behaviour change with a test (error
paths included), ruff + pytest + `alembic check` + `npm run build` + `npm run
lint` + `frontend:verify` for UI, STRUCTURE.md / README / CLAUDE.md /
`.env.example` updated in the same PR. Conventional-commit PR title,
worktree, commit list shown before committing, each PR against `main`.

### PR 1 — `feat(agent): learned price locators and deterministic rechecks`

**Goal.** Pass 1 of every run reads most listings without the LLM; every
check records how it was read; the false-price path is closed before any
notification. Today's run model is untouched, so this lands and pays for
itself even if nothing else does.

- **Migration 014.** Agent mirror.
- **Agent**
  - `agent/locators.py` (new): `PAGE_EXTRACTOR_JS`, `RUN_LOCATOR_JS`,
    `parse_result(text)`, `select_locator(extract, confirmed_price)`,
    `read_with(kind, locator, extract)`, `site_consensus(session, site_id)`.
    Pure functions over JSON except the last.
  - `agent/static.py` (new): `fetch(url, site)` (httpx, no redirects,
    browser-like UA, gate + guard), `extract(html) -> {jsonld, meta}` on
    `html.parser`, `probe(listing, locator, price) -> bool` for the learn
    step (§4.2 step 6), and the static rung of the ladder (§4.3). No new
    dependency.
  - `agent/validation.py` (new): `parse_price`, `validate_observation`,
    `url_allowed(url, site_base_url)` (S2), `clip_text` (S4/S5).
  - `agent/recheck.py` (new): `recheck_deterministic(browser, row) ->
    Outcome` per §4.3, serial (the per-site semaphore is PR 4). Never raises
    for a page problem; DB failures propagate.
  - `agent/observations.py` (new): `record_price_check` per §4.8. The
    `save_price_check` tool becomes validation + learn + a call to it;
    `notify.py`'s body moves in. The tool docstring gains one sentence about
    plausibility ("re-read the page and report exactly what it shows").
  - `agent/tools.py`: `UnitContext.browser`; learn step in
    `save_price_check`; URL guard in `save_listing`, `log_listing_check`,
    `check_images`; text caps; `disable_listing` added to the scan toolset.
  - `agent/agent.py`: `build_pass_agents` also yields the raw tool map; pass
    1 = `if CHEAP_RECHECK and await recheck_deterministic(...)`: done, else
    the existing `_bounded(recheck_listing(...))` followed by a post-unit
    learn. Log which method won.
  - `agent/prompt.py`: the untrusted-content paragraph in the scan and
    recheck prompts (S6).
  - `agent/config.py` + `.env.example`: `CHEAP_RECHECK`, `LOCATOR_MAX_FAILURES`,
    the three band vars.
- **Backend**: `PriceCheck.method` / `.confirmed` in `schemas/items.py`;
  `services/items.py::list_price_checks` maps them; `services/aggregates.py`
  filters `confirmed` everywhere a price is read.
- **Frontend**: `types.ts`, `handlers.ts` (seeded rows `method: 'llm',
  confirmed: true`), optional glyph / ghosted point in the checks log.
- **Tests**
  - `agent/tests/test_locators.py`: extractor fixtures (captured JSON,
    redacted) — JSON-LD in stock / sold out / eBay auction where `Offer.price`
    is the current bid (**must yield no locator and `markers.auction`**),
    BIN + bid, OG-only, microdata-only, hashed-class page, several elements
    with the same price (structured wins, then first stable), no match
    (→ `None`); `parse_result` against a captured MCP sample; `RUN_LOCATOR_JS`
    templating with a hostile selector (`"]) ; alert(1) //`) stays a literal.
  - `agent/tests/test_static.py`: captured raw-HTML fixtures (JSON-LD
    present / meta only / neither / a challenge page / a redirect response);
    `probe` true only on an exact match; the rung falls through on every
    non-match; `static_ok` cleared when the browser later succeeds with the
    same locator; `STATIC_FETCH=false` skips the rung; the guard refuses a
    private-address URL before any request is made.
  - `agent/tests/test_validation.py`: bands, currency, auction markers,
    `url_allowed` (private IPs, `localhost`, container names, subdomain vs
    look-alike host, off-site host).
  - `agent/tests/test_recheck.py`: a fake browser scripting extractor JSON
    per navigation; ladder order; failure bumps; availability → disable;
    ambiguous → `False`; anomalous locator → LLM read; anomalous LLM →
    unconfirmed row, no outbox row.
  - `agent/tests/test_observations.py` (real Postgres): edge + cooldown as
    before, now atomic; a forced outbox constraint failure still commits the
    check ("observation beats notification"); unconfirmed rows never notify.
  - `agent/tests/test_run_consumer.py`: cheap success skips the agent;
    `False` → agent; `CHEAP_RECHECK=false` → agent always; post-unit learn.
  - `agent/tests/test_tool_validation.py`: URL guard on all three tools; caps.
  - Backend: `test_items_api.py` (`method`, `confirmed`; aggregates ignore
    unconfirmed), `test_schema_defaults.py`.
- **Success**: after two full runs on the dev stack, ≥ 70 % of pass-1 units
  record `method != 'llm'` (§7 query 1); on sites whose pages carry
  server-rendered JSON-LD, ≥ 50 % of pass-1 units never open a browser
  (§7 query 8); zero notifications from unconfirmed rows (§7 query 5 = 0).

### PR 2a — `feat!: jobs daemon and Activity page replace runs`

**Goal.** No more ticker, no more runs. A new watch is hunting within
seconds; "check prices" re-reads an item's listings within seconds; rechecks
recur on their own. The Activity page shows what the hunter is doing.

- **Step 0 — design pass** (decision 6): prototype artifact in the Night
  Hunt system covering the §4.5 UI list; output = the contract diff.
- **Migration 015** + conftest DDL. Mirrors (run models removed).
- **Agent**
  - `agent/jobs.py` (new): `claim`, `heartbeat`, `complete`, `fail_or_retry`,
    `enqueue_recheck`, `bump_rechecks`, `enqueue_hunts`, `enqueue_ground`,
    `reap`, `prune`, `expand_scope`.
  - `agent/worker.py` (new): `serve()` — LISTEN loop + 30 s tick; the two
    pools as `asyncio.Semaphore`-bounded task groups, each job opening its
    own MCP session; the scheduler task (stale grounding, reaper, retention);
    clean shutdown through `_supervised` (in-flight jobs → `pending` with
    `run_after = now()`, so nothing is lost on `docker compose stop`).
  - `agent/breaker.py` (new): `record_outcome(site_id, ok)` (the counter,
    the trip, the doubling), `is_paused(site_id)`, and the claim-query
    clause that skips paused sites (§4.4). Called from the check and hunt
    pools around every job.
  - `agent/main.py`: `argparse`; `--serve`, `--once`; `ticker.sh` deleted;
    compose `command: python main.py --serve`; Dockerfile `CMD` = `--once`.
  - `agent/agent.py`: `build_llm()` / `open_browser_session()` factories;
    `execute_run` becomes `run_hunt_job` (one (watch, site) unit under a
    job); tool list filtered (S7); `browser_navigate` wrapped with the URL
    guard.
  - `agent/pricing.py`: `requests` → `httpx.AsyncClient`, `url_allowed` (S8);
    a `ground` job handler.
  - `save_listing` enqueues the first recheck and stamps
    `discovered_by_job_id`; `disable_listing` cancels the recheck; hunt units
    write the contract's per-listing event types as `job_events`.
- **Backend**
  - `services/jobs.py` (new; callers: items, listings, jobs router, MCP):
    `enqueue_hunts_for_watch`, `bump_rechecks`, `expand_scope`, `list_jobs`,
    `cancel_job`, ownership filter.
  - `routers/jobs.py` (new) per §4.5; `routers/runs.py`, `services/runs.py`,
    `schemas/runs.py`, `mcp/tools/runs.py` deleted; `mcp/tools/jobs.py`.
  - `services/items.py`: `create_item` enqueues hunts + ground in its
    transaction; `update_listing(active=False)` cancels the recheck;
    `listing_out` reads `discovered_by_job_id`; item detail computes `hunt`
    / `recheck` facts from jobs.
  - `services/events.py`: `job.*` frames + `listing.checked`.
  - `catalog.py` serializer: `paused_until` / `paused_reason` on `Site`;
    `routers/sites.py`: `paused_until: null` on update clears a pause (any
    other value → 422).
  - `core/auth` scope constant `JOBS`; STRUCTURE.md endpoint table.
- **Frontend**: `features/runs/*` deleted; `features/activity/*` per the
  design pass; `JobEventsProvider` (several live jobs, counts); item-page
  facts + buttons; site/category hunt buttons; token scope presets and
  labels; `handlers.ts` + `mocks/sse.ts` rewritten for jobs.
  `frontend:verify`.
- **Operator**: MCP `--isolated` (+ `--storage-state`, `--blocked-origins`);
  README Development / Requirements / Webhooks; compose comments; CLAUDE.md
  Commands + Agent internals rewritten; `.env.example` renames.
- **Tests**
  - `agent/tests/test_jobs_db.py` (real Postgres, `test_run_queue_db.py`
    idioms — that file is replaced): claim order, `SKIP LOCKED` under two
    concurrent claimers, the unique index (second pending recheck refused,
    bump instead), reaper transitions, successor insert on completion and on
    failure, `expand_scope` per scope kind with the slot filter, retention.
  - `agent/tests/test_worker.py`: fakes for claim/execute; NOTIFY and tick
    both drain; a job exception marks `failed`/retry and never kills the
    loop; SIGTERM returns in-flight jobs to `pending`.
  - `agent/tests/test_jobs_trigger.py`: raw asyncpg LISTEN sees the insert
    and the status change.
  - `agent/tests/test_breaker_db.py` (real Postgres): five errors trip,
    one success resets, doubling and the cap, paused jobs are not claimed
    and their `run_after` moves, the LLM fallback is skipped while paused,
    the `warn` job event is written once per trip.
  - Backend: `test_jobs_api.py` (202 shapes, 404, 422, cancel 409, CSRF 403,
    scope 403, ownership), `test_items_api.py` (create → jobs rows;
    deactivate → recheck cancelled; detail facts), `test_events_sse.py`
    (`job.*` and `listing.checked` reach the owner and not another user),
    `test_mcp.py` (job tools), `test_api_tokens.py` (scope rename +
    migration rewrite), `test_migrations.py` (015 up/down).
- **Success**: a site answering challenge pages trips the breaker within
  one cycle and makes zero LLM calls while paused (§7 query 9); median time
  from `POST /api/items` to the hunt's first `job_events` row < 60 s; from `POST /api/jobs {recheck}` to a new
  `price_checks` row < 30 s for an item with three listings; `ticker.sh`
  gone; median price age (§7 query 3) ≤ `RECHECK_INTERVAL_MINUTES` + a few
  minutes.

### PR 2b — `feat: perpetual hunting with backoff and per-watch check interval`

**Goal.** Hunting continues on its own only while it can find something;
the user decides how often each item is re-read.

- **Migration 016.** Mirrors.
- **Agent**: backoff chain on hunt completion; reset on save / freed slot /
  user hunt; the hourly perpetual sweep in the scheduler task (skipped
  entirely under `HUNT_ENABLED=false`, logged once); `disable_listing`
  wakes hunts and writes `inactive_reason`; effective interval in
  `enqueue_recheck`; `usage_metadata` summed into `jobs.stats.tokens_*`.
- **Agent, swap hunts** (§4.6; separable into a PR 2c if 2b grows):
  `payload.swap` honoured by `run_hunt_job`; the `TRACKED LISTINGS` prompt
  block; `UnitContext.replaced_listing_id` set by `disable_listing(reason=
  "replaced")`; the `SLOTS FULL:` backstop and the cheapest-mode price check
  in `save_listing`; reactivation of a `replaced` row on re-save;
  `get_known_listing_urls` excludes `replaced` rows older than 24 h.
- **Backend**: `hunt` and `recheck_interval_minutes` on items schemas /
  services / MCP (the `allow_reproductions` pattern; 422 below the floor);
  `update_listing(active=False)` writes `inactive_reason = 'untracked'` and
  wakes hunts; `expand_scope` sets `swap` for user hunts on full watches
  and answers 409 `hunting_disabled` under `HUNT_ENABLED=false`;
  `ItemDetail.recheck.effective_interval_minutes` derived from the last
  check and the next pending recheck; `InstanceInfo.recheck_interval_default`
  and `.hunt_enabled`.
- **Frontend**: `TrackingFields` — a "Hunting" switch and a "Check every"
  field (Segmented 15 m / 30 m / 1 h / 6 h / custom, placeholder = default);
  item facts line shows backoff state and the effective cadence ("every
  ~12m"); the **Hunt now** button on a full watch reads "Hunt for better"
  and is disabled with "hunting paused by the operator" when
  `InstanceInfo.hunt_enabled` is false.
- **Tests**: `test_jobs_db.py` backoff chain and reset, the sweep's slot /
  `hunt` filters (a full watch gets no job), user hunt on a full watch gets
  `swap`, effective interval; `test_slot_budget.py` swap cases — save on a
  full watch without a replace → `SLOTS FULL:`; replace then save at a
  higher price in cheapest mode → refused; replace then save lower →
  accepted, exactly N active; best-match swap accepted on any price; a
  second save in the same unit → refused; re-save of a `replaced` URL
  reactivates the row; `test_items_api.py` / `test_mcp.py` for the two
  fields and their 422s; `test_listings_api.py` `inactive_reason`;
  `HUNT_ENABLED=false` → the sweep enqueues nothing, `POST /api/jobs
  {hunt}` is 409 `hunting_disabled`, rechecks still recur, `InstanceInfo`
  reports it; `effective_interval_minutes` equals the watch interval when
  nothing stretches it and follows the next job's `run_after` when
  something does; `frontend:verify`.
- **Success**: a watch with all slots filled generates zero hunt jobs for
  24 h; freeing a slot enqueues within a tick; a watch on a 15-minute
  interval shows checks 15 minutes apart (§7 query 3 per watch); "hunt now"
  on a full cheapest watch either lowers the highest tracked price or
  changes nothing, never both a swap and a higher price (§7 query 6 = 0).

### PR 3 — `feat(agent): cheap scans` (reserved — designed after PR 2b ships)

**Goal.** Apply the locator idea to discovery. After PR 2b the only LLM
cost left is hunts on watches that never fill, which browse a site
agentically every six hours forever. A hunt's own visit can also capture
the search-results URL it settled on and the shape of a result card; a
cheap scan then fetches that page, diffs its listing links against the
watch's known URLs, and calls the model only to judge genuinely new
candidates. Nothing new = zero tokens. Reserved here so the numbering and
the order are settled; it gets its own design section before it is built.

- **Sketch, not a design.**
  - *Capture.* The wrapped `browser_navigate` (PR 2a) already logs every
    URL a hunt visits; the last search-results URL on the site's domain
    before the first listing page is the candidate, stored per (watch, site)
    (`watch_sites.search_url`, `search_url_verified_at`). The listing-URL
    pattern per site is derived from the site's saved listings
    (`sites.listing_url_pattern`, e.g. `^https://www\.ebay\.com/itm/\d+`),
    code-derived and code-verified like locators. Verification = the
    captured search URL, fetched, contains the URLs the hunt just saved.
  - *Scan.* A `scan` job kind between recheck and hunt: fetch the search
    URL (static first, browser fallback), extract links matching the
    pattern, drop known URLs (active, inactive, rejected), and if new
    candidates remain run a **judge-only** LLM unit that visits just those
    pages with the existing scan prompt's criteria and tools. Backoff and
    slots as for hunts; a scan that yields nothing new is what replaces the
    six-hourly agentic hunt. A watch with no verified search URL keeps
    hunting agentically.
- **Unknowns to settle in its design**: sort order (a search URL sorted by
  "newly listed" is what makes page 1 sufficient); when the search URL goes
  stale (relearn after N empty scans or a site restyle); whether the result
  card's price can pre-filter candidates before the model sees them; how
  the swap rule (§4.6) applies to a scan on a full watch; migration 017.
- **Why before parallel hunts**: it removes most of the demand for
  concurrency. Measure after it ships whether PR 4 is still needed.

### PR 4 — `feat(agent): parallel hunts with per-site pacing`

**Goal.** Hunts for different sites run at the same time without stepping
on each other or on the sites. Build only after PR 3 has run for a while
and serial hunting is still measured to be the bottleneck.

- **Migration 018.** Mirrors.
- **Agent**: `agent/pacing.py` (`SiteGate`, registry, the wrapped navigate
  tool); the per-site LLM-relearn semaphore in `recheck.py`; site floor in
  the effective interval; `HUNT_CONCURRENCY` raised to a measured default;
  run-stats tally onto `UnitContext`; `save_listing` `SLOTS FULL:` backstop
  under `FOR UPDATE` on the watch.
- **Backend**: `Site` pacing fields + 422s (`min_gap_seconds < 1`,
  `max_concurrency` outside 1–5); `catalog.py` serializer.
- **Frontend**: site form fields; the "several live hunts" states from the
  design pass; `handlers.ts` scripts two concurrent hunts.
- **Operator**: memory guidance from `docker stats` in the README; the
  local-model note.
- **Tests**: `test_pacing.py` (gap + jitter bounds, concurrency cap, the
  wrapped navigate awaits the gate and refuses off-site/private hosts);
  `test_recheck.py` (semaphore: one relearn, others retry the ladder first);
  `test_slot_budget.py` (two concurrent `save_listing`s on the last slot →
  exactly one succeeds); `test_sites_api.py` 422s; `frontend:verify`.
- **Success**: two watches on two sites hunt concurrently with no "already
  in use" errors over a day of logs; per-site gaps never below the minimum;
  no watch exceeds `max_listings` (§7 query 6 = 0 rows).

---

## 6. Deferred (decided out of v1, not forgotten)

- **Token budgets** (`budget_windows`, reserve-at-claim / settle-at-finish,
  daily caps global and per watch). `jobs.stats.tokens_*` from PR 2b is the
  data a budget would be sized from.
- **Notification enrichment**: watch-vs-listing edge per channel, a
  per-listing cooldown for webhooks, the richer payload (market ratio,
  authenticity verdict, slots, previous price), and `digest_minutes` on
  channels. Its own project after the hunter is live.
- **Per-slot MCP containers** with their own profiles, if isolated contexts
  turn out to draw more bot challenges than the persistent profile did.
- **Extractor JS in CI** (declined for v1, decision 15): the JS constants
  are the most site-dependent code in the build and only their captured
  outputs are tested. The offered fix, browser-marked local tests that
  inject saved HTML fixtures into a blank page via `browser_evaluate` and
  run the real extractor, skipped when no Playwright MCP is reachable, is a
  small PR whenever a restyle bites.
- **Multi-daemon pacing**: the site gate and the breaker counter are
  per-process. One daemon per database is the supported shape; a cron
  `--once` next to a running daemon is safe (`SKIP LOCKED`) but doubles the
  per-site rate. DB-side gates if that ever matters.
- **`price_checks` growth**: every read is a row (~2,400 a day for 50
  listings on 30 min). Fine for years; a rollup of rows older than 30 days
  to one per listing per day, and a chart that buckets, if the history ever
  gets too dense to read.
- **Vision fetcher SSRF (S3)**: one small `fix(vision): refuse private-address
  image URLs` PR, independent of this plan.
- **Site logins** (`--storage-state` covers consent banners only).

---

## 7. Metrics (SQL now; behind `GET /api/admin/stats` later if wanted)

```sql
-- 1. share of rechecks without an LLM call, per site, last 7 days
SELECT s.name, count(*) AS checks,
       round(100.0 * count(*) FILTER (WHERE pc.method <> 'llm') / count(*), 1) AS pct_no_llm
FROM price_checks pc JOIN listings l ON l.id = pc.listing_id JOIN sites s ON s.id = l.site_id
WHERE pc.checked_at > now() - interval '7 days'
GROUP BY s.name ORDER BY checks DESC;

-- 2. time and tokens per job by kind and method, last 7 days
SELECT kind, stats->>'method' AS method, count(*),
       percentile_cont(0.5) WITHIN GROUP (ORDER BY (stats->>'duration_ms')::int) AS p50_ms,
       sum((stats->>'tokens_in')::int + (stats->>'tokens_out')::int) AS tokens
FROM jobs WHERE status = 'done' AND finished_at > now() - interval '7 days'
GROUP BY 1, 2 ORDER BY 1, 2;

-- 3. median price age across active listings, right now (add GROUP BY l.watch_id per watch)
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY now() - last.checked_at) AS median_age
FROM listings l JOIN LATERAL (
  SELECT checked_at FROM price_checks WHERE listing_id = l.id AND confirmed
  ORDER BY checked_at DESC LIMIT 1
) last ON true WHERE l.active;

-- 4. locator health: learned, failing, cleared
SELECT locator_kind, count(*) FILTER (WHERE locator_verified_at IS NOT NULL) AS learned,
       count(*) FILTER (WHERE locator_failures > 0) AS failing
FROM listings WHERE active GROUP BY locator_kind;

-- 5. notifications sent for a price a later read contradicted (should be 0)
SELECT o.id, o.payload->>'listing_id', o.payload->>'price'
FROM notification_outbox o
JOIN price_checks later ON later.listing_id = (o.payload->>'listing_id')::int
  AND later.checked_at > o.created_at AND later.checked_at < o.created_at + interval '1 hour'
WHERE o.event = 'target.hit' AND (later.status = 'error' OR NOT later.confirmed);

-- 6. watches over their slot budget (should be 0 rows)
SELECT w.id, w.max_listings, count(*) FROM watches w JOIN listings l ON l.watch_id = w.id AND l.active
GROUP BY w.id, w.max_listings HAVING count(*) > w.max_listings;

-- 7. hunt yield and backoff state per watch
SELECT watch_id, count(*) FILTER (WHERE (stats->>'new_listings')::int > 0) AS productive,
       count(*) AS hunts, max((payload->>'backoff_minutes')::int) AS backoff
FROM jobs WHERE kind = 'hunt' AND finished_at > now() - interval '7 days' GROUP BY watch_id;

-- 8. rechecks that never opened a browser, per site, last 7 days
SELECT s.name, count(*) AS rechecks,
       round(100.0 * count(*) FILTER (WHERE j.stats->>'transport' = 'static') / count(*), 1) AS pct_static,
       count(*) FILTER (WHERE l.static_ok) AS listings_static_ok
FROM jobs j JOIN listings l ON l.id = j.listing_id JOIN sites s ON s.id = l.site_id
WHERE j.kind = 'recheck' AND j.status = 'done' AND j.finished_at > now() - interval '7 days'
GROUP BY s.name;

-- 9. breaker state and LLM calls made while a site was paused (should be 0)
SELECT s.name, s.consecutive_errors, s.paused_until, s.paused_reason,
       (SELECT count(*) FROM jobs j JOIN listings l ON l.id = j.listing_id
        WHERE l.site_id = s.id AND j.stats->>'method' = 'llm'
          AND j.started_at BETWEEN s.paused_until - interval '1 day' AND s.paused_until) AS llm_while_paused
FROM sites s WHERE s.paused_until IS NOT NULL;
```

Plus, from tracing (Langfuse/LangSmith, already wired): tokens per run
session before vs. after PR 1, and tokens per hunt job after PR 2a.

---

## 8. Remaining open questions

Everything in §1 is settled. The items below were the calls made while
revising; on 2026-09-16 every one of them was confirmed as written
(decision 17) except **10, 11 and 17, which stay open** — none of those is
needed before PR 3. The list is kept so the reasoning stays next to the
decision.

1. **`POST /api/jobs` is one endpoint with a scope**, mirroring today's
   `POST /api/runs {scope, scope_id}`, rather than per-resource routes
   (`/api/items/{id}/hunt`, `/api/items/{id}/refresh`). Least contract churn
   and one MCP tool. *(PR 2a)*
2. **Anomalous LLM reads are recorded unconfirmed and excluded from
   aggregates** rather than not recorded at all, so the checks log shows
   what was seen. *(PR 1)*
3. **Rechecks write no `job_events`**; their result is the `price_checks`
   row and `jobs.stats`. The Activity page shows them as a counter/list from
   `listing.checked` frames, not as a feed. *(PR 2a, design pass)*
4. **Ground jobs run in the hunt pool** (the LLM-bearing pool). *(PR 2a)*
5. **`RUN_*` env vars are renamed `JOB_*` without aliases.** *(PR 2a)*
6. **No flag → usage and exit 2** (`argparse`), which changes bare
   `main.py` from "full sweep" to an error; cron users switch to `--once`.
   *(PR 2a)*
7. **Job visibility**: owner of the watch (and, for `ground`, anyone
   watching the item); admins see all. *(PR 2a)*
8. **Plausibility bands** `[0.2, 5]` vs. the listing's history and ≥ 0.1 ×
   the market tier median, tunable, 0 = off. *(PR 1)*
9. **Listing URL must match the site's domain** (S2). This rejects a
   listing the model saves from a redirect to a sister domain
   (`ebay.com` → `ebay.co.uk`). Accepting the loss; it is also the SSRF fix.
   *(PR 1)*
10. **Isolated contexts and bot friction**: unknown until measured whether
    eBay/Mercari serve more challenges to cookie-less contexts; mitigation
    `--storage-state`, fallback per-slot containers (§6). Decide after PR
    2a's first week of logs.
11. **Migration numbering** collides with the fraud-signals plan (014–016).
    First to merge wins; renumber on rebase.
12. **Decisions 9 and 10 together.** "Stop hunting when full" plus "swaps in
    both modes" only has an effect if swaps run on the one hunt that can
    happen on a full watch: the user's "hunt now". That is how §4.6 reads
    it. If you meant something else (for example a slow background swap
    hunt at the backoff cap), say so; the mechanics are the same, only the
    trigger changes. *(PR 2b)*
13. **Swap guard details** chosen without asking: one swap per site per
    hunt; a `replaced` listing hidden from re-discovery for 24 h; re-save of
    a `replaced` URL reactivates the old row with its history rather than
    creating a new one; existing inactive rows backfill `inactive_reason =
    'ended'`. *(PR 2b)*
14. **Static probe details** chosen without asking: `jsonld` and `meta`
    kinds only; redirects are never followed by the GET (the browser
    confirms a move); one column `static_ok`, cleared on the first
    static-fail/browser-success and re-set at the next LLM learn, rather
    than a second failure counter. *(PR 1)*
15. **Breaker thresholds**: 5 consecutive errors, 60 min doubling to 24 h,
    counted across rechecks and hunts of the site, reset by any success.
    A trip also pauses hunts on that site, which is intended: a bot wall
    blocks discovery too. *(PR 2a)*
16. **Kill switch semantics**: "hunt now" answers 409 `hunting_disabled`
    rather than queueing silently; rechecks are unaffected; the value must
    be set in both env files. *(PR 2b)*
17. **PR 3 is a sketch.** Its unknowns are listed in §5; it is reserved so
    the order (before parallel hunts) and migration 017 are settled, not so
    it can be built from this doc. *(PR 3)*
