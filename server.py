from contextlib import asynccontextmanager
from pathlib import Path
from fastmcp import FastMCP
from fastmcp.experimental.transforms.code_mode import CodeMode
from services.central_service import get_conn
from tools import sites, devices, clients, alerts, prompts, events

_INSTRUCTIONS = (Path(__file__).parent / "INSTRUCTIONS.md").read_text()


@asynccontextmanager
async def lifespan(_server: FastMCP):
    conn = get_conn()
    try:
        yield {"conn": conn}
    finally:
        pass  # NewCentralBase has no explicit close; placeholder for future cleanup


mcp = FastMCP(
    "Central MCP",
    lifespan=lifespan,
    instructions=_INSTRUCTIONS,
    transforms=[CodeMode()],
)

sites.register(mcp)
devices.register(mcp)
clients.register(mcp)
alerts.register(mcp)
prompts.register(mcp)
events.register(mcp)


def run():
    mcp.run()


if __name__ == "__main__":
    mcp.run()
    # mcp.run(transport="sse", host="127.0.0.1", port=8001)

# Test
# uv run pytest tests/ -v

# Tool Test
# python -m watchfiles --filter python "python server.py" .
