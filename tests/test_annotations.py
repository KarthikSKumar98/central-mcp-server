import asyncio

from fastmcp import FastMCP

from tools import (
    DESTRUCTIVE,
    DIAGNOSTIC,
    READ_ONLY,
    alerts,
    clients,
    devices,
    events,
    gateway_monitoring,
    sites,
    troubleshooting,
    wlans,
)

READ_ONLY_TOOLS = {
    "central_get_devices",
    "central_get_device_details",
    "central_get_device_trends",
    "central_get_clients",
    "central_get_sites",
    "central_get_wlans",
    "central_get_gateway_cluster",
    "central_get_events",
    "central_get_alerts",
}

DIAGNOSTIC_TOOLS = {
    "central_run_network_test",
    "central_run_show_commands",
}

DESTRUCTIVE_TOOLS = {"central_bounce_port"}


def _registered_tools() -> dict[str, object]:
    mcp = FastMCP("annotation-snapshot")
    for module in (
        sites,
        devices,
        clients,
        alerts,
        events,
        gateway_monitoring,
        wlans,
        troubleshooting,
    ):
        module.register(mcp)
    return {
        tool.name: tool
        for tool in asyncio.run(mcp.list_tools(run_middleware=False))
    }


def test_registered_tool_annotations_match_snapshot() -> None:
    """Every survivor keeps its locked annotation-class hint values."""
    tools = _registered_tools()
    expected = {
        **{name: READ_ONLY for name in READ_ONLY_TOOLS},
        **{name: DIAGNOSTIC for name in DIAGNOSTIC_TOOLS},
        **{name: DESTRUCTIVE for name in DESTRUCTIVE_TOOLS},
    }

    assert set(tools) == set(expected)
    for name, annotations in expected.items():
        actual = tools[name].annotations
        assert actual.model_dump() == annotations.model_dump(), name
        assert actual.readOnlyHint == annotations.readOnlyHint, name
        assert actual.destructiveHint == annotations.destructiveHint, name
        assert actual.openWorldHint == annotations.openWorldHint, name
