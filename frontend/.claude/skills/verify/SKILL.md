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
Use playwright-core from the npx cache with the cached chromium instead. Both paths move
when npx or Playwright updates, so look them up rather than trusting a hash:

- playwright-core: `ls -d ~/.npm/_npx/*/node_modules/playwright-core` → import its `index.mjs`
  (as of 2026-09-23: `~/.npm/_npx/361ceb562f3b3235/…`, v1.61.1)
- chromium: the revision that playwright-core's `browsers.json` names for `chromium`, under
  `~/.cache/ms-playwright/chromium-<rev>/chrome-linux64/chrome` (pass as `executablePath`;
  1.61.1 wants `chromium-1228`)

Script pattern: launch headless, `page.on('console')` + `page.on('response')` for `/api/` URLs,
`navigator.serviceWorker.getRegistrations()` to detect MSW, screenshot, dump `document.body.innerText`.
Unauthenticated visits redirect to `/login`.

## Gotchas

- Run browser scripts with sandbox disabled — the sandbox resets localhost connections.
- Kill background dev servers when done (TaskStop).
