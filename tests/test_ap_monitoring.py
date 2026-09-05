from unittest.mock import patch

import pytest
from fastmcp.exceptions import ToolError

import tools.devices as mod
from models import (
    AccessPoint,
    APDetail,
    APPort,
    APRadio,
    DeviceEnvelope,
    DeviceTrendsEnvelope,
)
from tests.conftest import FakeMCP, make_ctx
from utils.cursor import decode_cursor, hash_query

RAW_AP = {
    "serialNumber": "AP123456",
    "deviceName": "ap-lobby-01",
    "siteId": "site-1",
    "siteName": "HQ",
    "status": "ONLINE",
    "model": "AP-635",
    "firmwareVersion": "10.6.0.2",
    "deployment": "Standalone",
    "clusterId": "cluster-1",
    "clusterName": "hq-cluster",
    "partNumber": "R7J54A",
    "deviceFunction": "",
    "role": "",
    "ipv4": "10.0.0.1",
    "macAddress": "8c:79:09:c3:53:40",
    "cpuUtilization": 12,
    "memoryUtilization": 45,
    "powerConsumption": 8.5,
    "clientCount": 3,
    "lastRebootReason": "COLD_HW_RESET",
    "publicIpv4": "61.246.230.194",
}

RAW_DETAIL_BASE = {
    "serialNumber": "AP123456",
    "deviceName": "ap-lobby-01",
    "status": "ONLINE",
    "model": "AP-635",
    "apStats": [{"clientCount": 5, "cpuUtilization": 20, "memoryUtilization": 40}],
    "radios": [
        {
            "radioNumber": 0,
            "band": "5GHz",
            "radioStats": [{"noiseFloor": -90, "channelUtilization": 15}],
        }
    ],
    "ports": [{"portIndex": 0, "name": "eth0", "status": "UP"}],
    "wlans": [{"wlanName": "Corp-WiFi", "band": "5GHz"}],
}


def ap_page(
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


def ap_query_hash() -> str:
    return hash_query(
        {
            "device_type": "ap",
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
    mod.register(fake)
    return fake._tools


@pytest.fixture(autouse=True)
def resolve_as_ap():
    with patch(
        "tools.devices._resolve_monitoring_family",
        side_effect=lambda _conn, serial: ("ap", serial),
    ):
        yield


@pytest.mark.asyncio
async def test_get_devices_ap_page_one_uses_single_page_api_and_emits_cursor(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.devices.MonitoringAPs.get_aps",
            return_value=ap_page([RAW_AP], total=150, next_cursor="2"),
        ) as mock_api,
        patch(
            "tools.devices.MonitoringAPs.get_all_aps",
            side_effect=AssertionError("aggregation API called"),
        ) as mock_all,
    ):
        result = await tools["central_get_devices"](ctx, device_type="ap")

    decoded = decode_cursor(
        result.next_cursor,
        expected_tool="central_get_devices:ap",
        expected_query_hash=ap_query_hash(),
    )

    assert isinstance(result, DeviceEnvelope)
    assert result.total == 150
    assert result.meta.total_available == 150
    assert result.items[0].device_type == "ACCESS_POINT"
    assert result.items[0].serial_number == "AP123456"
    assert result.items[0].status == "ONLINE"
    assert result.items[0].name == "ap-lobby-01"
    assert result.items[0].model == "AP-635"
    assert result.items[0].firmware_version == "10.6.0.2"
    assert result.items[0].deployment == "Standalone"
    assert result.items[0].site_id == "site-1"
    assert result.items[0].site_name == "HQ"
    assert result.items[0].ipv4 == "10.0.0.1"
    assert mock_api.call_args.kwargs["filter_str"] is None
    assert mock_api.call_args.kwargs["limit"] == mod.DEFAULT_DEVICE_LIMIT
    assert mock_api.call_args.kwargs["next_page"] == 1
    assert decoded.page_size == mod.DEFAULT_DEVICE_LIMIT
    assert decoded.position == {"upstream_next": "2"}
    mock_api.assert_called_once()
    mock_all.assert_not_called()


@pytest.mark.asyncio
async def test_get_devices_ap_last_page_is_terminal(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringAPs.get_aps",
        return_value=ap_page([RAW_AP], total=101, next_cursor=None),
    ):
        result = await tools["central_get_devices"](
            ctx,
            device_type="ap",
            limit=50,
        )

    assert result.next_cursor is None
    assert result.total == 101
    assert result.meta.total_available == 101
    assert result.truncated is False


@pytest.mark.asyncio
async def test_get_devices_ap_cursor_replay_fetches_next_upstream_page(tools):
    ctx = make_ctx()
    second_ap = {
        **RAW_AP,
        "serialNumber": "AP654321",
        "deviceName": "ap-lobby-02",
    }
    with patch(
        "tools.devices.MonitoringAPs.get_aps",
        side_effect=[
            ap_page([RAW_AP], total=2, next_cursor="2"),
            ap_page([second_ap], total=2, next_cursor=None),
        ],
    ) as mock_api:
        first_page = await tools["central_get_devices"](
            ctx,
            device_type="ap",
            limit=50,
        )
        second_page = await tools["central_get_devices"](
            ctx,
            device_type="ap",
            cursor=first_page.next_cursor,
        )

    second_call = mock_api.call_args_list[1].kwargs
    assert second_call["next_page"] == 2
    assert second_call["limit"] == 50
    assert [item.serial_number for item in second_page.items] == ["AP654321"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_arg,tool_value,expected_filter",
    [
        ("site_id", "site-1", "siteId eq 'site-1'"),
        ("site_name", "HQ", "siteName eq 'HQ'"),
        ("device_status", "ONLINE", "status eq 'ONLINE'"),
        ("model", "AP-635", "model eq 'AP-635'"),
        ("firmware_version", "10.6.0.2", "firmwareVersion eq '10.6.0.2'"),
        ("deployment", "Standalone", "deployment eq 'Standalone'"),
        ("cluster_id", "cluster-1", "clusterId eq 'cluster-1'"),
        ("cluster_name", "hq-cluster", "clusterName eq 'hq-cluster'"),
    ],
)
async def test_get_devices_ap_filter_field_mappings(
    tools, tool_arg, tool_value, expected_filter
):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringAPs.get_aps",
        return_value=ap_page(),
    ) as mock_api:
        result = await tools["central_get_devices"](
            ctx, device_type="ap", **{tool_arg: tool_value}
        )
    assert result.items == []
    assert mock_api.call_args.kwargs["filter_str"] == expected_filter


@pytest.mark.asyncio
async def test_get_devices_ap_combined_filters_and_sort(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringAPs.get_aps",
        return_value=ap_page(),
    ) as mock_api:
        await tools["central_get_devices"](
            ctx,
            device_type="ap",
            site_id="site-1",
            device_status="OFFLINE",
            cluster_name="hq-cluster",
            sort="deviceName asc",
        )
    assert mock_api.call_args.kwargs["filter_str"] == (
        "siteId eq 'site-1' and status eq 'OFFLINE' and clusterName eq 'hq-cluster'"
    )
    assert mock_api.call_args.kwargs["sort"] == "deviceName ASC"


@pytest.mark.asyncio
async def test_get_devices_ap_error_raises_tool_error(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.devices.MonitoringAPs.get_aps",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(ToolError, match="boom"),
    ):
        await tools["central_get_devices"](ctx, device_type="ap")


@pytest.mark.asyncio
async def test_get_device_details_ap_base_uses_original_fetch(tools):
    ctx = make_ctx()
    with (
        patch(
            "utils.monitoring.MonitoringAPs.get_ap_details",
            return_value=dict(RAW_DETAIL_BASE),
        ) as mock_details,
        patch("utils.monitoring.MonitoringAPs.get_ap_radios") as mock_radios,
        patch("utils.monitoring.MonitoringAPs.get_ap_ports") as mock_ports,
    ):
        result = await tools["central_get_device_details"](
            ctx, serial_number="AP123456"
        )
    assert isinstance(result, APDetail)
    assert result.serial_number == "AP123456"
    assert result.client_count == 5
    assert result.radios and result.ports and result.wlans
    mock_details.assert_called_once_with(
        central_conn=ctx.lifespan_context["conn"], serial_number="AP123456"
    )
    mock_radios.assert_not_called()
    mock_ports.assert_not_called()


@pytest.mark.asyncio
async def test_get_device_details_ap_upgrades_radios_and_ports(tools):
    ctx = make_ctx()
    dedicated_radios = {
        "items": [
            {
                "radioNumber": 0,
                "band": "5GHz",
                "channelQuality": 95,
                "clientCount": 3,
            }
        ]
    }
    dedicated_ports = {
        "items": [
            {
                "portIndex": 0,
                "name": "eth0",
                "status": "UP",
                "id": "port-0",
                "type": "ethernet",
                "accessVlan": "-",
                "nativeVlan": "-",
            }
        ]
    }
    with (
        patch(
            "utils.monitoring.MonitoringAPs.get_ap_details",
            return_value=dict(RAW_DETAIL_BASE),
        ),
        patch(
            "utils.monitoring.MonitoringAPs.get_ap_radios",
            return_value=dedicated_radios,
        ) as mock_radios,
        patch(
            "utils.monitoring.MonitoringAPs.get_ap_ports",
            return_value=dedicated_ports,
        ) as mock_ports,
    ):
        result = await tools["central_get_device_details"](
            ctx,
            serial_number="AP123456",
            include=["radios", "ports"],
        )

    mock_radios.assert_called_once()
    mock_ports.assert_called_once()
    assert result.radios and result.radios[0].channel_quality == 95
    assert result.ports and result.ports[0].id == "port-0"
    assert result.ports[0].access_vlan == "-"


@pytest.mark.asyncio
async def test_get_device_details_ap_rejects_gateway_include(tools):
    ctx = make_ctx()
    with pytest.raises(ToolError, match=r"tunnels.*device_type='ap'"):
        await tools["central_get_device_details"](
            ctx, serial_number="AP123456", include=["tunnels"]
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [None, {}])
async def test_get_device_details_ap_not_found_raises_tool_error(tools, raw):
    ctx = make_ctx()
    with (
        patch("utils.monitoring.MonitoringAPs.get_ap_details", return_value=raw),
        pytest.raises(ToolError, match="No AP found"),
    ):
        await tools["central_get_device_details"](ctx, serial_number="MISSING")


@pytest.mark.asyncio
async def test_get_device_details_ap_error_raises_tool_error(tools):
    ctx = make_ctx()
    with (
        patch(
            "utils.monitoring.MonitoringAPs.get_ap_details",
            side_effect=RuntimeError("connection refused"),
        ),
        pytest.raises(ToolError, match="connection refused"),
    ):
        await tools["central_get_device_details"](ctx, serial_number="AP123456")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,metric,identifier,method_name,method_kwarg",
    [
        ("ap", "cpu-utilization", {}, "get_ap_trends", None),
        ("ap", "throughput", {}, "get_ap_trends", None),
        (
            "radio",
            "channel-utilization",
            {"radio_number": 0},
            "get_ap_radio_trends",
            "radio_number",
        ),
        (
            "port",
            "throughput",
            {"port_index": 1},
            "get_ap_port_trends",
            "port_index",
        ),
    ],
)
async def test_get_device_trends_ap_routes_scope_and_metric(
    tools, scope, metric, identifier, method_name, method_kwarg
):
    ctx = make_ctx()
    samples = [{"timestamp": "2026-03-21T12:00:00Z", "value": 10}]
    with patch(
        f"utils.monitoring.MonitoringAPs.{method_name}", return_value=samples
    ) as mock_trends:
        result = await tools["central_get_device_trends"](
            ctx,
            serial_number="AP123456",
            scope=scope,
            metric=metric,
            **identifier,
        )
    assert isinstance(result, DeviceTrendsEnvelope)
    assert result.items[0].timestamp == "2026-03-21T12:00:00Z"
    assert mock_trends.call_args.kwargs["metric"] == metric
    if method_kwarg:
        assert mock_trends.call_args.kwargs[method_kwarg] == next(
            iter(identifier.values())
        )


@pytest.mark.asyncio
async def test_get_device_trends_ap_reports_original_and_returned_points(tools):
    ctx = make_ctx()
    samples = [{"timestamp": f"2026-03-21T12:0{i}:00Z", "value": i} for i in range(3)]
    with patch("utils.monitoring.MonitoringAPs.get_ap_trends", return_value=samples):
        result = await tools["central_get_device_trends"](
            ctx,
            serial_number="AP123456",
            metric="cpu-utilization",
            max_points=2,
        )
    assert result.meta.total_available == 3
    assert result.meta.returned == 2
    assert result.meta.sampled is True
    assert result.truncated is True


@pytest.mark.asyncio
async def test_get_device_trends_ap_empty_is_empty_envelope(tools):
    ctx = make_ctx()
    with patch("utils.monitoring.MonitoringAPs.get_ap_trends", return_value=[]):
        result = await tools["central_get_device_trends"](
            ctx, serial_number="AP123456", metric="cpu-utilization"
        )
    assert result.items == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"scope": "radio", "metric": "channel-utilization"}, "radio_number"),
        ({"scope": "port", "metric": "throughput"}, "port_index"),
        ({"scope": "ap", "metric": "noise-floor"}, "Invalid metric"),
        ({"scope": "ap"}, "require metric"),
    ],
)
async def test_get_device_trends_ap_validation_errors_raise_tool_error(
    tools, kwargs, message
):
    ctx = make_ctx()
    with pytest.raises(ToolError, match=message):
        await tools["central_get_device_trends"](
            ctx, serial_number="AP123456", **kwargs
        )


@pytest.mark.asyncio
async def test_get_device_trends_ap_explicit_window_and_api_error(tools):
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringAPs.get_ap_trends",
        side_effect=RuntimeError("upstream failure"),
    ) as mock_trends:
        with pytest.raises(ToolError, match="upstream failure"):
            await tools["central_get_device_trends"](
                ctx,
                serial_number="AP123456",
                metric="cpu-utilization",
                start_time="2026-03-21T00:00:00.000Z",
                end_time="2026-03-21T23:59:59.999Z",
            )
    assert mock_trends.call_args.kwargs["start_time"] == "2026-03-21T00:00:00.000Z"
    assert mock_trends.call_args.kwargs["end_time"] == "2026-03-21T23:59:59.999Z"


def test_access_point_model_preserves_list_specific_normalization():
    ap = AccessPoint.from_api(RAW_AP)
    assert ap.last_reboot_reason == "AP reboot caused by cold hw reset(power loss)"
    assert ap.client_count == 3
    assert ap.model_dump()["serial_number"] == "AP123456"


def test_ap_detail_model_dump_drops_nulls():
    detail = APDetail.from_api(RAW_DETAIL_BASE)
    dumped = detail.model_dump()
    assert "last_seen_at" not in dumped
    assert dumped["serial_number"] == "AP123456"


def test_apradio_accepts_real_world_string_values():
    radio = APRadio(
        radioNumber=0,
        band="5GHz",
        channelQuality="95",
        channelUtilization="12",
    )
    assert radio.channel_quality == 95


def test_ap_port_accepts_placeholder_vlan_payload():
    port = APPort.from_api(
        {
            "portIndex": 0,
            "name": "eth0",
            "status": "up",
            "speed": "Auto",
            "accessVlan": "-",
            "nativeVlan": "-",
        }
    )
    assert port.access_vlan == "-"
    assert port.native_vlan == "-"
    assert port.speed == "Auto"


def test_ap_detail_accepts_poe_class_negotiated_power():
    detail = APDetail.from_api(
        {
            "serialNumber": "AP123456",
            "status": "ONLINE",
            "negotiatedPower": "802.3at",
            "apStats": [
                {"clientCount": 1, "cpuUtilization": 6, "memoryUtilization": 40}
            ],
        }
    )
    assert detail.negotiated_power == "802.3at"
    assert detail.cpu_utilization == 6
    assert detail.client_count == 1
