"""Entry point for the hunter: sets up logging (scraper.log + console) and
runs the daemon, or one drain of the queue.

    --serve   run until stopped, claiming work as it appears (compose)
    --once    queue what is due, drain the queue until empty, exit (cron)

There is no bare mode. A typo used to start a full sweep of everything,
silently and expensively; argparse now prints the usage and exits 2.

Both modes run under _supervised, which turns SIGTERM and SIGINT into
cancellation: a `docker stop` (or a Ctrl-C) unwinds the pools and hands every
in-flight job back to the queue on the way out, so nothing is lost and nothing
waits for the reaper."""

import argparse
import asyncio
import logging
import signal

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
    Run one coroutine to completion, treating SIGTERM and SIGINT as "stop":
    the task unwinds through every `finally`, which is where the pools return
    what they were holding. Failures are logged, never raised — under compose
    this process is the hunter, and it should come back rather than die on a
    bad pass.
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
        log.error(f"Hunter stopped: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Snagr's hunter — the agent that works the queue.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--serve", action="store_true", help="run until stopped (the daemon)")
    mode.add_argument("--once", action="store_true", help="drain the queue once and exit (cron)")
    args = parser.parse_args()

    # imported here so --once and --serve both pay the import cost only after
    # the arguments have been accepted
    from worker import once, serve

    if args.serve:
        log.info("Hunter starting.....")
        _supervised(serve())
        log.info("Hunter stopped")
    else:
        log.info("Draining the queue.....")
        _supervised(once())
        log.info("Queue drained")
