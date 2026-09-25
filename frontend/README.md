# Snagr frontend

React 19 + Vite + TypeScript + Tailwind v4 + TanStack Query SPA for Snagr, a
self-hosted price-tracking app. Dark "night-hunt" UI: set a target price, let the hunter
work, watch it live, snag the deal. The price charts are hand-rolled SVG; Recharts draws
only the category change chart.

## Run it

The app talks to the real backend: dev requests to `/api` proxy to `http://localhost:8000`
(see `vite.config.ts`), so start the FastAPI server first.

```bash
npm install
npm run dev          # http://localhost:5173
```

### Mock mode (no backend needed)

A full mock API (MSW) seeded with a year of deterministic price history is still available —
run `VITE_USE_MOCKS=true npm run dev` (an inline value beats the file, and leaves the tracked
`.env.development` alone; setting it there works too). Sign in with
**demo@snagr.dev / snagr**. Press **Hunt now** on an item (or the hunt buttons on categories
and sites) to watch a scripted hunt stream into the Activity page and the panel; it writes a
real listing and price check into the mock store, so the dashboard updates when it finishes.
A demo check loop also runs for as long as a stream is open, one listing every ~20 s, which
is what fills the checks tail. Mock data resets on page reload; the session survives. `src/mocks/handlers.ts` doubles as the behavioral spec
(status codes + `error.code`) the backend is built against.

## Scripts

- `npm run dev` — dev server (proxies `/api` to `localhost:8000`)
- `npm run build` — type-check + production build to `dist/`
- `npm run lint` — oxlint (react / typescript / oxc plugins, see `.oxlintrc.json`)
- `npm test` — vitest over `src/**/*.test.ts` (pure logic, e.g. `features/items/rail.test.ts`)
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
├── main.tsx      boot: starts MSW only when VITE_USE_MOCKS is exactly 'true'
├── router.tsx    every route (old /runs links redirect to /activity)
├── api/          contract: types.ts (API mirror), client.ts (cookie auth + refresh), endpoints.ts, queries.ts (query keys)
├── mocks/        MSW handlers + seeded fixture store + the scripted SSE demo hunt and check loop
├── features/     auth, dashboard, categories, items, sites, activity (SSE provider + the Activity page, ticker and sheet), settings, vision (review queue + reference library)
├── components/   ui/ primitives, charts/ (theme, the shared SVG price plot, sparkline, tooltip, range selector), layout/ (shell, masthead)
├── lib/          money (decimal strings), time (ranges), cn, useMediaQuery
└── styles/       globals.css — all design tokens
```

`src/api/types.ts` **is** the API contract the backend must implement — the Pydantic
schemas in `backend/app/schemas/` mirror it field-for-field, and `src/mocks/handlers.ts`
is the behavioral oracle (status codes and `error.code`) the backend is built against.

## Design system — "Night Hunt"

`src/styles/globals.css` is the single token source (`src/components/charts/chartTheme.ts`
mirrors the chart hexes as JS literals because SVG attributes and Recharts props need literal
values, not CSS vars — change both together). Dark-only, by design.

- **Surfaces** are a green-cast night ramp: `page → well → surface → raised → overlay`
  (`well` is for inset grounds: search, terminal logs, list footers). Borders are always
  `hairline` / `hairline-strong`, never solid grays.
- **`lume`** (illuminated-reticle amber) is the identity color: active nav, primary buttons,
  focus, live states, "close to target". It is never semantic.
- **Semantics are unchanged and inverted vs finance**: `drop` green = price fell / target
  met = good; `rise` red = price rose. Every semantic color ships with a glyph
  (`▲▼✓✗⚠⌖○✚`) — never color alone. Green `⌖` always means "in range".
- **Type roles**: Big Shoulders Display (wordmark, page titles, verdicts, big prices — always
  letter-spaced), IBM Plex Sans (body), IBM Plex Mono + `tnum` (every numeral, timestamp,
  eyebrow, button label, log line).
- **Signature components**: the dashboard's verdict hero (`VerdictHero`) states the hunt in a
  sentence plus one line of tonight's totals — aggregates only, since per-item facts appear
  exactly once, in the watch table; `Radar` sweeps only while the hunter is working; `MeterToTarget`/`Ladder` draw distance to
  target (lume within 5%); `ListingsBoard` extends the ladder into one log-scale price rail
  per listing (range-high left → cheapest right, a ⌖ notch on each row, a labeled price
  ruler, drift marks from the chart's range; the scale math is `features/items/rail.ts`); `TerminalLog` is the one voice
  for agent/check logs; `Segmented` is the one segmented control.
- **Dialogs are field cards** (`components/ui/dialog.tsx`): `DialogHeader` (optional
  `DialogEyebrow`, title, description) → `DialogBody` → `DialogFooter`. Only the body
  scrolls, so the footer's buttons never leave the screen; under `sm` the card becomes a
  bottom sheet. A form wraps body and footer in `<form className="contents">` so both stay
  grid rows. Footer order is Back (`mr-auto`), Cancel, then the primary, always rightmost.
  Enter and exit are keyframe animations (`animate-dialog-in/out`, `animate-sheet-up/down`)
  because Radix waits for `animationend` before unmounting; keep a dialog mounted after
  close rather than rendering it conditionally, or the exit never plays. A two-step dialog
  shows `StepPips` in its eyebrow (a finished step is ✓ in ink-2, never drop-green).
- **Sites are picked, not typed**: every place a category's sites are chosen (New
  category, Edit sites, Edit category) uses `features/sites/SitePicker`, a checklist whose
  last row adds a site inline and picks it (`siteUrl.ts` normalizes the address and catches
  a host that's already listed). A category with no sites offers **Link sites** (warn) in
  place of Add item, and Add item always belongs to one category.
