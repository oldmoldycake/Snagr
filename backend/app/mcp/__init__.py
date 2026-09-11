"""The MCP layer — Snagr as tools for agents (BACKEND_REQUIREMENTS §11).

server.py owns the FastMCP instance, the bearer verifier and the app factory
main.py registers at POST /api/mcp; tools/<section>.py registers the tools,
one module per section of endpoints.ts, each calling the same services the
routers do so an agent sees exactly what the UI sees.
"""
