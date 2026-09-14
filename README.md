# Snagr

[![CI](https://github.com/oldmoldycake/Snagr/actions/workflows/ci.yml/badge.svg)](https://github.com/oldmoldycake/Snagr/actions/workflows/ci.yml)
[![CodeQL](https://github.com/oldmoldycake/Snagr/actions/workflows/codeql.yml/badge.svg)](https://github.com/oldmoldycake/Snagr/actions/workflows/codeql.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)

A self-hosted price tracker for secondhand-marketplace hunting. You describe what you're watching for and at what price; an LLM agent drives a real headless browser to find new listings and re-check known ones, and the web UI shows every hunt's state at a glance — current best price, drift against your target, price history, and live run progress.

**Status: pre-release.** The whole stack runs end to end — the backend implements the full frontend contract, and every push to `main` publishes container images — but there are no versioned releases yet (version `0.1.0`; release-please is wired up and waiting for the first one). Expect rough edges.

![The dashboard: tonight's verdict, agent status, and every watched item with trend, best price, site, and drift to target](docs/screenshots/dashboard.png)

![An item: per-listing price history against the target line, tracking rules, and each listing's drift](docs/screenshots/item-detail.png)

*Both screenshots are the frontend's built-in mock data (see [Development](#development)).*

## Features

- **Watches, not bookmarks** — track an *item* across several marketplace sites at once, with a target price, free-form criteria the agent applies when judging listings, a selection mode (`cheapest` or `best_match`), and a slot budget so a watch never balloons past the number of listings you asked for.
- **LLM scraping through a real browser** — the agent works marketplace pages via [Playwright MCP](https://github.com/microsoft/playwright-mcp), so it sees what you'd see. The model is pluggable: any [LangChain `init_chat_model`](https://python.langchain.com/docs/how_to/chat_models_universal_init/) provider via four env vars. The agent ships adapters for OpenRouter, OpenAI, Anthropic, Google, Ollama, Groq, Mistral, Together, Fireworks, xAI, DeepSeek, Cohere, and AWS Bedrock.
- **Price history that means something** — every re-check is recorded; best/average price, sparklines, and percent drift are derived from the raw checks. Prices are `Numeric(10,2)` in the database and decimal strings in the API, never floats. Auction bids are never recorded as prices (Buy It Now is the exception), so a $1 opening bid can't fake a target hit.
- **Runs from the UI** — trigger a scrape for everything, one category, one site, or one item and watch it live over SSE; the run history keeps every run's event log. Recurring schedules exist at the database level (`run_schedules`, fired by the agent's queue ticker) but have no UI or API yet.
- **Market-price grounding** — the agent periodically researches a reference market price per item and condition tier (price guides first, then a broad [SearXNG](https://docs.searxng.org) snippet search) so "is this a deal?" has a denominator.
- **Visual authenticity (optional)** — a DINOv3 sidecar embeds listing photos and scores them against a per-item reference library of real and fake examples. Suspicious listings are flagged on the board, and their photos land in a review queue where confirming one grows the library. Fully opt-in; the stack runs without it.
- **Self-host-friendly auth** — httpOnly cookie sessions with rotating refresh tokens, optional OIDC SSO (Authentik, Keycloak, …), first registered user becomes admin, and registration is invite-only after that unless you open it.
- **Notifications you own** — when a watch's best price crosses its target, or a genuinely new listing shows up, the agent queues an event and the backend delivers it to the channels you configure under Settings: your own [ntfy](https://ntfy.sh) server, a Discord channel, or any webhook (HMAC-signed JSON, so other tools can build on top). Target hits are edge-triggered with a cooldown, so a listing that merely stays cheap isn't re-announced every night.

## Architecture

Four independently-deployed components in one repo, sharing one PostgreSQL database (**pgvector required**):

| Component | What it is | Runs as |
|---|---|---|
| `backend/` | FastAPI JSON API (async SQLAlchemy 2.0 / asyncpg), owns the schema + Alembic migrations | server on `:8000` |
| `frontend/` | React 19 + Vite + Tailwind v4 SPA, served by nginx which proxies `/api` | server on `:80` (compose publishes it on `:8081`) |
| `agent/` | LangChain scraper batch job driving Playwright MCP | scheduled / queue-ticker, not a server |
| `vision/` | optional visual-authenticity sidecar (DINOv3 embeddings, S3-compatible object store — MinIO in the compose profile) | server on `:8100`, opt-in |

## Requirements

- **PostgreSQL with the [pgvector](https://github.com/pgvector/pgvector) extension** — required since migration 009 whether or not the vision sidecar is enabled (the schema carries embedding columns either way). The drop-in [`pgvector/pgvector`](https://hub.docker.com/r/pgvector/pgvector) image ships it preinstalled; on an existing server, install the distro package (e.g. `postgresql-18-pgvector` on Debian/Ubuntu, matching your major version) and enable it once per database as a superuser:

  ```sql
  CREATE EXTENSION vector;
  ```

  **Upgrading an existing install?** `alembic upgrade head` stops at migration 009 with exactly this instruction:

  > Snagr now requires the pgvector extension. Run `CREATE EXTENSION vector;` as your Postgres admin (see README → Requirements), then re-run `alembic upgrade head`.

  Enabling the extension and re-running the migration is the whole upgrade — no data changes.

- A [Playwright MCP](https://github.com/microsoft/playwright-mcp) endpoint the agent can reach.
- An LLM API key — or a local model server — for any [LangChain `init_chat_model`](https://python.langchain.com/docs/how_to/chat_models_universal_init/) provider.
- A [SearXNG](https://docs.searxng.org) instance with the JSON output format enabled, for market-price grounding. Without one, grounding attempts fail and are logged; scraping itself is unaffected.
- **Docker + Docker Compose v2** for the reference stack. To run components outside Docker instead: **Python 3.14** (a hard floor — `agent/main.py` uses 3.14-only `except` syntax) and **Node 22** (what CI and the images use).

## Installing

There is no production compose stack yet — the [development stack](#development) below is the reference wiring. CI does publish an image per component to GHCR on every push to `main`:

```
ghcr.io/oldmoldycake/snagr-backend
ghcr.io/oldmoldycake/snagr-frontend
ghcr.io/oldmoldycake/snagr-agent
ghcr.io/oldmoldycake/snagr-vision
```

`:dev` tracks the tip of `main` and `:sha-<short>` pins a commit; semver tags and `:latest` will appear with the first release. Images are published for `linux/amd64` only — on arm64, build from source. They run their baked-in commands (uvicorn on `8000`, nginx on `80`, one scrape pass then exit, uvicorn on `8100`) and are configured entirely through the env vars listed under [Configuration](#configuration).

## Development

Each Python component keeps its own `venv/`; the frontend is plain npm. The fastest full stack is compose:

```bash
git clone https://github.com/oldmoldycake/Snagr.git && cd Snagr

# 1. Point the components at your Postgres (pgvector enabled), Playwright MCP, and SearXNG
cp backend/.env.example backend/.env   # DATABASE_URL, JWT_SECRET, ...
cp agent/.env.example agent/.env       # AI_* provider vars, PLAYWRIGHT_MCP_URL, SEAR_XNG_URL, DATABASE_URL

# 2. Create the schema (run CREATE EXTENSION vector first — see Requirements)
cd backend && python -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/alembic upgrade head && cd ..

# 3. Run everything
docker compose up --build   # frontend :8081, backend :8000, agent run-queue ticker
```

The compose `agent` service also loads `agent/.env.docker` (gitignored, no example file yet): `agent/.env` is written for host-side runs with `localhost` URLs, and the overlay re-points `DATABASE_URL` and `PLAYWRIGHT_MCP_URL` at hosts the container can reach (add `VISION_SIDECAR_URL=http://vision:8100` there if you use the vision profile). Create it before step 3 or compose refuses to start. Postgres and the Playwright MCP stay external.

The agent ticker checks the run queue every minute — that's what makes UI-triggered runs actually execute — and refreshes stale market prices every 15th tick. It also fails any run whose agent process died (no heartbeat for five minutes), so a crash never leaves the Run button stuck on "a run is already active". For a cron-driven deployment instead, `agent/.env.example` lists the equivalent crontab lines (`main.py` nightly, `--consume` every minute, `--ground-only` every 15 minutes).

The frontend also runs fully standalone on a mock API seeded with a year of price history (`VITE_USE_MOCKS=true npm run dev` in `frontend/`, sign in with `demo@snagr.dev` / `snagr`) — see [frontend/README.md](frontend/README.md). Backend architecture is documented file-by-file in [backend/STRUCTURE.md](backend/STRUCTURE.md).

To enable the visual-authenticity sidecar: `cp vision/.env.example vision/.env` and set its `S3_SECRET_KEY` (it ships as `CHANGE_ME`) to match the compose MinIO password — `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` default to `snagr-minio` / `snagr-minio-secret`, and the sidecar can't reach its bucket until the two agree. Then set `VISION_SIDECAR_URL=http://vision:8100` in `backend/.env` and `agent/.env.docker` (the profile only starts the sidecar; each component switches the feature on when that var is set — use `http://localhost:8100` only when the backend or agent runs on the host), and `docker compose --profile vision up --build`. The [DINOv3 weights](https://huggingface.co/facebook/dinov3-vits16plus-pretrain-lvd1689m) are license-gated: accept the license and set `HF_TOKEN`, or the sidecar starts degraded (`/health` says so) and scoring is skipped.

## Configuration

Each component reads its own `.env`; the annotated `.env.example` files are the authoritative reference:

| File | The important ones |
|---|---|
| [`backend/.env.example`](backend/.env.example) | `DATABASE_URL`, `JWT_SECRET` (generate one!), `COOKIE_SECURE`, `REGISTRATION_OPEN`, `OIDC_*`, `NTFY_SERVER_URL`, `VISION_SIDECAR_URL`, `MCP_ENABLED` |
| [`agent/.env.example`](agent/.env.example) | `AI_PROVIDER` / `AI_MODEL` / `AI_URL` / `AI_API_KEY`, `PLAYWRIGHT_MCP_URL`, `DATABASE_URL`, `SEAR_XNG_URL`, `EXPECTED_CURRENCY`, `VISION_SIDECAR_URL`, `NOTIFY_COOLDOWN_HOURS`, the `RUN_*` / `AGENT_*` run-lifecycle caps; optional LangSmith / Langfuse tracing |
| [`vision/.env.example`](vision/.env.example) | `DATABASE_URL` (sync `postgresql+psycopg://` driver), `S3_*`, `HF_TOKEN`, `VISION_MODEL` (must embed at dim 384), `VISION_RETENTION_DAYS` |
| compose environment (root `.env` or your shell; `vision` profile only) | `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` — must match `S3_ACCESS_KEY` / `S3_SECRET_KEY` in `vision/.env` |

## Connecting an agent (MCP)

Snagr speaks the [Model Context Protocol](https://modelcontextprotocol.io): the same operations the web app uses are exposed as tools at `POST /api/mcp`, so Claude Code, Hermes, OpenClaw or any MCP client can browse your items, prices and runs on your behalf and, with the right scope, add watches, edit them and kick off runs.

1. **Settings → MCP & API → New token** — pick an access preset and copy the token; it is shown once.
2. Paste the ready-made config for your client from the same page. For Claude Code:
   ```bash
   claude mcp add --transport http snagr https://snagr.example.com/api/mcp --header "Authorization: Bearer snagr_pat_…"
   ```

Tokens are scoped (`read` / `write` / `runs`), never reach account or admin routes, and double as a bearer credential on the REST API. `MCP_ENABLED=false` turns the whole surface off. claude.ai and Claude Desktop connectors need OAuth sign-in, which Snagr doesn't offer yet — use a client that sends a bearer header.

## Webhooks

A `webhook` channel (Settings → Notifications) POSTs a signed, versioned envelope for
every event it's subscribed to. Two events exist today — `target.hit` (a price check made
a watch's best price cross its target, edge-triggered) and `listing.new` (the scan pass
saved a genuinely new listing, no price yet):

```json
{ "version": 1, "id": 123, "event": "target.hit",
  "occurred_at": "2026-09-01T05:12:00+00:00",
  "data": { "watch_id": 4, "item_id": 12, "listing_id": 88, "site_id": 2,
            "item_name": "…", "site_name": "…", "listing_url": "…",
            "price": "449.99", "currency": "USD", "target_price": "500.00" } }
```

`id` is the outbox id — retries reuse it, so dedupe on it. The exception is a **Send
test** delivery, which carries `event: "test"`, `id: 0` and an empty `data` object:
exclude `event: "test"` before keying on `id`, or your second test send will look
like a duplicate. Every request carries
`X-Snagr-Event`, `X-Snagr-Delivery` (the delivery id, or `test` for a test send),
`X-Snagr-Timestamp` (unix seconds), and `X-Snagr-Signature: sha256=<hex>` where

```
signature = HMAC_SHA256(secret, "{timestamp}." + raw_body_bytes)
```

The signing secret is server-generated and shown exactly once, in the create response
(rotation = delete and recreate). To verify: recompute over the exact bytes you received,
compare constant-time, and reject when `|now - timestamp| > 300s`. Ignore `event` values
you don't recognise — the set grows, and channels subscribed to all events pick up new
ones automatically. Delivery retries with backoff (30s / 5m / 30m / 2h, 5 attempts).

Destination URLs are user-supplied and POSTed without an IP blocklist — deliberate for a
self-hosted instance where every account belongs to the operator's household.

## Security posture

Snagr is built to live on a trusted LAN behind your own reverse proxy:

- The web app is the only thing meant to be exposed; put HTTPS in front of it and set `COOKIE_SECURE=true`.
- Auth tokens live in httpOnly cookies (JS never sees them); mutations require a CSRF header.
- Agents and scripts use **API tokens** instead (Settings → MCP & API): a `snagr_pat_…` bearer credential, stored hashed, scoped to read / write / runs, and never able to touch the account that owns it. Set `MCP_ENABLED=false` to turn that whole surface off.
- The Playwright MCP, vision sidecar, and MinIO are **LAN-internal and unauthenticated by design** — bind them to trusted interfaces only. The same goes for the SearXNG instance the agent queries. (The dev compose stack publishes the backend on `:8000` and the sidecar on `:8100` so host-run dev servers can reach them; drop those mappings, or bind them to `127.0.0.1`, for anything long-lived.)

Found a vulnerability? See [SECURITY.md](SECURITY.md).

## Contributing

Issues and PRs welcome — [CONTRIBUTING.md](CONTRIBUTING.md) covers the dev setup, the test contract, and the conventions CI enforces.

## License

[AGPL-3.0](LICENSE). Run it, change it, share it — if you host a modified Snagr for others, share your changes too.
