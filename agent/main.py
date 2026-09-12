"""Entry point for the price scraper job: sets up logging (scraper.log +
console) and runs the agent once over all watched items, recorded as a global
agent_runs row. With --consume it instead claims one API-enqueued run, or
fires a due run_schedules row when the queue is empty, and exits when there is
neither — cron it every minute so UI-triggered runs start promptly and
schedules fire on time. With --ground-only it only refreshes stale
market prices and exits — the near-instant path for newly added items, cheap
enough to cron every few minutes.

Every mode runs under _supervised, which turns SIGTERM and SIGINT into
cancellation of the job: a `docker stop` (or a Ctrl-C) unwinds it, and the
run driver writes the run's terminal state on the way out instead of leaving
the row 'running' for the reaper to find minutes later."""

import asyncio
import logging
import signal
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler(),
    ],
)

log = logging.getLogger(__name__)


def _supervised(job) -> None:
    """
    Run one job coroutine to completion, treating SIGTERM and SIGINT as
    "cancel the job": the task unwinds through every `finally`, and
    agent._drive's cancellation handler fails the run it was driving.
    Failures are logged, never raised — the ticker loop must outlive a bad
    pass, and the next tick happens regardless.
    """

    async def main() -> None:
        task = asyncio.current_task()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, task.cancel)
        await job

    try:
        asyncio.run(main())
    except asyncio.CancelledError, KeyboardInterrupt:
        log.warning("Stopped by signal")
    except Exception as e:
        log.error(f"Job failed: {e}")


if __name__ == "__main__":
    # Imported lazily per mode: agent.py asserts PLAYWRIGHT_MCP_URL at import,
    # and grounding needs no browser — --ground-only must run without one.
    if "--ground-only" in sys.argv:
        from pricing import ground_stale

        log.info("Market grounding job started.....")
        _supervised(ground_stale())
        log.info("Market grounding job finished")
    elif "--consume" in sys.argv:
        from agent import consume

        log.info("Run-queue consumer tick started.....")
        _supervised(consume())
        log.info("Run-queue consumer tick finished")
    else:
        from agent import run

        log.info("Price scraper job started.....")
        _supervised(run())
        log.info("Price Scraper job finished")
