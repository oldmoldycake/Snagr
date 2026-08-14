"""Entry point for the price scraper job: sets up logging (scraper.log +
console) and runs the agent once over all watched items. With --ground-only
it only refreshes stale market prices and exits — the near-instant path for
newly added items, cheap enough to cron every few minutes."""

import asyncio
import logging
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

if __name__ == "__main__":
    # Imported lazily per mode: agent.py asserts PLAYWRIGHT_MCP_URL at import,
    # and grounding needs no browser — --ground-only must run without one.
    if "--ground-only" in sys.argv:
        from pricing import ground_stale

        log.info("Market grounding job started.....")
        try:
            asyncio.run(ground_stale())
        except Exception as e:
            log.error(f"Job failed: {e}")
        log.info("Market grounding job finished")
    else:
        from agent import run

        log.info("Price scraper job started.....")
        try:
            asyncio.run(run())
        except Exception as e:
            log.error(f"Job failed: {e}")
        log.info("Price Scraper job finished")
