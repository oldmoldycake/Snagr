
import os
from dotenv import load_dotenv

load_dotenv()
#AI 
OLLAMA_URL = os.getenv("OLLAMA_URL","http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_URL","qwen3.6:34b")

#MCP
PLAYWRIGHT_MCP_URL = os.getenv("PLAYWRIGHT_MCP_URL")
    
