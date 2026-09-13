# Snagr — Agent Instructions

Snagr is a self-hosted price tracker: four independently-deployed components
(`agent/`, `backend/`, `frontend/`, `vision/`) sharing one Postgres database.

The working guide for this repo is **[CLAUDE.md](CLAUDE.md)** — architecture,
commands, the cross-cutting invariants, and the house rules for writing code
here. Read it first; it is the file kept current.

Then, per area:

- [`backend/STRUCTURE.md`](backend/STRUCTURE.md) — every backend file's job, the
  layer model, and the endpoint→file lookup.
- [`frontend/README.md`](frontend/README.md) — scripts, mock mode, structure, and
  the design system.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup, the test contract, and the
  conventions CI enforces.

The API contract is defined by the frontend, and the backend is built to match
it: `frontend/src/api/endpoints.ts` (routes), `types.ts` (request/response
shapes), `src/mocks/handlers.ts` (status codes and `error.code`).
