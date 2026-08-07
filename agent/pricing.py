import requests
import json
import logging
import asyncio
from database import get_watched_item_list

log = logging.getLogger(__name__)
async def search_sear_xng(query, base_url = "http://localhost:8888"):
    try:
        logging.info("Searching SearXNG.....")
        params = {"q": query, "format": json}
        response = requests.get(f"{base_url}/search", params=params, timeout=10)
        response.raise_for_status()
        return response.json
    except Exception as e:
        logging.error(f"Error searching SearXNG: {e}")

async def parse_sear_xng_results(sear_xng_results):
    pass




async def main():
    await get_watched_item_list()

if __name__ == "__main__":
    asyncio.run(main())
