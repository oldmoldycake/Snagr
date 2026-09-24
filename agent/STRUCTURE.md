# Agent Structure — What Goes Where

The map of every file in `agent/`, the hunter.

The hunter is a daemon that claims jobs from the Postgres `jobs` table and
works them. There are three kinds: a `hunt` searches one (watch, site) pair for
listings with a model driving a headless browser (Playwright MCP); a `recheck`
re-reads one listing's price, usually with no model at all; a `ground` refreshes
one item's market-price stats. `main.py --serve` runs until stopped (compose);
`main.py --once` queues what is due, drains the queue and exits (cron).

**The schema is not the agent's.** `database.py` holds a column-compatible
subset of `backend/app/models.py`, which owns the canonical schema and every
Alembic migration. Schema changes go through a backend revision; never run
`Base.metadata.create_all()` from here against the live DB.
**`agent/.env.example` is the source of record for configuration** — every knob
is optional there and explained; the table at the end summarizes it.

Stack: asyncio + async SQLAlchemy 2.0 (asyncpg) + LangChain `create_agent` over
`langchain-mcp-adapters`. Flat modules, no package; each carries a docstring
stating its job.

---

## Tree

```
agent/
├── main.py            # entry point: logging, --serve | --once (no bare mode), SIGTERM/SIGINT → cancellation via _supervised
├── worker.py          # the daemon: the two pools, LISTEN snagr_jobs + 30 s tick, per-kind job runners, housekeeping (reap, grounding, sweep, prune)
├── jobs.py            # the queue: claim, heartbeat, complete / fail_or_retry, successors, hunt backoff + wakes, sweep, reap, prune, job events
├── agent.py           # the model-facing units: browser session + tool filtering, guarded browser_navigate, run_hunt_job, recheck_listing, the unit budgets
├── prompt.py          # prompt text: the hunt prompt (TRACKING SLOTS / TRACKED LISTINGS), the recheck prompt, grounding's two prompts
├── tools.py           # the DB-writing tools the model calls — their docstrings ARE the tool descriptions it reads
├── observations.py    # the one writer of a price observation (record_price_check) + UnitContext, the ids a unit is bound to
├── recheck.py         # recheck_deterministic: the static rung, then the read ladder — a price with no model in the loop
├── locators.py        # where a price lives on a page: the page extractor JS, select_locator, replay, site_consensus, PageReader
├── static.py          # the browserless rung: one plain GET, jsonld/meta locators only; the learn-time probe that sets static_ok
├── breaker.py         # the per-site circuit breaker: count consecutive read errors, pause the site, push its jobs out
├── validation.py      # what the agent may believe (pure): parse_price, validate_observation, url_allowed, clip_text
├── pricing.py         # market-price grounding: SearXNG + guide pages over plain HTTP, model extraction, tier stats → market_prices
├── notify.py          # the target-hit *decision* only (pure): is this reading a crossing, and what is the owner told
├── llm.py             # build_llm(): the chat model, built on demand so the check pool pays for one only when it needs it; the tracing handler, job_trace, flush_traces
├── config.py          # settings from env/.env — every one except DATABASE_URL (see Conventions)
├── database.py        # engine + session factory, the ORM subset of backend/app/models.py, the read/write helpers the units use
├── Dockerfile         # 2-stage: build venv → slim runtime; CMD is --once, compose overrides it with --serve
├── requirements.txt   # pinned deps incl. the LangChain provider packages; ruff unpinned (CI pins it)
├── pytest.ini         # testpaths + pythonpath=. (flat modules, not a package)
└── tests/
    ├── conftest.py     # DATABASE_URL → snagr_test rewrite, AI_*/MCP stubs, migration 015's index + triggers by hand, unit_runtime()
    ├── fixtures/       # captured page-extractor output (see README.md), raw HTML for the static rung, raw MCP replies
    └── test_*.py       # one module per concern (23 files) — copy the nearest sibling's pattern
```

---

## Layer responsibilities (the mental model)

Job flow: **worker** (claim, pools, terminal state) → **unit** (`agent.py` for
model work, `recheck.py` for code-only reads, `pricing.py` for grounding) →
**writers** (`tools.py` for the model, `observations.py` for every price) →
**`database.py` / `jobs.py`** (SQL). **`validation.py`** and **`breaker.py`** sit
across all of it deciding what is believed and which sites are read at all.

| Layer | Owns | Never does |
|---|---|---|
| `worker.py` | which pool claims what, running one job, its terminal state, housekeeping | read a page or run a model stream itself |
| `jobs.py` | every queue write: claim, finish, successors, wakes, sweep, reap, prune, events | swallow a failure (except the best-effort heartbeat, status poll, `wake_hunts`, `append_event`) |
| `agent.py` + `prompt.py` | one model unit: session, tools, prompt, budgets, cancellation | pick what to work on |
| `tools.py` | validating what the model typed, returning errors as strings it can read | take a watch/item/site id from the model, or trust a listing id it typed |
| `observations.py` | writing a price check + its notification + its hunt event, atomically | decide whether a reading is a crossing (`notify.py` does) |
| `recheck.py` / `locators.py` / `static.py` | reading a price with code alone | conclude a listing is gone from the raw HTML |
| `validation.py` | shape, plausibility, URL and text guards | touch the DB, the network or DNS |
| `config.py` | reading env | anything else |

---

## How a job flows

1. **Claim.** `jobs.claim` is one `UPDATE … WHERE id = (SELECT … FOR UPDATE OF j
   SKIP LOCKED LIMIT 1) RETURNING …`: highest `priority` first (a user's "hunt
   now" is 100), then oldest `run_after`, then oldest id. The subquery
   `LEFT JOIN`s `sites` and **skips any job whose site is paused** — that is the
   circuit breaker's whole enforcement. The claim stamps `running`, `locked_by`,
   `heartbeat_at`, `started_at` and spends an attempt.
2. **Pools.** `worker.serve` starts `RECHECK_CONCURRENCY` check workers that
   claim `recheck` (browser session always, a model only when the ladder gives
   up) and `HUNT_CONCURRENCY` hunt workers that claim `hunt` (model + browser)
   and `ground` (model + SearXNG + plain HTTP, no browser). Under
   `HUNT_ENABLED=false` the hunt pool claims only `ground` (`worker.kinds_for`).
   Worker ids are `host:pid#check-N` / `#hunt-N`, recorded on every claimed row.
3. **Wake-ups.** Migration 015's trigger `NOTIFY`s `snagr_jobs` on every job
   insert and status change; one `LISTEN` connection nudges every worker, and
   each drains its kinds until the queue is empty. A 30 s tick does the same
   thing, so nothing depends on a NOTIFY arriving; the listener reconnects
   forever on DB loss.
4. **Run.** Each hunt and recheck opens and closes its own MCP session
   (`agent.open_browser_session`); with the server on `--isolated` that is its
   own browser context, which is what lets "check prices now" overtake a hunt.
   Hunt and recheck units run under `bounded` (`AGENT_UNIT_TIMEOUT_SECONDS`),
   model units under `recursion_limit = AGENT_MAX_STEPS`; a `ground` job has
   neither cap. A hunt's model is sent only its latest `agent.PAGES_KEPT`
   tool results in full — older page snapshots become a placeholder, the DB
   tools' one-line replies are kept — so its cost grows with the pages it
   reads, not with their square. A hunt polls its job's status every 5 s between model steps and
   stops on `cancelled`. `_with_heartbeat` stamps `jobs.heartbeat_at` every
   `JOB_HEARTBEAT_INTERVAL_SECONDS` meanwhile.
5. **Finish.** `jobs.complete` (done, stats) or `jobs.fail_or_retry` (back to
   `pending`, due at once, until `JOB_MAX_ATTEMPTS` attempts are spent, then
   `failed`). A job the API cancelled mid-flight keeps `cancelled`. Successors
   are inserted **in the same transaction**: a recheck that completes, is
   cancelled, or fails for good queues the listing's next check; a hunt that
   completes queues its pair's next hunt (see below).
6. **Shutdown.** `main._supervised` turns SIGTERM/SIGINT into task
   cancellation; `serve`'s `finally` cancels the pools and hands everything this
   process holds back to `pending` in one statement (`jobs.release_all`).
7. **Housekeeping.** `worker._scheduler` runs `housekeeping` every 60 s:
   `jobs.reap` (any `running` row silent past `JOB_STALE_AFTER_SECONDS` goes
   through `fail_or_retry`) and `queue_grounding` every pass; `jobs.sweep` and
   `jobs.prune` every 60th pass **and on the first**, so a hunter that was down
   picks dropped pairs back up the moment it starts. `--once` runs one
   housekeeping pass (first-pass rules) before draining.

---

## Nine things that aren't obvious (read before you touch the agent)

1. **The queue is the design** (`jobs.py`, `backend/app/services/jobs.py`,
   migration 015). The partial unique index `uq_jobs_open` allows one *open*
   (`pending`/`running`) job per target, so every insert on both sides is
   `ON CONFLICT DO NOTHING`, "check this listing now" is an UPDATE of the
   pending row (the backend's `services/jobs.py`), and `POST /api/jobs` never
   409s on a duplicate. A listing always has exactly one recheck ahead of it:
   `save_listing` queues the first in the transaction that saves the listing,
   and every terminal finish queues the next (a retry is the same row going
   back to `pending`) — a listing that dropped out of the queue would silently
   stop being watched. Untracking is what ends the chain. The next check is due at the
   watch's `recheck_interval_minutes`, else `RECHECK_INTERVAL_MINUTES`, never
   below `RECHECK_INTERVAL_FLOOR_MINUTES`, and never inside a site pause. Set both
   interval settings to the same values in `backend/.env`: the UI reads the
   default from the backend and the API refuses an interval below the floor.

2. **A watch with open slots is hunted on its own; a full one gets no new
   hunts**, so a full watch costs nothing until a slot frees. A completed hunt
   queues its pair's next one while the watch has room and `watches.hunt` is
   on: at once after a save, otherwise `payload.backoff_minutes` out, doubling per empty hunt from
   `HUNT_BACKOFF_MIN_MINUTES` to `HUNT_BACKOFF_CAP_MINUTES` (15 → 360,
   `reason='backoff'`). A freed slot — `disable_listing`, a recheck that sees the
   listing sold/ended/auction-only, the user's untrack — wakes the watch's hunts
   with their backoff forgotten (`add_hunt_wakes`, twinned by the backend's
   `wake_hunts`). `jobs.sweep` is the safety net, not the engine: a hunt for
   every huntable pair with nothing open. `watches.hunt = false` means hunted
   only on "hunt now"; rechecks carry on. `HUNT_ENABLED=false` is the operator's
   kill switch: no sweep, no successors, no wakes, and queued hunts wait; the
   backend (same value in `backend/.env`) answers `POST /api/jobs` for a hunt
   with 409 `hunting_disabled`.

3. **A hunt that finds its watch full is a swap hunt.** Hunts run one site at
   a time, so whichever site goes first can fill every slot; the other sites'
   hunts, already queued, then run as swap hunts rather than skipping, so
   every site gets its say. Nothing queues a new hunt for a full watch, so
   this is one pass per queued site each time the watch fills. A person's
   "hunt now" on a full watch is one too (the backend flags it
   `payload.swap = true`, `services/jobs.py::_hunts`; the agent needs no
   flag). `run_hunt_job` replaces the `TRACKING SLOTS` prompt block with
   `TRACKED LISTINGS`, weakest first (`database.weakest_first` — cheapest:
   highest price; best match: lowest score, higher price breaking a tie).
   Every `save_listing` on a full watch is a trade, and code picks what it
   trades away: the weakest tracked listing, ranked under a lock on the watch
   row, retired in the transaction that saves the new one. The reply
   (`TRADED:`) names the new weakest, and a hunt trades as often as the site
   has something better. `save_listing` answers `SLOTS FULL:` outside a swap
   hunt, for a price the bands disbelieve, in cheapest mode unless the price
   is strictly lower than the weakest's last confirmed one, and in best-match
   mode unless the match score is higher, or equal at a lower price; a
   refused save changes nothing. A `replaced` URL stays in
   `get_known_listing_urls` for `REPLACED_HIDDEN_FOR` (24 h, timed from the
   swap's `listing_ended` event), and re-saving it later brings back the same
   row with its history — unlike sold/ended/auction/untracked, which answer
   `SKIPPED:`. Should a slot have freed since it was queued, a swap hunt runs
   as an ordinary one.

4. **Most rechecks never reach the model.** When a price is confirmed by the
   model (`save_price_check`, or `save_listing` with a price), code — never the
   model — reads the page, picks what holds that exact number
   (`locators.select_locator`, priority `jsonld → meta → microdata → css`),
   replays it once to verify, and stores `price_locator` / `locator_kind` on the
   listing. For `jsonld`/`meta` it also probes the raw HTML and sets `static_ok`
   when a plain GET reads the same price. `recheck_deterministic` then tries the
   static rung (`STATIC_FETCH`), then one browser load and the ladder: the
   listing's locator → the site's consensus locator → the JSON-LD/meta
   fallbacks. The LLM is the fallback, and its read relearns the locator; a
   locator that misses `LOCATOR_MAX_FAILURES` times is cleared.
   `CHEAP_RECHECK=false` sends every recheck through the model.
   `price_checks.method` records the path (`llm` | `jsonld` | `meta` |
   `microdata` | `locator`, the last meaning a replayed css path); §7 query 1 of
   `docs/design/perpetual-hunter.md` measures the share.

5. **A site that stops answering is left alone** (`breaker.py`).
   `SITE_BREAKER_ERRORS` (5) consecutive failed reads pause the site for
   `SITE_BREAKER_MINUTES` (60), doubling per trip up to `SITE_BREAKER_CAP_MINUTES`
   (1440); any successful read resets the count, and a disbelieved price still
   counts as an answer. Paused means invisible: the claim skips the site's jobs
   and its pending jobs are pushed out to the moment the pause lifts
   (`reason='paused'`, a user's own request keeps `'user'`). The trip writes a
   `warn` `site_paused` event on the job that caused it. `PATCH /api/sites/{id}`
   with `paused_until: null` lifts it by hand; nothing in the agent shortens one.

6. **Nothing believes a page on sight** (`validation.py`). `validate_observation`
   *refuses* a reading that is not a price (bad shape, zero, more than two
   decimals, an auction-only page) — nothing is recorded — and *disbelieves* one
   outside the bands: `PRICE_BAND_LOW`/`PRICE_BAND_HIGH` against the listing's
   last confirmed price, `PRICE_MARKET_FLOOR` against the item's market median.
   A disbelieved model read is recorded with `confirmed = false`, never
   notifies, and stays out of every aggregate for good; the *next* read landing
   within 1% of it is the one believed. A disbelieved locator read is thrown
   away and the model re-reads the page. `url_allowed` keeps a URL inside the
   site's registrable domain and off the private network, for storing a URL
   *and* for every navigation: the model is given a `browser_navigate` wrapper
   (`guarded_navigate`), and code execution, file upload and tab control are
   withheld (`BLOCKED_BROWSER_TOOLS`). `clip_text` caps model-typed text before
   it reaches a later prompt or a notification body.

7. **One writer owns the observation** (`observations.record_price_check`).
   The model's `save_price_check`, `save_listing` with a price, and the
   deterministic recheck all end there: the check row, the cooldown take, the
   `target.hit` outbox row and — on a hunt — the job event, in one transaction
   under a row lock on the watch, with the notification steps in a savepoint so
   an observation always beats a notification. `target.hit` is edge-triggered
   (`notify.target_hit_payload`: only a price that *crosses* the target) and
   stamped on `watches.last_notified_at` at enqueue, with
   `NOTIFY_COOLDOWN_HOURS` as the spam floor. `listing.new` is queued by
   `save_listing` after its commit (`database.enqueue_new_listing`), for a new
   row only. A watch's `notify` flag gates alerting, nothing else — a muted
   watch is still hunted and rechecked. The agent only writes
   `notification_outbox`; migration 010's trigger wakes the backend dispatcher
   (`backend/app/services/notifications.py`), which delivers and retries. The
   agent never contacts a push service.

8. **The tools' docstrings are prompts.** Every function in `tools.py` handed
   to the model is described to it by its docstring, so keep them accurate and
   imperative and update them whenever behavior changes; errors go back as
   strings the model can act on (`Error:`, `SKIPPED:`, `SLOTS FULL:`,
   `REFUSED:`, `TRADED:`, `ALREADY RECORDED:` — a hunt reads each listing
   once, `UnitContext.observed`). The watch, item and site a call is about are never arguments:
   the orchestrator binds an `observations.UnitContext` onto the run config,
   and each tool reads it through the injected `ToolRuntime` (`tools.unit_of`),
   which never appears in the tool schema. A `listing_id` the model does pass
   is checked against the unit (`observations.assert_writable`): on a recheck
   it must be the one listing, on a hunt one of the watch's. The unit also
   carries its job id and its own stats tally, because several jobs run at
   once.

9. **Who writes job events.** A hunt writes its story — `job_started`, each
   page read, `listing_discovered` / `listing_evaluated` / `listing_ended`,
   `price_found`, `job_finished`. A `ground` job writes one `job_finished`. A
   recheck writes nothing when it succeeds: its whole output is its
   `price_checks` row, which migration 015's trigger turns into a
   `listing.checked` frame. Every kind, recheck included, gets the worker's
   generic lines (`worker._work_one`) — an `error` when it raises, a `warn`
   when cancelled mid-flight — and the breaker's `site_paused` when it trips.

---

## Configuration

Defaults are those in `config.py`; `agent/.env.example` explains each at length.

| Group | Variable | Default | Meaning |
|---|---|---|---|
| Provider | `AI_PROVIDER` / `AI_MODEL` | `open_router` / `qwen3.6:35b` | any LangChain `init_chat_model` provider key and model |
| | `AI_URL` / `AI_API_KEY` | `http://localhost:11434` / unset | provider base URL; key passed only when set |
| Connections | `DATABASE_URL` | required | the shared Postgres (asserted at import by `database.py`) |
| | `PLAYWRIGHT_MCP_URL` | required for browser jobs | the MCP server; it **must** run with `--isolated` |
| | `SEAR_XNG_URL` | unset | SearXNG for grounding (read into `config.SEARXNG_URL`) |
| | `VISION_SIDECAR_URL` | unset | vision sidecar; unset = `check_images` not registered |
| Pools | `RECHECK_CONCURRENCY` | 3 | check workers |
| | `HUNT_CONCURRENCY` | 1 | hunt workers (hunt + ground); raise only after measuring the provider |
| Hunting | `HUNT_ENABLED` | true | kill switch; same value in `backend/.env` |
| | `HUNT_BACKOFF_MIN_MINUTES` / `_CAP_MINUTES` | 15 / 360 | empty-hunt backoff, doubling |
| Recheck | `RECHECK_INTERVAL_MINUTES` | 30 | default cadence; same value in `backend/.env` |
| | `RECHECK_INTERVAL_FLOOR_MINUTES` | 5 | least any watch gets; same value in `backend/.env` |
| | `CHEAP_RECHECK` | true | false = every recheck through the model |
| | `STATIC_FETCH` | true | false = never the browserless GET |
| | `LOCATOR_MAX_FAILURES` | 3 | misses before a locator is cleared and relearned |
| Breaker | `SITE_BREAKER_ERRORS` | 5 | consecutive failed reads that trip it |
| | `SITE_BREAKER_MINUTES` / `_CAP_MINUTES` | 60 / 1440 | first pause, doubling to the cap |
| Plausibility | `PRICE_BAND_LOW` / `PRICE_BAND_HIGH` | 0.2 / 5 | ratio band against the listing's last confirmed price; 0 = off |
| | `PRICE_MARKET_FLOOR` | 0.1 | fraction of the market median below which a price is disbelieved; 0 = off |
| Job lifecycle | `JOB_HEARTBEAT_INTERVAL_SECONDS` | 30 | heartbeat cadence |
| | `JOB_STALE_AFTER_SECONDS` | 300 | silence before the reaper takes a job back |
| | `JOB_MAX_ATTEMPTS` | 3 | attempts before a job is failed for good |
| | `AGENT_MAX_STEPS` | 200 | graph steps per model unit (~2 per tool call) |
| | `AGENT_UNIT_TIMEOUT_SECONDS` | 900 | wall-clock cap per unit |
| Retention | `JOB_RETENTION_DAYS` | 7 | terminal recheck + ground jobs |
| | `HUNT_RETENTION_DAYS` | 90 | terminal hunts (events cascade) |
| Grounding | `EXPECTED_CURRENCY` | USD | the one currency stats are built from and alerts fire in |
| | `MARKET_PRICE_TTL_HOURS` | 24 | stats older than this refresh; also the retry backoff |
| | `MARKET_PRICE_MAX_REFRESH_PER_RUN` | 10 | stale items per pass (never-grounded ones exempt) |
| Vision | `VISION_TIMEOUT_SECONDS` | 90 | hard cap on one sidecar call |
| Notifications | `NOTIFY_COOLDOWN_HOURS` | 24 | spam floor under the edge trigger |
| Tracing | `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` | unset | both set = Langfuse callback on (`LANGFUSE_BASE_URL` read by its SDK) |
| | `LANGSMITH_TRACING` / `_API_KEY` / `_PROJECT` | unset | read by LangChain itself, not by `config.py` |

### What lands in the tracer

Only model calls are traced, so a recheck the ladder handled leaves no trace:
the count of `recheck` traces is how often the model fallback ran, not how
many checks there were. The hunter never stops, so a session is the thing
being watched rather than a run, and everything else is a tag:

| Trace name | Session | User | Tags | Metadata |
|---|---|---|---|---|
| `hunt` | `watch-<watch_id>` | watch owner | `kind:hunt`, `site:<name>`, `category:<slug>`, `swap` on a swap hunt | `job_id`, `watch_id`, `item_id`, `site_id` |
| `recheck` | `watch-<watch_id>` | watch owner | `kind:recheck`, `site:<name>`, `category:<slug>` | the same, plus `listing_id` |
| `ground` | `item-<item_id>` | none — shared by every watcher | `kind:ground`, `category:<slug>` | `job_id`, `item_id`, `category_id` |

Hunts and rechecks carry these on their agent config (`agent.agent_config`).
Grounding makes bare model calls, which the Langfuse handler does not lift
into trace attributes, so the ground job opens the trace itself
(`llm.job_trace`) and its `condition-tiers` and `extract-observations` calls
nest inside it. `tests/test_tracing.py` pins that handler behavior.

---

## Tests

`./venv/bin/pytest` from `agent/`. The suite is **sync**: there is no
pytest-asyncio, and DB tests drive coroutines on a module-level event loop
(`_LOOP.run_until_complete`) or with `asyncio.run`.

- `conftest.py` rewrites `DATABASE_URL` to the **same `snagr_test` DB the
  backend suite uses** before any agent module is imported; DB-backed modules
  create the agent's subset schema there and drop it afterwards. **Never run the
  agent and backend suites at the same time.**
- The queue's rules are not in any ORM model, so `conftest.py` hand-copies
  migration 015's `uq_jobs_open` index (`OPEN_JOB_INDEX`) and its notify
  triggers (`JOB_NOTIFY_DDL`). A migration that changes either must update it,
  and `backend/tests/conftest.py` too.
- `fixtures/` holds real `PAGE_EXTRACTOR_JS` captures (provenance and
  redactions in `tests/fixtures/README.md`), `static_*.html` pages for the
  static rung, and raw MCP replies for `parse_result`.
- `unit_runtime()` builds the `ToolRuntime` a tool receives, so tool tests call
  the real function with a bound `UnitContext`.

---

## Conventions

- **`config.py` reads the settings.** The one exception is `DATABASE_URL`,
  which `database.py` reads itself because the engine is built at import.
- **Tool docstrings are prompts** — reviewed like code, updated with behavior.
- **Failures in the queue propagate** (`jobs.py`); read helpers in
  `database.py` answer an empty default so a hiccup skips optional work.
- **Prices are `Decimal`, parsed by `validation.parse_price`**, and every
  observation goes through `record_price_check`.
- **Locking order is watch, then site, then job**, everywhere (`jobs.add_event`).
- **ruff**: `./venv/bin/ruff check --fix && ./venv/bin/ruff format`; CI pins the
  version in `.github/workflows/ci.yml`.
