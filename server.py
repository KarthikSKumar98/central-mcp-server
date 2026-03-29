from contextlib import asynccontextmanager
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.experimental.transforms.code_mode import CodeMode

from services.central_service import get_conn, verify_connection
from tools import alerts, clients, devices, events, sites

from . import prompts

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
        yield {"conn": conn}
    finally:
        # Close any open connections or perform cleanup here if necessary
        if conn is not None:
            conn.close()


mcp = FastMCP(
    "Central MCP",
    lifespan=lifespan,
    instructions=_INSTRUCTIONS,
    transforms=[CodeMode()],
)

# Register tools with the MCP server
sites.register(mcp)
devices.register(mcp)
clients.register(mcp)
alerts.register(mcp)
events.register(mcp)

# Register prompts with the MCP server
prompts.register(mcp)

# Entry point for the installed CLI command: `central-mcp-server` (see pyproject.toml)
def run():
    mcp.run()

# For local development, you can run this script directly with `python server.py` to start the MCP server.
if __name__ == "__main__":
    mcp.run()

    # For local development with sse, use the following command:
    # mcp.run(transport="sse", host="127.0.0.1", port=8001)
