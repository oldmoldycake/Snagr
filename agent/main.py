"""Entry point for the price scraper job: sets up logging (scraper.log +
console) and runs the agent once over all watched items."""

import asyncio
import logging
from agent import run



logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler(),
    ]
)

log = logging.getLogger(__name__)

if __name__ == "__main__":
    log.info("Price scraper job started.....")

    try:
        asyncio.run(run())
    except Exception as e:
        log.error(f"Job failed: {e}")
    log.info("Price Scraper job finished")



