# Security Policy

## Supported versions

Security fixes land on `main` and ship in the latest release only — there are no backports.

## Reporting a vulnerability

Please report vulnerabilities privately via GitHub: **Security → Report a vulnerability** on this repository. Don't open a public issue for anything exploitable.

You can expect an acknowledgement within a few days. Please include enough detail to reproduce the problem — affected component (`backend/`, `frontend/`, `agent/`, `vision/`), a proof of concept if you have one, and the impact as you understand it.

## Deployment posture (what's in scope)

Snagr is designed for a trusted LAN with a reverse proxy in front of the web app:

- Only the frontend (which proxies `/api`) is meant to be exposed; everything else stays internal.
- The Playwright MCP, vision sidecar, and MinIO are **unauthenticated by design** and must never be reachable from untrusted networks. Reports that amount to "these services have no auth" are working as documented; reports that they're reachable in ways the docs say they shouldn't be, or that the trust boundary can be crossed from the exposed surface, are very much in scope.
