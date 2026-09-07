import asyncio

import pytest
from fastmcp import Client as FastMCPClient, FastMCP

from models import (
    Alert,
    AlertEnvelope,
    Client,
    ClientEnvelope,
    Device,
    DeviceEnvelope,
    DeviceTrendsEnvelope,
    Event,
    EventEnvelope,
    GatewayCluster,
    GatewayClusterEnvelope,
    SiteData,
    SiteEnvelope,
    SiteMetrics,
    TrendSample,
    WLAN,
    WlanEnvelope,
)
from tools import alerts, clients, devices, events, gateway_monitoring, sites, wlans
from utils.envelope import build_envelope


ENVELOPE_TOOLS = {
    "central_get_devices",
    "central_get_device_trends",
    "central_get_clients",
    "central_get_sites",
    "central_get_wlans",
    "central_get_gateway_cluster",
    "central_get_events",
    "central_get_alerts",
}


def _registered_tools():
    mcp = FastMCP("response-format-schema")
    for module in (alerts, clients, devices, events, gateway_monitoring, sites, wlans):
        module.register(mcp)
    return asyncio.run(mcp.list_tools(run_middleware=False))


def test_every_envelope_tool_declares_response_format_enum_and_default() -> None:
    tools_by_name = {tool.name: tool for tool in _registered_tools()}
    assert ENVELOPE_TOOLS <= tools_by_name.keys()
    for name in ENVELOPE_TOOLS:
        schema = tools_by_name[name].parameters["properties"]["response_format"]
        assert schema["enum"] == ["concise", "detailed"]
        assert schema["default"] == "concise"


CASES = [
    (DeviceEnvelope, Device, "part_number", {"serial_number", "mac_address", "device_type", "status", "site_id"}),
    (DeviceTrendsEnvelope, TrendSample, None, {"timestamp"}),
    (
        ClientEnvelope,
        Client,
        "hostname",
        {"mac", "status", "site_id", "ipv4", "user_name"},
    ),
    (SiteEnvelope, SiteData, "location", {"site_id"}),
    (WlanEnvelope, WLAN, None, {"wlan_name", "status"}),
    (GatewayClusterEnvelope, GatewayCluster, "capacity", {"cluster_name"}),
    (
        EventEnvelope,
        Event,
        "attributes",
        {"event_id", "event_identifier", "serial_number", "source_type", "description"},
    ),
    (AlertEnvelope, Alert, "updated_by", {"device_type", "status"}),
]


@pytest.mark.parametrize("envelope_cls,item_cls,dropped,identifiers", CASES)
def test_concise_projection_is_visible_and_preserves_identifiers(
    envelope_cls, item_cls, dropped, identifiers
) -> None:
    values = {field: f"value-{field}" for field in identifiers}
    if dropped is not None:
        values[dropped] = [] if dropped in {"attributes", "capacity"} else f"value-{dropped}"
    if item_cls is SiteData:
        values["location"] = {}
        values["name"] = "HQ"
        values["metrics"] = SiteMetrics()
    if item_cls is Event:
        from models import SourceType

        values["source_type"] = SourceType.SWITCH
    item = item_cls.model_construct(**values)
    concise = build_envelope(envelope_cls, [item], response_format="concise").model_dump()
    detailed = build_envelope(envelope_cls, [item], response_format="detailed").model_dump()

    concise_keys = set(concise["items"][0])
    detailed_keys = set(detailed["items"][0])
    assert concise["meta"]["response_format"] == "concise"
    assert detailed["meta"]["response_format"] == "detailed"
    assert concise_keys <= detailed_keys
    assert identifiers <= concise_keys
    if dropped is None:
        assert "omitted_fields" not in concise["meta"]
    else:
        assert dropped not in concise_keys
        assert dropped in concise["meta"]["omitted_fields"]


@pytest.mark.asyncio
async def test_fastmcp_client_serializes_concise_items_without_omitted_keys() -> None:
    mcp = FastMCP("response-format-client")

    @mcp.tool
    async def projected_devices() -> DeviceEnvelope:
        item = Device.model_construct(
            serial_number="SERIAL-1",
            mac_address="00:11:22:33:44:55",
            device_type="SWITCH",
            model="6300M",
            name="edge-1",
            status="ONLINE",
            site_id="site-1",
            site_name="HQ",
            part_number="verbose-part",
        )
        return build_envelope(DeviceEnvelope, [item], response_format="concise")

    async with FastMCPClient(mcp) as client:
        result = await client.call_tool("projected_devices")

    item = result.structured_content["items"][0]
    assert "part_number" not in item
    assert result.structured_content["meta"]["omitted_fields"] == ["part_number"]
