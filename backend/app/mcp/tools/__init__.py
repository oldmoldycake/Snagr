"""Tool registration — one module per section of endpoints.ts. Each module's
register() defines its tools on the shared server; docstrings are the prompt
the agent reads, held to the same bar as agent/tools.py."""

from fastmcp import FastMCP

from app.mcp.tools import catalog, charts, instance, items, jobs, vision


def register(mcp: FastMCP) -> None:
    """Register every section's tools on the server."""
    for module in (instance, catalog, items, charts, jobs, vision):
        module.register(mcp)
