import logging, os
from langchain_ollama import ChatOllama
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from config import OLLAMA_MODEL, OLLAMA_URL, PLAYWRIGHT_MCP_URL
from tools import save_listing, save_price_check
from database import get_watched_item_list

log = logging.getLogger(__name__)

assert PLAYWRIGHT_MCP_URL is not None, "PLAYWRIGHT_MCP_URL not set"
llm = ChatOllama(
    model=OLLAMA_MODEL,
    base_url=OLLAMA_URL
)
async def run():
    client = MultiServerMCPClient({
        "playwright": {
            "url": PLAYWRIGHT_MCP_URL,
            "transport": "streamable_http",
        }
    })

    tools = await client.get_tools()  # ← now async
    tools = tools + [save_price_check, save_listing]

    agent = create_react_agent(llm, tools)

    site_item_list = await get_watched_item_list()

    for site_id, site_name, item_id, item_name in site_item_list:
        log.info(f"Starting search for {item_id}, {item_name}, on site {site_id}, {site_name}")
