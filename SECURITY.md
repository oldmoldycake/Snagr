# Security Policy

## Supported versions

Security fixes land on `main` and ship in the next release; only the latest release is supported — there are no backports. The `:dev` images track the tip of `main` and pick up fixes first.

## Reporting a vulnerability

Please report vulnerabilities privately via GitHub: **Security → Report a vulnerability** on this repository. Don't open a public issue for anything exploitable.

You can expect an acknowledgement within a few days. Please include enough detail to reproduce the problem — affected component (`backend/`, `frontend/`, `agent/`, `vision/`), a proof of concept if you have one, and the impact as you understand it.

## Deployment posture (what's in scope)

Snagr is designed for a trusted LAN with a reverse proxy in front of the web app:

- Only the frontend (which proxies `/api`) is meant to be exposed; everything else stays internal. The dev `docker-compose.yml` additionally publishes the API on `:8000` and the vision sidecar on `:8100` for host-side development — neither should be published in a real deployment.
- Credentials: httpOnly cookie sessions (`snagr_access` JWT + a rotating DB-backed `snagr_refresh`), CSRF-header-guarded mutations, and `snagr_pat_…` API tokens (sha256 at rest, scoped read / write / jobs, barred from `/api/auth/me`, `/api/me/*` and `/api/admin/*`). Bugs that cross any of those boundaries are in scope. `MCP_ENABLED=false` disables bearer-token authentication and leaves `/api/mcp` unregistered; the token-management routes remain, but the tokens they mint authenticate nothing.
- The Playwright MCP, the SearXNG instance, the vision sidecar, and MinIO are **unauthenticated by design** and must never be reachable from untrusted networks. Reports that amount to "these services have no auth" are working as documented; reports that they're reachable in ways the docs say they shouldn't be, or that the trust boundary can be crossed from the exposed surface, are very much in scope.
