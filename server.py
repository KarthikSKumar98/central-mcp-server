import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.experimental.transforms.code_mode import CodeMode

import prompts
from config import DYNAMIC_TOOLS, MCP_HOST, MCP_PORT, MCP_TRANSPORT
from constants import API_CONCURRENCY_LIMIT
from services.central_service import get_conn, verify_connection
from tools import alerts, ap_monitoring, clients, devices, events, sites, wlans

_INSTRUCTIONS = (Path(__file__).parent / "INSTRUCTIONS.md").read_text()


@asynccontextmanager
async def lifespan(_server: FastMCP):
    conn = None
    try:
        conn = get_conn()
        verify_connection(conn)
    except Exception as e:
        raise RuntimeError(
            f"Failed to connect to Central: {e}\n"
            "Ensure credentials in .env are correct and the server is reachable."
        ) from e
    try:
        yield {"conn": conn, "api_semaphore": asyncio.Semaphore(API_CONCURRENCY_LIMIT)}
    finally:
        # Close any open connections or perform cleanup here if necessary
        if conn is not None:
            conn.close()


mcp = FastMCP(
    "Central MCP",
    lifespan=lifespan,
    instructions=_INSTRUCTIONS,
    transforms=(
        [CodeMode()] if DYNAMIC_TOOLS else []
    ),  # Enable code mode only when dynamic tools are enabled.
)

# Register tools with the MCP server
sites.register(mcp)
devices.register(mcp)
clients.register(mcp)
alerts.register(mcp)
events.register(mcp)
ap_monitoring.register(mcp)
wlans.register(mcp)

# Register prompts with the MCP server
prompts.register(mcp)


# Entry point for the installed CLI command: `central-mcp-server` (see pyproject.toml)
def run():
    if MCP_TRANSPORT == "stdio":
        mcp.run()
    else:
        mcp.run(transport=MCP_TRANSPORT, host=MCP_HOST, port=MCP_PORT)


# For local development, you can run this script directly with `python server.py` to start the MCP server.
if __name__ == "__main__":
    if MCP_TRANSPORT == "stdio":
        mcp.run()
    else:
        mcp.run(transport=MCP_TRANSPORT, host=MCP_HOST, port=MCP_PORT)
