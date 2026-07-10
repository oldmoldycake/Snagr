"""SSE broadcaster — fan run_events out to every connected /api/events client (Phase 3, D3).

Responsibilities:
  - A process-wide hub of connected clients (asyncio.Queue per client).
  - listen_pg(): a background task that Postgres-LISTENs on 'snagr_run_events';
    on NOTIFY, loads the new run_events row(s) and broadcasts to all clients.
  - snapshot_for(client): on connect, send run.snapshot of active runs so a
    reconnecting client can backfill gaps (matches mocks/sse.ts addClient()).
  - encode(event, data, id): SSE wire format `event: <name>\\ndata: <json>\\n\\n`.

Simpler fallback if LISTEN/NOTIFY is troublesome: poll run_events WHERE
seq > last_sent every ~1s inside the per-client generator.
"""

# TODO: implement the hub described above.
