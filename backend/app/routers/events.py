"""Server-Sent Events stream — GET /api/events  (Phase 3).

NOT in endpoints.ts: the frontend opens this directly via
`new EventSource('/api/events')` in features/runs/RunEventsProvider.tsx.

Wire format (match mocks/sse.ts exactly):
    on connect  -> event: run.snapshot   {active_runs: [...]}
    per event   -> event: run.event      RunEvent    (id: "<run_id>:<seq>")
    lifecycle   -> event: run.started / run.finished  {run: AgentRun}

Backed by services/events.py (Postgres LISTEN/NOTIFY hub, D3). nginx.conf
already disables buffering + extends timeouts for this path.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["events"])

# TODO: implement the SSE endpoint (sse-starlette EventSourceResponse).
