import requests
import json
import logging
import asyncio
import os
from database import get_watched_item_list

SEARCH_URL = os.getenv("SEAR_XNG_URL") 
log = logging.getLogger(__name__)
queries = ["What is a {} worth", "How much does {} sell for", "{} estimated value" ]



async def search_sear_xng_queries(base_url = "http://localhost:8888"):
    try:
        searches = []
        for query in queries:
            logging.info("Searching SearXNG.....")
            params = {"q": query, "format": json}
            response = requests.get(f"{base_url}/search", params=params, timeout=10)
            response.raise_for_status()
            print(response.json)
            searches.append(response.json)
        return searches
    except Exception as e:
        logging.error(f"Error searching SearXNG: {e}")

async def parse_sear_xng_results(sear_xng_results):
    pass




async def main():
    await get_watched_item_list()
    searches = await search_sear_xng_queries(SEARCH_URL)
if __name__ == "__main__":
    asyncio.run(main())
