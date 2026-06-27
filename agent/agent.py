import logging, os
from langchain_ollama import ChatOllama
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from config import OLLAMA_MODEL, OLLAMA_URL, PLAYWRIGHT_MCP_URL
llm = ChatOllama(
    model=OLLAMA_MODEL,
    base_url=OLLAMA_URL
)

async def run(): 


    async with MultiServerMCPClient({
        "playwright": {
            "url": PLAYWRIGHT_MCP_URL,
            "transport": "streamable_http"
        }
    }) as client:
        
        tools = client.get_tools()

