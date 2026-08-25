# Contributing to Snagr

Thanks for considering it. This is a small project with strong conventions — most of them are enforced by CI, so this page is mainly about not being surprised.

## Dev setup

Each Python component (`backend/`, `agent/`, `vision/`) keeps its own virtualenv; always invoke tools through it:

```bash
cd backend && python -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/pytest
```

The frontend is plain npm (`npm install`, `npm run dev`), and runs against a full mock API by default — see [frontend/README.md](frontend/README.md).

## The test contract

- Backend and agent tests need a reachable **PostgreSQL with the pgvector extension**; vision tests too. Point `DATABASE_URL` (or `backend/.env`) at it.
- Suites never touch your data: `conftest.py` rewrites the URL's last path segment to a throwaway database (`snagr_test`, or `snagr_test_vision` for the vision suite) before importing anything, and asserts the rewrite changed the URL. Those test databases must exist on the server.
- Every behavior change lands with a test; bug fixes reproduce first with a failing test. Backend tests run against the real DB — don't mock the ORM.

## Style

- Python is settled by **ruff** (`./venv/bin/ruff check --fix && ./venv/bin/ruff format`); the frontend by **oxlint** + the TypeScript build (`npm run lint && npm run build`). CI runs all of it.
- Everything ruff can't see is settled by precedent: open the sibling file that does the same kind of job and copy its idioms. Boring and explicit beats clever.
- Python dependency pins are Dependabot-managed — don't hand-bump versions in a feature PR.

## PRs

- **PR titles are conventional commits** and linted: `feat|fix|refactor|test|docs|style|chore|ci|build|perf|revert`, scope free-form (`feat(backend): ...`). PRs are squash-merged with the title as the commit message, so the title is what history keeps.
- CI is path-gated per component: jobs for parts you didn't touch report "skipped", which is normal and satisfies the required checks.
- The API contract is defined by the frontend (`frontend/src/api/types.ts` + `frontend/src/mocks/handlers.ts`); the backend is built to match it, not the other way around.
