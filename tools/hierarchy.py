import asyncio

from fastmcp import Context, FastMCP

from models import NetworkHierarchy
from tools import READ_ONLY
from utils.common import api_context, format_tool_error
from utils.hierarchy import build_hierarchy


def register(mcp: FastMCP) -> None:
    """Register network hierarchy tools with the MCP server."""

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_network_hierarchy(
        ctx: Context,
        site_names: list[str] | None = None,
    ) -> NetworkHierarchy | str:
        """Return the network as a nested hierarchy tree ready for Mermaid or Excalidraw rendering.

        The hierarchy is strictly vertical: Global → Site Collection → Site → Device.
        Every node has exactly one parent — no node is attached to more than one
        level, and no level is skipped. Site Collections are omitted when none are
        configured in Central, collapsing the structure to Global → Site → Device,
        but the vertical ordering is always preserved.

        Device Groups exist in Central but are intentionally excluded. They represent
        a horizontal grouping (devices across sites sharing a config policy) rather
        than a vertical parent-child relationship, so they do not belong in this
        topology tree.

        Use this tool when the user wants to visualize, diagram, or explore the
        overall network topology. Pass the result directly to a Mermaid or
        Excalidraw MCP tool to produce a diagram.

        Parameters
        ----------
        - site_names: Optional list of exact site names to include. When provided,
          only matching sites and their devices appear in the tree, and empty
          collections are pruned. Omit to return the full global hierarchy.

        """
        async with api_context(ctx) as conn:
            try:
                return await asyncio.to_thread(build_hierarchy, conn, site_names)
            except Exception as e:
                return format_tool_error("fetching network hierarchy", e)
