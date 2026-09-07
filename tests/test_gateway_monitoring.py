"""Tests for tools/gateway_monitoring.py."""

import json
from unittest.mock import patch

import pytest
from fastmcp.exceptions import ToolError

import tools.devices as devices_mod
import tools.gateway_monitoring as mod
from constants import GATEWAY_MAX_PAGE_SIZE
from models import (
    CapacityTrendSample,
    DeviceEnvelope,
    DeviceTrendsEnvelope,
    GatewayCluster,
    GatewayClusterEnvelope,
    GatewayDetail,
    GatewayDHCPLease,
    GatewayDHCPPool,
    GatewayUplink,
    TrendSample,
)
from tests.conftest import FakeMCP, make_ctx
from utils.cursor import decode_cursor, encode_cursor, hash_query

# ---------------------------------------------------------------------------
# Shared realistic payloads (from a20-gateway-monitoring-payloads.md)
# ---------------------------------------------------------------------------

RAW_GATEWAY = {
    "macAddress": "00:1a:1e:06:55:70",
    "ipAddress": "10.97.55.248",
    "macRange": "00:1a:1e:06:55:70-00:1a:1e:06:55:77",
    "rebootReason": "Power Cycle (Intent:cause:register ee:ee:0:1)",
    "mode": None,
    "cpuUtilization": 3,
    "memoryUtilization": 21,
    "model": "A7240XM",
    "type": "network-monitoring/gateway-monitoring",
    "deviceFunction": "Unspecified",
    "id": "DL0006948",
    "clusterName": "auto_group_168",
    "role": "Member",
    "serialNumber": "DL0006948",
    "uptimeInMillis": 4688743000,
    "siteName": "Bengaluru (BLR) - Branch",
    "firmwareVersion": "10.5.0.0_87691",
    "siteId": "62201157617",
    "status": "Online",
    "deviceName": "BO-BLR-GTW01",
}

RAW_PORT = {
    "healthReasons": [],
    "mtu": "1500 bytes",
    "macAddress": "00:1a:1e:06:55:71",
    "speed": "1000",
    "throughput": {"received": 37332, "sent": 27630},
    "totalPackets": 211815,
    "broadcastPackets": 32451,
    "multicastPackets": 4893,
    "crcErrors": 0,
    "collisions": 0,
    "runts": 0,
    "giants": 0,
    "adminState": "Enabled",
    "operState": "Up",
    "health": "Good",
    "portType": "Access",
    "connectorType": "",
    "usage": {"total": 29233345, "received": 16799802, "sent": 12433543},
    "type": "network-monitoring/gateway-monitoring",
    "id": "DL0006948/ports/GE 0/0/0",
    "name": "GE 0/0/0",
    "portNumber": "0",
    "duplex": "Full",
    "vlan": "1330",
}

RAW_TUNNEL = {
    "destinationIpAddress": "10.97.55.180",
    "type": "network-monitoring/gateway-monitoring",
    "vni": "",
    "uptime": "1M 24d",
    "mtu": "1450",
    "tunnelName": "BO-BLR-GTW01:inet::BO-BLR-AP04:inet",
    "tunnelType": "LAN",
    "authentication": "SHA-2 256",
    "lastConnected": "Apr 12, 2026 15:50",
    "id": "DL0006948/tunnels/BO-BLR-GTW01:inet::BO-BLR-AP04:inet",
    "greTunnelId": "",
    "greTunnelIpAddress": "",
    "mode": "Orchestrated",
    "uplinkName": "",
    "inSpi": "2790042368",
    "macAddress": "00:1a:1e:06:55:70",
    "outSpi": "222096128",
    "nextReKey": 1780739997,
    "peerType": "AP",
    "natEnabled": "Enabled",
    "health": "Good",
    "lastDownReason": "NA",
    "vlanId": 1330,
    "droppedPackets": 0,
    "throughput": {"received": 0, "sent": 0},
    "usage": {"total": 0, "received": 0, "sent": 0},
    "healthReasons": [],
    "encryption": "AES-256",
    "gateway": "BO-BLR-GTW01",
    "encapsulation": "IPsec",
    "status": "Up",
    "sourceIpAddress": "10.97.55.248",
}

RAW_VLAN = {
    "ipv4Subnet": "10.97.55.248/24",
    "ipv4MaskAddr": "255.255.255.0",
    "ipv4": "10.97.55.248",
    "type": "network-monitoring/gateway-monitoring",
    "id": "DL0006948/vlans/1330",
    "interfaces": "GE 0/0/0",
    "name": "",
    "vlanId": 1330,
    "vlanType": "Static",
    "status": "Up",
    "adminStatus": "Up",
}

RAW_UPLINK = {
    "linkTag": "uplink-0",
    "name": "WAN-1",
    "status": "Up",
    "uplinkType": "wired",
    "ipAddress": "203.0.113.1",
    "gateway": "BO-BLR-GTW01",
}

RAW_DHCP_POOL = {
    "poolName": "pool-1",
    "vlanId": 33,
    "vlanName": "Client-Vlan 1",
    "subnet": "192.168.3.0/24",
    "leaseDuration": 90061,
    "poolSize": 100,
    "currentLeases": 4,
    "utilization": 4,
    "availableAddresses": 96,
}

RAW_DHCP_LEASE = {
    "poolName": "pool-1",
    "ipAddress": "192.168.3.4",
    "macAddress": "70:cd:0d:0b:40:d2",
    "clientSiteId": "12345",
    "clientSerial": "CG0021253",
    "infraType": None,
    "hostName": "pc76",
    "clientDeviceType": "MSFT 5.0",
    "startTime": 1756136958062,
    "expirationTime": 1756137138062,
    "remainingTime": "172800",
    "reservation": "No",
}

RAW_CLUSTER_MEMBER = {
    "macAddress": "00:1a:1e:06:55:70",
    "siteName": "Bengaluru (BLR) - Branch",
    "id": "auto_group_168/members/DL0006948",
    "type": "network-monitoring/gateway-monitoring",
    "partNumber": "",
    "model": "A7240XM",
    "ipv6": "",
    "softwareVersion": "10.7.2.1_93286",
    "clusterName": "auto_group_168",
    "firmwareVersion": "10.7.2.1_93286",
    "lastSeenAt": None,
    "serialNumber": "DL0006948",
    "ipv4": "10.97.55.248",
    "role": "Member",
    "siteId": "62201157617",
    "status": "ONLINE",
    "deviceName": "BO-BLR-GTW01",
}

RAW_TUNNEL_HEALTH_SUMMARY = [
    {
        "serialNumber": "DL0006948",
        "id": "auto_group_168/DL0006948/tunnels",
        "type": "network-monitoring/gateway-monitoring",
        "siteId": "62201157617",
        "deviceName": "BO-BLR-GTW01",
        "tunnelHealth": {"good": 2, "fair": 0, "poor": 0},
    }
]

# Cluster snapshot as returned by fetch_cluster_snapshot
RAW_CLUSTER_SNAPSHOT = {
    "cluster_name": "auto_group_168",
    "members": [RAW_CLUSTER_MEMBER],
    "tunnel_health_summary": RAW_TUNNEL_HEALTH_SUMMARY,
}

# Raw hardware-temperature response (list of sensor dicts)
RAW_TEMPERATURE_LIST = [
    {
        "type": "network-monitoring/gateway-monitoring",
        "graph": {
            "samples": [{"data": [42], "timestamp": "2026-06-05T19:05:00Z"}],
            "keys": ["CPU"],
        },
        "id": "DL0006948",
        "metric": "temperature",
    },
    {
        "type": "network-monitoring/gateway-monitoring",
        "graph": {
            "samples": [{"data": [30], "timestamp": "2026-06-05T19:05:00Z"}],
            "keys": ["Ambient"],
        },
        "id": "DL0006948",
        "metric": "temperature",
    },
]

# Normalized capacity trends (return_raw_response=True shape)
RAW_CAPACITY_TRENDS = [
    {
        "type": "network-monitoring/gateway-monitoring",
        "graph": {
            "samples": [
                {"data": [0, 0, 65536, 0, 0], "timestamp": "2026-06-05T19:00:00Z"}
            ],
            "keys": [
                "active_client_count",
                "standby_client_count",
                "cluster_client_max_capacity",
                "active_client_percentage",
                "standby_client_percentage",
            ],
        },
        "id": "auto_group_168",
        "capacityType": "client_capacity",
    },
    {
        "type": "network-monitoring/gateway-monitoring",
        "graph": {
            "samples": [
                {
                    "data": [1, 1, 0, 0, 0.01, 0.01, 0, 0, 16384],
                    "timestamp": "2026-06-05T19:00:00Z",
                }
            ],
            "keys": [
                "active_ap_count",
                "standby_ap_count",
                "active_sw_count",
                "standby_sw_count",
                "active_ap_percentage",
                "standby_ap_percentage",
                "active_sw_percentage",
                "standby_sw_percentage",
                "cluster_device_max_capacity",
            ],
        },
        "id": "auto_group_168",
        "capacityType": "device_capacity",
    },
]


def gateway_page(
    items: list[dict] | None = None,
    *,
    total: int | None = None,
    next_cursor: str | None = None,
) -> dict:
    page_items = items or []
    return {
        "items": page_items,
        "count": len(page_items),
        "total": len(page_items) if total is None else total,
        "next": next_cursor,
    }


def device_family_query_hash(device_type: str) -> str:
    return hash_query(
        {
            "device_type": device_type,
            "site_id": None,
            "site_name": None,
            "device_name": None,
            "serial_number": None,
            "device_status": None,
            "model": None,
            "device_function": None,
            "is_provisioned": None,
            "site_assigned": None,
            "firmware_version": None,
            "deployment": None,
            "cluster_id": None,
            "cluster_name": None,
            "sort": None,
        }
    )


@pytest.fixture
def tools():
    fake = FakeMCP()
    devices_mod.register(fake)
    mod.register(fake)

    get_devices = fake._tools["central_get_devices"]

    async def get_gateway_devices(ctx, **kwargs):
        return await get_devices(ctx, device_type="gateway", **kwargs)

    fake._tools["central_get_devices"] = get_gateway_devices
    return fake._tools


@pytest.fixture(autouse=True)
def resolve_as_gateway():
    with patch(
        "tools.devices._resolve_monitoring_family",
        side_effect=lambda _conn, serial: ("gateway", serial),
    ):
        yield


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_registers_gateway_tools(tools):
    assert "central_get_devices" in tools
    assert "central_get_device_details" in tools
    assert "central_get_device_trends" in tools
    assert "central_get_gateway_cluster" in tools


def test_gateway_module_itself_keeps_only_cluster_tools():
    fake = FakeMCP()
    mod.register(fake)
    assert list(fake._tools) == ["central_get_gateway_cluster"]


# ---------------------------------------------------------------------------
# central_get_devices — filters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_gateways_page_one_uses_single_page_api_and_emits_cursor(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.devices.MonitoringGateways.get_gateways",
            return_value=gateway_page(
                [RAW_GATEWAY],
                total=150,
                next_cursor="2",
            ),
        ) as mock_api,
        patch(
            "tools.devices.MonitoringGateways.get_all_gateways",
            side_effect=AssertionError("aggregation API called"),
        ) as mock_all,
    ):
        result = await tools["central_get_devices"](ctx)

    decoded = decode_cursor(
        result.next_cursor,
        expected_tool="central_get_devices:gateway",
        expected_query_hash=device_family_query_hash("gateway"),
    )

    assert isinstance(result, DeviceEnvelope)
    assert result.total == 150
    assert result.meta.total_available == 150
    assert result.items[0].serial_number == "DL0006948"
    assert result.items[0].device_type == "GATEWAY"
    assert result.items[0].status == "ONLINE"
    assert result.items[0].name == "BO-BLR-GTW01"
    assert result.items[0].model == "A7240XM"
    assert result.items[0].function == "Unspecified"
    assert result.items[0].role == "Member"
    assert result.items[0].firmware_version == "10.5.0.0_87691"
    assert result.items[0].site_id == "62201157617"
    assert result.items[0].site_name == "Bengaluru (BLR) - Branch"
    assert result.items[0].ipv4 == "10.97.55.248"
    call_kwargs = mock_api.call_args.kwargs
    assert call_kwargs["filter_str"] is None
    assert call_kwargs["sort"] is None
    assert call_kwargs["limit"] == devices_mod.DEFAULT_DEVICE_LIMIT
    assert call_kwargs["next_page"] == 1
    assert decoded.page_size == devices_mod.DEFAULT_DEVICE_LIMIT
    assert decoded.position == {"upstream_next": "2"}
    mock_api.assert_called_once()
    mock_all.assert_not_called()


@pytest.mark.asyncio
async def test_get_gateways_last_page_is_terminal(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringGateways.get_gateways",
        return_value=gateway_page([RAW_GATEWAY], total=101, next_cursor=None),
    ):
        result = await tools["central_get_devices"](ctx, limit=50)

    assert result.next_cursor is None
    assert result.total == 101
    assert result.meta.total_available == 101
    assert result.truncated is False


@pytest.mark.asyncio
async def test_get_gateways_cursor_replay_fetches_next_upstream_page(tools):
    ctx = make_ctx()
    second_gateway = {
        **RAW_GATEWAY,
        "serialNumber": "DL0006949",
        "deviceName": "BO-BLR-GTW02",
    }
    with patch(
        "tools.devices.MonitoringGateways.get_gateways",
        side_effect=[
            gateway_page([RAW_GATEWAY], total=2, next_cursor="2"),
            gateway_page([second_gateway], total=2, next_cursor=None),
        ],
    ) as mock_api:
        first_page = await tools["central_get_devices"](ctx, limit=50)
        second_page = await tools["central_get_devices"](
            ctx,
            cursor=first_page.next_cursor,
        )

    second_call = mock_api.call_args_list[1].kwargs
    assert second_call["next_page"] == 2
    assert second_call["limit"] == 50
    assert [item.serial_number for item in second_page.items] == ["DL0006949"]


@pytest.mark.asyncio
async def test_get_gateways_rejects_limit_above_upstream_max(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.devices.api_context",
            side_effect=AssertionError("connection opened"),
        ) as mock_context,
        pytest.raises(ToolError) as exc_info,
    ):
        await tools["central_get_devices"](
            ctx,
            limit=GATEWAY_MAX_PAGE_SIZE + 1,
        )

    error = json.loads(str(exc_info.value))
    assert error["code"] == "validation_error"
    assert error["retryable"] is False
    assert "gateway page size max is 100" in error["message"]
    mock_context.assert_not_called()


@pytest.mark.asyncio
async def test_get_gateways_rejects_cursor_page_size_above_upstream_max(tools):
    ctx = make_ctx()
    cursor = encode_cursor(
        "central_get_devices:gateway",
        GATEWAY_MAX_PAGE_SIZE + 1,
        {"upstream_next": "2"},
        device_family_query_hash("gateway"),
    )
    with (
        patch(
            "tools.devices.api_context",
            side_effect=AssertionError("connection opened"),
        ) as mock_context,
        pytest.raises(ToolError) as exc_info,
    ):
        await tools["central_get_devices"](ctx, cursor=cursor)

    error = json.loads(str(exc_info.value))
    assert error["code"] == "validation_error"
    assert error["retryable"] is False
    assert "gateway page size max is 100" in error["message"]
    mock_context.assert_not_called()


@pytest.mark.asyncio
async def test_get_gateways_accepts_upstream_max_page_size(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringGateways.get_gateways",
        return_value=gateway_page(),
    ) as mock_api:
        result = await tools["central_get_devices"](
            ctx,
            limit=GATEWAY_MAX_PAGE_SIZE,
        )

    assert result.items == []
    assert mock_api.call_args.kwargs["limit"] == GATEWAY_MAX_PAGE_SIZE


@pytest.mark.asyncio
async def test_get_gateways_rejects_ap_family_cursor(tools):
    ctx = make_ctx()
    ap_cursor = encode_cursor(
        "central_get_devices:ap",
        50,
        {"upstream_next": "2"},
        device_family_query_hash("ap"),
    )
    with (
        patch(
            "tools.devices.api_context",
            side_effect=AssertionError("connection opened"),
        ) as mock_context,
        pytest.raises(ToolError) as exc_info,
    ):
        await tools["central_get_devices"](ctx, cursor=ap_cursor)

    error = json.loads(str(exc_info.value))
    assert error["code"] == "validation_error"
    assert error["retryable"] is False
    assert "invalid or stale cursor" in error["message"]
    mock_context.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_arg,tool_value,expected_filter",
    [
        ("site_id", "62201157617", "siteId eq '62201157617'"),
        (
            "site_name",
            "Bengaluru (BLR) - Branch",
            "siteName eq 'Bengaluru (BLR) - Branch'",
        ),
        ("model", "A7240XM", "model eq 'A7240XM'"),
        ("device_status", "ONLINE", "status eq 'Online'"),
        ("cluster_name", "auto_group_168", "clusterName eq 'auto_group_168'"),
    ],
)
async def test_get_gateways_filter_field_mappings(
    tools, tool_arg, tool_value, expected_filter
):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringGateways.get_gateways",
        return_value=gateway_page(),
    ) as mock_api:
        await tools["central_get_devices"](ctx, **{tool_arg: tool_value})
    assert mock_api.call_args.kwargs["filter_str"] == expected_filter


@pytest.mark.asyncio
async def test_get_gateways_status_title_case_online(tools):
    """status='Online' (title-case) produces the correct filter — not ONLINE."""
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringGateways.get_gateways",
        return_value=gateway_page([RAW_GATEWAY]),
    ) as mock_api:
        result = await tools["central_get_devices"](ctx, device_status="ONLINE")
    assert mock_api.call_args.kwargs["filter_str"] == "status eq 'Online'"
    assert isinstance(result, DeviceEnvelope)


@pytest.mark.asyncio
async def test_get_gateways_status_title_case_offline(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringGateways.get_gateways",
        return_value=gateway_page(),
    ) as mock_api:
        await tools["central_get_devices"](ctx, device_status="OFFLINE")
    assert mock_api.call_args.kwargs["filter_str"] == "status eq 'Offline'"


@pytest.mark.asyncio
async def test_get_gateways_empty_returns_string(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringGateways.get_gateways",
        return_value=gateway_page(),
    ):
        result = await tools["central_get_devices"](ctx, site_id="missing")
    assert result.items == []


@pytest.mark.asyncio
async def test_get_gateways_api_error_returns_formatted_error(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.devices.MonitoringGateways.get_gateways",
            side_effect=Exception("boom"),
        ),
        pytest.raises(ToolError, match="boom"),
    ):
        await tools["central_get_devices"](ctx)


@pytest.mark.asyncio
async def test_get_gateways_parse_error_returns_formatted_error(tools):
    """A parse error (e.g. missing required field) surfaces the parsing error."""
    ctx = make_ctx()
    # serialNumber is required; omitting it triggers a Pydantic ValidationError
    bad_payload = [{"model": "A7240XM", "status": "Online"}]
    with (
        patch(
            "tools.devices.MonitoringGateways.get_gateways",
            return_value=gateway_page(bad_payload),
        ),
        pytest.raises(ToolError, match="serialNumber"),
    ):
        await tools["central_get_devices"](ctx)


@pytest.mark.asyncio
async def test_get_gateways_null_optional_fields_excluded(tools):
    ctx = make_ctx()
    sparse = {"serialNumber": "GW001", "status": "Online"}
    with patch(
        "tools.devices.MonitoringGateways.get_gateways",
        return_value=gateway_page([sparse]),
    ):
        result = await tools["central_get_devices"](ctx)
    serialized = result.items[0].model_dump()
    assert serialized["serial_number"] == "GW001"
    assert serialized["status"] == "ONLINE"
    assert serialized["device_type"] == "GATEWAY"


@pytest.mark.asyncio
async def test_get_gateways_sort_passed_through(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringGateways.get_gateways",
        return_value=gateway_page([RAW_GATEWAY]),
    ) as mock_api:
        await tools["central_get_devices"](ctx, sort="deviceName asc")
    assert mock_api.call_args.kwargs["sort"] == "deviceName ASC"


# ---------------------------------------------------------------------------
# central_get_device_details
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_gateway_details_base_only(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_gateway_details",
            return_value=dict(RAW_GATEWAY),
        ) as mock_details,
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_all_gateway_ports"
        ) as mock_ports,
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_all_gateway_tunnels"
        ) as mock_tunnels,
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_gateway_uplinks"
        ) as mock_uplinks,
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_all_gateway_vlans"
        ) as mock_vlans,
    ):
        result = await tools["central_get_device_details"](
            ctx, serial_number="DL0006948"
        )

    assert isinstance(result, GatewayDetail)
    assert result.serial_number == "DL0006948"
    assert result.ports is None
    assert result.tunnels is None
    assert result.uplinks is None
    assert result.vlans is None
    mock_details.assert_called_once_with(
        central_conn=ctx.lifespan_context["conn"], serial_number="DL0006948"
    )
    mock_ports.assert_not_called()
    mock_tunnels.assert_not_called()
    mock_uplinks.assert_not_called()
    mock_vlans.assert_not_called()


@pytest.mark.asyncio
async def test_get_gateway_details_include_dhcp_fetches_pools_and_leases(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_gateway_details",
            return_value=dict(RAW_GATEWAY),
        ),
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_all_gateway_dhcp_pools",
            return_value=[RAW_DHCP_POOL],
        ) as mock_pools,
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_all_gateway_dhcp_clients",
            return_value=[RAW_DHCP_LEASE],
        ) as mock_leases,
    ):
        result = await tools["central_get_device_details"](
            ctx, serial_number="DL0006948", include=["dhcp"]
        )

    assert isinstance(result, GatewayDetail)
    mock_pools.assert_called_once()
    mock_leases.assert_called_once()
    assert result.dhcp_pools[0].pool_name == "pool-1"
    assert result.dhcp_pools[0].available_addresses == 96
    assert result.dhcp_leases[0].ip_address == "192.168.3.4"
    assert result.dhcp_leases[0].reservation == "No"


@pytest.mark.asyncio
async def test_get_gateway_details_include_tunnels(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_gateway_details",
            return_value=dict(RAW_GATEWAY),
        ),
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_all_gateway_tunnels",
            return_value=[RAW_TUNNEL],
        ) as mock_tunnels,
    ):
        result = await tools["central_get_device_details"](
            ctx, serial_number="DL0006948", include=["tunnels"]
        )

    assert isinstance(result, GatewayDetail)
    mock_tunnels.assert_called_once()
    assert result.tunnels is not None
    assert result.tunnels[0].tunnel_name == "BO-BLR-GTW01:inet::BO-BLR-AP04:inet"
    assert result.tunnels[0].tunnel_type == "LAN"


@pytest.mark.asyncio
async def test_get_gateway_details_include_uplinks_envelope_unwrapped(tools):
    """Uplinks endpoint returns {items, total}; fetch_snapshot unwraps to items list."""
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_gateway_details",
            return_value=dict(RAW_GATEWAY),
        ),
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_gateway_uplinks",
            return_value={"items": [RAW_UPLINK], "total": 1},
        ) as mock_uplinks,
    ):
        result = await tools["central_get_device_details"](
            ctx, serial_number="DL0006948", include=["uplinks"]
        )

    assert isinstance(result, GatewayDetail)
    mock_uplinks.assert_called_once()
    assert result.uplinks is not None
    assert len(result.uplinks) == 1
    assert result.uplinks[0].link_tag == "uplink-0"


@pytest.mark.asyncio
async def test_get_gateway_details_include_uplinks_empty_envelope(tools):
    """Empty uplinks envelope (total=0, items=[]) results in empty list."""
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_gateway_details",
            return_value=dict(RAW_GATEWAY),
        ),
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_gateway_uplinks",
            return_value={"items": [], "total": 0},
        ),
    ):
        result = await tools["central_get_device_details"](
            ctx, serial_number="DL0006948", include=["uplinks"]
        )

    assert isinstance(result, GatewayDetail)
    # items=[] means the key is absent (fetch_snapshot checks "items" in result but stores [])
    # The GatewayDetail.uplinks will either be None or empty list
    assert result.uplinks is None or result.uplinks == []


@pytest.mark.asyncio
async def test_get_gateway_details_dhcp_empty_lists_are_preserved(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_gateway_details",
            return_value=dict(RAW_GATEWAY),
        ),
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_all_gateway_dhcp_pools",
            return_value=[],
        ),
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_all_gateway_dhcp_clients",
            return_value=[],
        ),
    ):
        result = await tools["central_get_device_details"](
            ctx, serial_number="DL0006948", include=["dhcp"]
        )

    assert isinstance(result, GatewayDetail)
    assert result.dhcp_pools == []
    assert result.dhcp_leases == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "include,method_name,response,attribute,expected",
    [
        ("ports", "get_all_gateway_ports", [RAW_PORT], "port_number", "0"),
        ("vlans", "get_all_gateway_vlans", [RAW_VLAN], "vlan_id", 1330),
    ],
)
async def test_get_gateway_details_restored_ports_and_vlans_includes(
    tools, include, method_name, response, attribute, expected
):
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_gateway_details",
            return_value=dict(RAW_GATEWAY),
        ),
        patch(
            f"tools.gateway_monitoring.MonitoringGateways.{method_name}",
            return_value=response,
        ) as mock_include,
    ):
        result = await tools["central_get_device_details"](
            ctx, serial_number="DL0006948", include=[include]
        )
    mock_include.assert_called_once()
    included = getattr(result, include)
    assert included and getattr(included[0], attribute) == expected


@pytest.mark.asyncio
async def test_get_gateway_details_rejects_switch_include_before_detail_fetch(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_gateway_details",
            side_effect=AssertionError("detail fetch opened"),
        ) as mock_details,
        pytest.raises(ToolError, match=r"interfaces.*device_type='gateway'"),
    ):
        await tools["central_get_device_details"](
            ctx, serial_number="DL0006948", include=["interfaces"]
        )
    mock_details.assert_not_called()


def test_gateway_dhcp_model_fields_all_have_descriptions():
    for model in (GatewayDHCPPool, GatewayDHCPLease):
        assert all(field.description for field in model.model_fields.values())


@pytest.mark.asyncio
async def test_get_gateway_details_not_found(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_gateway_details",
            return_value=None,
        ),
        pytest.raises(ToolError, match="No gateway found"),
    ):
        await tools["central_get_device_details"](ctx, serial_number="MISSING")


@pytest.mark.asyncio
async def test_get_gateway_details_empty_dict_not_found(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_gateway_details",
            return_value={},
        ),
        pytest.raises(ToolError, match="No gateway found"),
    ):
        await tools["central_get_device_details"](ctx, serial_number="MISSING2")


@pytest.mark.asyncio
async def test_get_gateway_details_fetch_error(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_gateway_details",
            side_effect=Exception("connection refused"),
        ),
        pytest.raises(ToolError, match="connection refused"),
    ):
        await tools["central_get_device_details"](ctx, serial_number="DL0006948")


# ---------------------------------------------------------------------------
# central_get_device_trends — scope validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_gateway_trends_gateway_cpu(tools):
    ctx = make_ctx()
    samples = [{"timestamp": "2026-06-05T19:05:00Z", "cpu_utilization": 2}]
    with patch(
        "tools.gateway_monitoring.MonitoringGateways.get_gateway_trends",
        return_value=samples,
    ) as mock_trends:
        result = await tools["central_get_device_trends"](
            ctx,
            serial_number="DL0006948",
            metric="cpu-utilization",
            scope="gateway",
        )

    assert isinstance(result, DeviceTrendsEnvelope)
    assert isinstance(result.items[0], TrendSample)
    assert result.items[0].model_dump()["cpu_utilization"] == 2
    call_kwargs = mock_trends.call_args.kwargs
    assert call_kwargs["metric"] == "cpu-utilization"


@pytest.mark.asyncio
async def test_get_gateway_trends_gateway_memory(tools):
    ctx = make_ctx()
    samples = [{"timestamp": "2026-06-05T19:05:00Z", "memory_utilization": 20}]
    with patch(
        "tools.gateway_monitoring.MonitoringGateways.get_gateway_trends",
        return_value=samples,
    ):
        result = await tools["central_get_device_trends"](
            ctx,
            serial_number="DL0006948",
            metric="memory-utilization",
        )
    assert result.items[0].model_dump()["memory_utilization"] == 20


@pytest.mark.asyncio
async def test_get_gateway_trends_wan_availability_minus_one(tools):
    """wan-availability returns -1 when not configured; tool passes through unchanged."""
    ctx = make_ctx()
    samples = [{"timestamp": "2026-06-05T19:05:00Z", "wan_availability": -1}]
    with patch(
        "tools.gateway_monitoring.MonitoringGateways.get_gateway_trends",
        return_value=samples,
    ):
        result = await tools["central_get_device_trends"](
            ctx,
            serial_number="DL0006948",
            metric="wan-availability",
        )
    assert result.items[0].model_dump()["wan_availability"] == -1


@pytest.mark.asyncio
async def test_get_gateway_trends_port_throughput(tools):
    """scope='port' with port_number calls get_gateway_port_trends."""
    ctx = make_ctx()
    samples = [{"timestamp": "2026-06-05T19:05:00Z", "tx": 27442, "rx": 35879}]
    with patch(
        "tools.gateway_monitoring.MonitoringGateways.get_gateway_port_trends",
        return_value=samples,
    ) as mock_port_trends:
        result = await tools["central_get_device_trends"](
            ctx,
            serial_number="DL0006948",
            metric="throughput",
            scope="port",
            port_number="0",
        )

    assert isinstance(result, DeviceTrendsEnvelope)
    assert result.items[0].model_dump()["tx"] == 27442
    assert mock_port_trends.call_args.kwargs["port_number"] == "0"


@pytest.mark.asyncio
async def test_get_gateway_trends_tunnel_throughput(tools):
    """scope='tunnel' with tunnel_name calls get_gateway_tunnel_trends."""
    ctx = make_ctx()
    samples = [{"timestamp": "2026-06-05T19:05:00Z", "tx": 0, "rx": 0}]
    with patch(
        "tools.gateway_monitoring.MonitoringGateways.get_gateway_tunnel_trends",
        return_value=samples,
    ) as mock_tunnel_trends:
        result = await tools["central_get_device_trends"](
            ctx,
            serial_number="DL0006948",
            metric="throughput",
            scope="tunnel",
            tunnel_name="BO-BLR-GTW01:inet::BO-BLR-AP04:inet",
        )

    assert isinstance(result, DeviceTrendsEnvelope)
    assert (
        mock_tunnel_trends.call_args.kwargs["tunnel_name"]
        == "BO-BLR-GTW01:inet::BO-BLR-AP04:inet"
    )


@pytest.mark.asyncio
async def test_get_gateway_trends_uplink_scope(tools):
    """scope='uplink' with link_tag calls get_gateway_uplink_trends."""
    ctx = make_ctx()
    samples = [{"timestamp": "2026-06-05T19:05:00Z", "tx": 1000, "rx": 2000}]
    with patch(
        "tools.gateway_monitoring.MonitoringGateways.get_gateway_uplink_trends",
        return_value=samples,
    ) as mock_uplink_trends:
        result = await tools["central_get_device_trends"](
            ctx,
            serial_number="DL0006948",
            metric="throughput",
            scope="uplink",
            link_tag="uplink-0",
        )

    assert isinstance(result, DeviceTrendsEnvelope)
    assert mock_uplink_trends.call_args.kwargs["link_tag"] == "uplink-0"


@pytest.mark.asyncio
async def test_get_gateway_trends_port_missing_port_number(tools):
    """scope='port' without port_number returns formatted error containing 'port_number'."""
    ctx = make_ctx()
    with pytest.raises(ToolError, match="port_number"):
        await tools["central_get_device_trends"](
            ctx,
            serial_number="DL0006948",
            metric="throughput",
            scope="port",
        )


@pytest.mark.asyncio
async def test_get_gateway_trends_tunnel_missing_tunnel_name(tools):
    """scope='tunnel' without tunnel_name returns formatted error containing 'tunnel_name'."""
    ctx = make_ctx()
    with pytest.raises(ToolError, match="tunnel_name"):
        await tools["central_get_device_trends"](
            ctx,
            serial_number="DL0006948",
            metric="throughput",
            scope="tunnel",
        )


@pytest.mark.asyncio
async def test_get_gateway_trends_uplink_missing_link_tag(tools):
    """scope='uplink' without link_tag returns formatted error containing 'link_tag'."""
    ctx = make_ctx()
    with pytest.raises(ToolError, match="link_tag"):
        await tools["central_get_device_trends"](
            ctx,
            serial_number="DL0006948",
            metric="throughput",
            scope="uplink",
        )


@pytest.mark.asyncio
async def test_get_gateway_trends_invalid_metric_for_gateway_scope(tools):
    """scope='gateway' with a port-only metric returns error naming valid gateway metrics."""
    ctx = make_ctx()
    with pytest.raises(ToolError, match="cpu-utilization"):
        await tools["central_get_device_trends"](
            ctx,
            serial_number="DL0006948",
            metric="frames-errors",  # port-only metric
            scope="gateway",
        )


@pytest.mark.asyncio
async def test_get_gateway_trends_invalid_scope(tools):
    """An unrecognized scope returns a formatted error naming valid scopes."""
    ctx = make_ctx()
    with pytest.raises(ToolError, match="gateway"):
        await tools["central_get_device_trends"](
            ctx,
            serial_number="DL0006948",
            metric="cpu-utilization",
            scope="blade",  # invalid
        )


@pytest.mark.asyncio
async def test_get_gateway_trends_explicit_time_window(tools):
    """Explicit start_time/end_time are passed through to the underlying API call."""
    ctx = make_ctx()
    samples = [{"timestamp": "2026-03-21T12:00:00Z", "cpu_utilization": 10}]
    with patch(
        "tools.gateway_monitoring.MonitoringGateways.get_gateway_trends",
        return_value=samples,
    ) as mock_trends:
        await tools["central_get_device_trends"](
            ctx,
            serial_number="DL0006948",
            metric="cpu-utilization",
            start_time="2026-03-21T00:00:00.000Z",
            end_time="2026-03-21T23:59:59.999Z",
        )

    assert mock_trends.call_args.kwargs["start_time"] == "2026-03-21T00:00:00.000Z"
    assert mock_trends.call_args.kwargs["end_time"] == "2026-03-21T23:59:59.999Z"


@pytest.mark.asyncio
async def test_get_gateway_trends_empty_returns_string(tools):
    ctx = make_ctx()
    with patch(
        "tools.gateway_monitoring.MonitoringGateways.get_gateway_trends",
        return_value=[],
    ):
        result = await tools["central_get_device_trends"](
            ctx,
            serial_number="DL0006948",
            metric="cpu-utilization",
        )
    assert isinstance(result, DeviceTrendsEnvelope)
    assert result.items == []
    assert result.meta.returned == 0


@pytest.mark.asyncio
async def test_get_gateway_trends_api_exception(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_gateway_trends",
            side_effect=RuntimeError("upstream failure"),
        ),
        pytest.raises(ToolError, match="upstream failure"),
    ):
        await tools["central_get_device_trends"](
            ctx,
            serial_number="DL0006948",
            metric="cpu-utilization",
        )


# ---------------------------------------------------------------------------
# hardware-temperature normalization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_gateway_trends_temperature_normalization(tools):
    """hardware-temperature list-of-sensor-dicts is normalized per timestamp with sensor keys."""
    ctx = make_ctx()
    with patch(
        "tools.gateway_monitoring.MonitoringGateways.get_gateway_trends",
        return_value=RAW_TEMPERATURE_LIST,
    ):
        result = await tools["central_get_device_trends"](
            ctx,
            serial_number="DL0006948",
            metric="hardware-temperature",
        )

    assert isinstance(result, DeviceTrendsEnvelope)
    assert len(result.items) == 1  # single shared timestamp
    assert result.meta.total_available == 1
    sample = result.items[0].model_dump()
    assert sample["timestamp"] == "2026-06-05T19:05:00Z"
    assert sample["CPU"] == 42
    assert sample["Ambient"] == 30


@pytest.mark.asyncio
async def test_get_gateway_trends_temperature_multiple_timestamps(tools):
    """Multiple timestamps across sensors are each emitted as separate samples."""
    ctx = make_ctx()
    raw = [
        {
            "graph": {
                "samples": [
                    {"data": [42], "timestamp": "2026-06-05T19:05:00Z"},
                    {"data": [43], "timestamp": "2026-06-05T19:10:00Z"},
                ],
                "keys": ["CPU"],
            }
        },
        {
            "graph": {
                "samples": [
                    {"data": [30], "timestamp": "2026-06-05T19:05:00Z"},
                    {"data": [31], "timestamp": "2026-06-05T19:10:00Z"},
                ],
                "keys": ["Ambient"],
            }
        },
    ]
    with patch(
        "tools.gateway_monitoring.MonitoringGateways.get_gateway_trends",
        return_value=raw,
    ):
        result = await tools["central_get_device_trends"](
            ctx,
            serial_number="DL0006948",
            metric="hardware-temperature",
        )

    assert len(result.items) == 2
    samples = [r.model_dump() for r in result.items]
    assert samples[0]["CPU"] == 42
    assert samples[0]["Ambient"] == 30
    assert samples[1]["CPU"] == 43
    assert samples[1]["Ambient"] == 31


def test_normalize_temperature_trends_standalone():
    """Unit test for _normalize_temperature_trends helper."""
    result = mod._normalize_temperature_trends(RAW_TEMPERATURE_LIST)
    assert len(result) == 1
    assert result[0]["timestamp"] == "2026-06-05T19:05:00Z"
    assert result[0]["CPU"] == 42
    assert result[0]["Ambient"] == 30


def test_normalize_temperature_trends_empty_input():
    assert mod._normalize_temperature_trends([]) == []


# ---------------------------------------------------------------------------
# central_get_gateway_cluster
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_gateway_cluster_default(tools):
    """Default snapshot returns one typed cluster item with member health."""
    ctx = make_ctx()
    with patch(
        "tools.gateway_monitoring.fetch_cluster_snapshot",
        return_value=dict(RAW_CLUSTER_SNAPSHOT),
    ) as mock_snapshot:
        result = await tools["central_get_gateway_cluster"](
            ctx, cluster_name="auto_group_168"
        )

    assert isinstance(result, GatewayClusterEnvelope)
    assert isinstance(result.items[0], GatewayCluster)
    cluster = result.items[0]
    assert cluster.cluster_name == "auto_group_168"
    assert len(cluster.members) == 1
    assert cluster.members[0].serial_number == "DL0006948"
    assert cluster.members[0].status == "ONLINE"
    assert cluster.tunnel_health_summary is not None
    mock_snapshot.assert_called_once_with(
        mock_snapshot.call_args.args[0],  # conn
        "auto_group_168",
        None,
    )


@pytest.mark.asyncio
async def test_get_gateway_cluster_with_vlan_mismatch_include(tools):
    ctx = make_ctx()
    snapshot_with_mismatch = dict(RAW_CLUSTER_SNAPSHOT)
    snapshot_with_mismatch["vlan_mismatch"] = {
        "type": "network-monitoring/gateway-monitoring",
        "good": 1,
        "poor": 1,
        "id": "auto_group_168/vlan-mismatch",
    }
    with patch(
        "tools.gateway_monitoring.fetch_cluster_snapshot",
        return_value=snapshot_with_mismatch,
    ):
        result = await tools["central_get_gateway_cluster"](
            ctx, cluster_name="auto_group_168", include=["vlan_mismatch"]
        )

    cluster = result.items[0]
    assert cluster.vlan_mismatch is not None
    assert cluster.vlan_mismatch["good"] == 1


@pytest.mark.asyncio
async def test_get_gateway_cluster_with_connectivity_include(tools):
    ctx = make_ctx()
    snapshot_with_conn = dict(RAW_CLUSTER_SNAPSHOT)
    snapshot_with_conn["connectivity"] = {
        "nodes": [
            {
                "role": "Member",
                "health": "Good",
                "peers": [
                    {"vlanMismatch": "Yes", "mismatchedVlan": 1, "name": "BO-BLR-GTW02"}
                ],
                "name": "BO-BLR-GTW01",
                "serial": "DL0006948",
            }
        ],
        "id": "auto_group_168/connectivity-graph",
    }
    with patch(
        "tools.gateway_monitoring.fetch_cluster_snapshot",
        return_value=snapshot_with_conn,
    ):
        result = await tools["central_get_gateway_cluster"](
            ctx, cluster_name="auto_group_168", include=["connectivity"]
        )

    cluster = result.items[0]
    assert cluster.connectivity is not None
    assert len(cluster.connectivity["nodes"]) == 1


@pytest.mark.asyncio
async def test_get_gateway_cluster_empty_members_is_empty_envelope(tools):
    ctx = make_ctx()
    with patch(
        "tools.gateway_monitoring.fetch_cluster_snapshot",
        return_value={
            "cluster_name": "empty_cluster",
            "members": [],
            "tunnel_health_summary": [],
        },
    ):
        result = await tools["central_get_gateway_cluster"](
            ctx, cluster_name="empty_cluster"
        )
    assert isinstance(result, GatewayClusterEnvelope)
    assert result.items == []
    assert result.meta.returned == 0


@pytest.mark.asyncio
async def test_get_gateway_cluster_none_result_is_empty_envelope(tools):
    ctx = make_ctx()
    with patch(
        "tools.gateway_monitoring.fetch_cluster_snapshot",
        return_value=None,
    ):
        result = await tools["central_get_gateway_cluster"](
            ctx, cluster_name="nonexistent"
        )
    assert isinstance(result, GatewayClusterEnvelope)
    assert result.items == []


@pytest.mark.asyncio
async def test_get_gateway_cluster_api_error(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.fetch_cluster_snapshot",
            side_effect=Exception("network timeout"),
        ),
        pytest.raises(ToolError, match="network timeout"),
    ):
        await tools["central_get_gateway_cluster"](ctx, cluster_name="auto_group_168")


# ---------------------------------------------------------------------------
# central_get_gateway_cluster include=capacity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_gateway_cluster_include_capacity_normalized(tools):
    """Capacity include adds typed flat samples to the cluster item."""
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.fetch_cluster_snapshot",
            return_value=dict(RAW_CLUSTER_SNAPSHOT),
        ) as mock_snapshot,
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_cluster_capacity_trends",
            return_value=RAW_CAPACITY_TRENDS,
        ) as mock_capacity,
    ):
        result = await tools["central_get_gateway_cluster"](
            ctx,
            cluster_name="auto_group_168",
            include=["capacity"],
        )

    mock_snapshot.assert_called_once_with(
        mock_snapshot.call_args.args[0],
        "auto_group_168",
        None,
    )
    capacity = result.items[0].capacity
    assert capacity is not None
    assert all(isinstance(item, CapacityTrendSample) for item in capacity)
    client_sample = next(
        item for item in capacity if item.capacity_type == "client_capacity"
    )
    device_sample = next(
        item for item in capacity if item.capacity_type == "device_capacity"
    )
    assert client_sample.cluster_client_max_capacity == 65536
    assert client_sample.active_client_count == 0
    assert device_sample.active_ap_count == 1
    assert device_sample.cluster_device_max_capacity == 16384
    call_kwargs = mock_capacity.call_args.kwargs
    assert call_kwargs["cluster_name"] == "auto_group_168"
    assert call_kwargs["return_raw_response"] is True


@pytest.mark.asyncio
async def test_get_gateway_cluster_capacity_serial_number_passed_through(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.fetch_cluster_snapshot",
            return_value=dict(RAW_CLUSTER_SNAPSHOT),
        ),
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_cluster_capacity_trends",
            return_value=RAW_CAPACITY_TRENDS,
        ) as mock_capacity,
    ):
        await tools["central_get_gateway_cluster"](
            ctx,
            cluster_name="auto_group_168",
            include=["capacity"],
            serial_number="DL0006948",
        )
    assert mock_capacity.call_args.kwargs["serial_number"] == "DL0006948"


@pytest.mark.asyncio
async def test_get_gateway_cluster_capacity_explicit_time_window(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.fetch_cluster_snapshot",
            return_value=dict(RAW_CLUSTER_SNAPSHOT),
        ),
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_cluster_capacity_trends",
            return_value=RAW_CAPACITY_TRENDS,
        ) as mock_capacity,
    ):
        await tools["central_get_gateway_cluster"](
            ctx,
            cluster_name="auto_group_168",
            include=["capacity"],
            start_time="2026-06-05T18:00:00.000Z",
            end_time="2026-06-05T19:00:00.000Z",
        )
    call_kwargs = mock_capacity.call_args.kwargs
    assert call_kwargs["start_time"] == "2026-06-05T18:00:00.000Z"
    assert call_kwargs["end_time"] == "2026-06-05T19:00:00.000Z"


@pytest.mark.asyncio
async def test_get_gateway_cluster_capacity_empty_is_additive_empty_list(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.fetch_cluster_snapshot",
            return_value=dict(RAW_CLUSTER_SNAPSHOT),
        ),
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_cluster_capacity_trends",
            return_value=[],
        ),
    ):
        result = await tools["central_get_gateway_cluster"](
            ctx,
            cluster_name="auto_group_168",
            include=["capacity"],
        )
    assert result.items[0].capacity == []


@pytest.mark.asyncio
async def test_get_gateway_cluster_capacity_api_error_raises_tool_error(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.fetch_cluster_snapshot",
            return_value=dict(RAW_CLUSTER_SNAPSHOT),
        ),
        patch(
            "tools.gateway_monitoring.MonitoringGateways.get_cluster_capacity_trends",
            side_effect=Exception("API error"),
        ),
        pytest.raises(ToolError, match="API error"),
    ):
        await tools["central_get_gateway_cluster"](
            ctx,
            cluster_name="auto_group_168",
            include=["capacity"],
        )


@pytest.mark.asyncio
async def test_get_gateway_cluster_capacity_params_require_include_before_connection(
    tools,
):
    ctx = make_ctx()
    with (
        patch(
            "tools.gateway_monitoring.api_context",
            side_effect=AssertionError("connection opened"),
        ) as mock_context,
        pytest.raises(ToolError, match=r"serial_number.*include='capacity'"),
    ):
        await tools["central_get_gateway_cluster"](
            ctx,
            cluster_name="auto_group_168",
            serial_number="DL0006948",
        )
    mock_context.assert_not_called()


def test_normalize_capacity_trends_standalone():
    """Unit test for _normalize_capacity_trends helper."""
    result = mod._normalize_capacity_trends(RAW_CAPACITY_TRENDS)
    assert len(result) == 2
    client = next(r for r in result if r["capacity_type"] == "client_capacity")
    assert client["cluster_client_max_capacity"] == 65536
    assert client["timestamp"] == "2026-06-05T19:00:00Z"


def test_normalize_capacity_trends_empty_input():
    assert mod._normalize_capacity_trends([]) == []


# ---------------------------------------------------------------------------
# GatewayUplink model
# ---------------------------------------------------------------------------


def test_gateway_uplink_model_parses_correctly():
    uplink = GatewayUplink(**RAW_UPLINK)
    assert uplink.link_tag == "uplink-0"
    assert uplink.name == "WAN-1"
    assert uplink.status == "Up"
    assert uplink.uplink_type == "wired"


def test_gateway_uplink_null_fields_excluded_on_dump():
    uplink = GatewayUplink(linkTag="tag-1")
    dumped = uplink.model_dump()
    assert dumped["link_tag"] == "tag-1"
    assert "name" not in dumped
    assert "status" not in dumped


def test_gateway_detail_uplinks_wired_into_model():
    """GatewayDetail.from_api correctly parses uplinks list into GatewayUplink instances."""
    raw = dict(RAW_GATEWAY)
    raw["uplinks"] = [RAW_UPLINK]
    detail = GatewayDetail.from_api(raw)
    assert detail.uplinks is not None
    assert len(detail.uplinks) == 1
    assert isinstance(detail.uplinks[0], GatewayUplink)
    assert detail.uplinks[0].link_tag == "uplink-0"
