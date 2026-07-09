# Snagr frontend

React 19 + Vite + TypeScript + Tailwind v4 + Recharts + TanStack Query SPA for Snagr, a
self-hosted price-tracking app. Dark "deal-hunter" UI: set a target price, run the LLM agent,
watch it work live, snag the deal.

## Run it

The app talks to the real backend: dev requests to `/api` proxy to `http://localhost:8000`
(see `vite.config.ts`), so start the FastAPI server first.

```bash
npm install
npm run dev          # http://localhost:5173
```

### Mock mode (no backend needed)

A full mock API (MSW) seeded with a year of deterministic price history is still available —
set `VITE_USE_MOCKS=true` in `.env.development` and restart the dev server. Sign in with
**demo@snagr.dev / snagr**. Click **Run all** (or the run buttons on categories, sites, and
items) to watch a scripted agent run stream into the activity panel; it writes real price
checks into the mock store, so the dashboard updates when it finishes. Mock data resets on
page reload; the session survives. `src/mocks/handlers.ts` doubles as the behavioral spec
(status codes + `error.code`) the backend is built against.

## Scripts

- `npm run dev` — dev server (proxies `/api` to `localhost:8000`)
- `npm run build` — type-check + production build to `dist/`
- `npm run preview` — serve the production build locally
- `npx tsc -b` — type-check only

## Docker

```bash
docker build -t snagr-frontend .
```

Multi-stage build → nginx serving the SPA with `/api` proxied to a `backend:8000` service
(SSE-safe: buffering off, long read timeout). See `nginx.conf`.

## Structure

```
src/
├── api/          contract: types.ts (API mirror), client.ts (cookie auth + refresh), endpoints.ts, queries.ts (query keys)
├── mocks/        MSW handlers + seeded fixture store + scripted SSE demo run
├── features/     auth, dashboard, categories, items, sites, runs (SSE provider + activity sheet), settings
├── components/   ui/ primitives, charts/ (theme, sparkline, range selector), layout/ (shell, sidebar, topbar)
├── lib/          money (decimal strings), time (ranges), cn
└── styles/       globals.css — all design tokens
```

The API contract the backend must implement is documented in `../docs/BACKEND_REQUIREMENTS.md`;
`src/api/types.ts` is its TypeScript mirror. Keep them in sync.
