"""Run lifecycle — enqueue, scope resolution, status transitions (Phase 3, D3).

Responsibilities:
  - resolve_scope(scope, scope_id): validate the target exists (404) and build
    the human scope_label ("Everything" / "Category: X" / "Site: Y" / "Item: Z").
  - enqueue_run(): 409 run_in_progress (with error.run_id) if a run is already
    queued/running; else insert agent_runs row status='queued' and NOTIFY.
  - cancel_run(): mark cancelled, emit the run.finished event.
  - list_runs()/get_run(): read history.

The agent (agent/*.py) is the CONSUMER: it claims queued rows
(SELECT ... FOR UPDATE SKIP LOCKED), runs, and writes run_events + updates
status/stats/last_seq. This module only produces/queries rows.
"""

# TODO: implement the functions described above.
