---
name: verify
description: Build, launch, and drive the Snagr frontend to verify changes at the browser surface
---

# Verifying the Snagr frontend

## Build

```bash
cd frontend && npm run build   # tsc -b + vite build; fails on type errors
```

## Launch (dev)

```bash
cd frontend && npm run dev -- --port 5174 --strictPort   # 5173 is often taken by ANOTHER project's Vite app
```

- `/api` proxies to `http://localhost:8000` (vite.config.ts). Host port 8000 may be held by the
  `kitty_krib_backend` docker container, not the Snagr backend — a 502 from the proxy usually means
  the wrong/no upstream, not a frontend bug.
- Mock mode: `VITE_USE_MOCKS=true npm run dev -- --port 5175 --strictPort` (env var beats
  `.env.development`). Sign in demo@snagr.dev / snagr. Mock on = MSW service worker registered +
  `[snagr] Mock API enabled` in console.

## Drive

The Playwright MCP wants branded Chrome (`/opt/google/chrome/chrome`), which isn't installed.
Use playwright-core from the npx cache with the cached chromium instead:

- playwright-core: `~/.npm/_npx/9833c18b2d85bc59/node_modules/playwright-core/index.mjs`
- chromium: `~/.cache/ms-playwright/chromium-1223/chrome-linux64/chrome` (pass as `executablePath`)

Script pattern: launch headless, `page.on('console')` + `page.on('response')` for `/api/` URLs,
`navigator.serviceWorker.getRegistrations()` to detect MSW, screenshot, dump `document.body.innerText`.
Unauthenticated visits redirect to `/login`.

## Gotchas

- Run browser scripts with sandbox disabled — the sandbox resets localhost connections.
- Kill background dev servers when done (TaskStop).
