from unittest.mock import patch

import pytest

import tools.ap_monitoring as mod
from models import WLAN, AccessPoint, AccessPointStatistics
from tests.conftest import FakeMCP, make_ctx

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
    "ipv6": "",
    "macAddress": "8c:79:09:c3:53:40",
    "cpuUtilization": 12,
    "memoryUtilization": 45,
    "powerConsumption": 8.5,
    "clientCount": 3,
    "lastRebootReason": "COLD_HW_RESET",
    "publicIpv4": "61.246.230.194",
    "lastSeenAt": None,
    # These should be silently ignored by the model:
    "type": "network-monitoring/access-point-monitoring",
    "id": "AP123456",
    "buildingId": "",
    "floorId": "",
    "deviceGroupId": "",
    "deviceGroupName": "",
}

RAW_STATS = {
    "timestamp": "2026-03-21T10:00:00.000Z",
    "cpuUtilization": 44,
    "memoryUtilization": 61,
    "powerConsumption": 12,
}


@pytest.fixture
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


def test_registers_ap_tools(tools):
    assert "central_get_aps" in tools
    assert "central_get_ap_statistics" in tools
    assert "central_get_ap_wlans" in tools


@pytest.mark.asyncio
async def test_get_aps_no_filters(tools):
    ctx = make_ctx()
    with patch("tools.ap_monitoring.MonitoringAPs.get_all_aps", return_value=[RAW_AP]) as mock_api:
        result = await tools["central_get_aps"](ctx)
    assert isinstance(result, list)
    assert isinstance(result[0], AccessPoint)
    assert result[0].serial_number == "AP123456"
    serialized = result[0].model_dump()
    assert serialized["serial_number"] == "AP123456"
    assert serialized["status"] == "ONLINE"
    assert serialized["client_count"] == 3
    assert serialized["last_reboot_reason"] == "AP reboot caused by cold hw reset(power loss)"
    assert serialized["public_ipv4"] == "61.246.230.194"
    assert serialized["cpu_utilization"] == 12
    assert serialized["memory_utilization"] == 45
    assert serialized["power_consumption"] == 8.5
    assert "uptime_in_millis" not in serialized
    assert "notes" not in serialized
    assert "type" not in serialized
    assert "id" not in serialized
    assert "last_seen_at" not in serialized
    call_kwargs = mock_api.call_args.kwargs
    assert call_kwargs["filter_str"] is None
    assert call_kwargs["sort"] is None


@pytest.mark.asyncio
async def test_get_aps_reboot_reason_key_is_mapped_to_description(tools):
    ctx = make_ctx()
    raw = {"serialNumber": "AP000001", "status": "ONLINE", "lastRebootReason": "POWER_LOSS"}
    with patch("tools.ap_monitoring.MonitoringAPs.get_all_aps", return_value=[raw]):
        result = await tools["central_get_aps"](ctx)
    assert result[0].last_reboot_reason == "AP rebooted due to loss power"


@pytest.mark.asyncio
async def test_get_aps_reboot_reason_unknown_key_is_passed_through(tools):
    ctx = make_ctx()
    raw = {"serialNumber": "AP000002", "status": "ONLINE", "lastRebootReason": "SOME_FUTURE_KEY"}
    with patch("tools.ap_monitoring.MonitoringAPs.get_all_aps", return_value=[raw]):
        result = await tools["central_get_aps"](ctx)
    assert result[0].last_reboot_reason == "SOME_FUTURE_KEY"


@pytest.mark.asyncio
async def test_get_aps_offline_payload_keeps_last_seen_at(tools):
    ctx = make_ctx()
    raw_offline_ap = {
        "serialNumber": "AP123456",
        "status": "OFFLINE",
        "lastSeenAt": "2026-03-21T10:00:00.000Z",
    }
    with patch(
        "tools.ap_monitoring.MonitoringAPs.get_all_aps",
        return_value=[raw_offline_ap],
    ):
        result = await tools["central_get_aps"](ctx, status="OFFLINE")

    serialized = result[0].model_dump()
    assert serialized["status"] == "OFFLINE"
    assert serialized["last_seen_at"] == "2026-03-21T10:00:00.000Z"
    assert "uptime_in_millis" not in serialized
    assert "cpu_utilization" not in serialized


@pytest.mark.asyncio
async def test_get_aps_null_optional_fields_are_excluded(tools):
    ctx = make_ctx()
    raw_sparse_ap = {
        "serialNumber": "AP999999",
        "status": "ONLINE",
    }
    with patch(
        "tools.ap_monitoring.MonitoringAPs.get_all_aps",
        return_value=[raw_sparse_ap],
    ):
        result = await tools["central_get_aps"](ctx)

    serialized = result[0].model_dump()
    assert serialized == {"serial_number": "AP999999", "status": "ONLINE"}
    assert "client_count" not in serialized
    assert "last_reboot_reason" not in serialized
    assert "public_ipv4" not in serialized
    assert "uptime_in_millis" not in serialized
    assert "notes" not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_arg,tool_value,expected_filter",
    [
        ("site_id", "site-1", "siteId eq 'site-1'"),
        ("site_name", "HQ", "siteName eq 'HQ'"),
        ("serial_number", "AP123456", "serialNumber eq 'AP123456'"),
        ("device_name", "ap-lobby-01", "deviceName eq 'ap-lobby-01'"),
        ("status", "ONLINE", "status eq 'ONLINE'"),
        ("model", "AP-635", "model eq 'AP-635'"),
        ("firmware_version", "10.6.0.2", "firmwareVersion eq '10.6.0.2'"),
        ("deployment", "Standalone", "deployment eq 'Standalone'"),
        ("cluster_id", "cluster-1", "clusterId eq 'cluster-1'"),
        ("cluster_name", "hq-cluster", "clusterName eq 'hq-cluster'"),
    ],
)
async def test_get_aps_filter_field_mappings(tools, tool_arg, tool_value, expected_filter):
    ctx = make_ctx()
    with patch("tools.ap_monitoring.MonitoringAPs.get_all_aps", return_value=[]) as mock_api:
        await tools["central_get_aps"](ctx, **{tool_arg: tool_value})
    assert mock_api.call_args.kwargs["filter_str"] == expected_filter


@pytest.mark.asyncio
async def test_get_aps_multi_value_in_filter(tools):
    ctx = make_ctx()
    with patch("tools.ap_monitoring.MonitoringAPs.get_all_aps", return_value=[]) as mock_api:
        await tools["central_get_aps"](ctx, serial_number="AP1,AP2")
    assert mock_api.call_args.kwargs["filter_str"] == "serialNumber in ('AP1', 'AP2')"


@pytest.mark.asyncio
async def test_get_aps_combined_filters(tools):
    ctx = make_ctx()
    with patch("tools.ap_monitoring.MonitoringAPs.get_all_aps", return_value=[]) as mock_api:
        await tools["central_get_aps"](
            ctx,
            site_id="site-1",
            status="ONLINE",
            cluster_name="hq-cluster",
            sort="deviceName asc",
        )
    filter_str = mock_api.call_args.kwargs["filter_str"]
    assert "siteId eq 'site-1'" in filter_str
    assert "status eq 'ONLINE'" in filter_str
    assert "clusterName eq 'hq-cluster'" in filter_str
    assert " and " in filter_str
    assert mock_api.call_args.kwargs["sort"] == "deviceName asc"


@pytest.mark.asyncio
async def test_get_aps_empty_returns_string(tools):
    ctx = make_ctx()
    with patch("tools.ap_monitoring.MonitoringAPs.get_all_aps", return_value=[]):
        result = await tools["central_get_aps"](ctx, site_id="missing")
    assert result == "No access points found matching the specified criteria."


@pytest.mark.asyncio
async def test_get_aps_error_returns_formatted_error(tools):
    ctx = make_ctx()
    with patch(
        "tools.ap_monitoring.MonitoringAPs.get_all_aps",
        side_effect=Exception("boom"),
    ):
        result = await tools["central_get_aps"](ctx)
    assert result == "Error fetching access points: boom"


@pytest.mark.asyncio
async def test_get_ap_statistics_success(tools):
    ctx = make_ctx()
    with patch(
        "tools.ap_monitoring.MonitoringAPs.get_ap_stats",
        return_value=[RAW_STATS],
    ) as mock_api:
        result = await tools["central_get_ap_statistics"](ctx, serial_number="AP123456")
    assert isinstance(result, list)
    assert isinstance(result[0], AccessPointStatistics)
    assert result[0].cpu_utilization == 44
    serialized = result[0].model_dump()
    assert serialized["cpu_utilization"] == 44
    assert "cpuUtilization" not in serialized
    assert mock_api.call_args.kwargs["serial_number"] == "AP123456"
    assert mock_api.call_args.kwargs["start_time"] is not None
    assert mock_api.call_args.kwargs["end_time"] is not None


def test_access_point_statistics_uses_snake_case_for_output():
    stat = AccessPointStatistics(
        timestamp="2026-03-21T10:00:00.000Z",
        cpuUtilization=44,
        memoryUtilization=61,
        powerConsumption=12,
    )

    assert stat.model_dump() == {
        "timestamp": "2026-03-21T10:00:00.000Z",
        "cpu_utilization": 44,
        "memory_utilization": 61,
        "power_consumption": 12,
    }
    assert stat.model_dump(by_alias=True) == {
        "timestamp": "2026-03-21T10:00:00.000Z",
        "cpu_utilization": 44,
        "memory_utilization": 61,
        "power_consumption": 12,
    }


@pytest.mark.asyncio
async def test_get_ap_statistics_parse_error_returns_formatted_error(tools):
    ctx = make_ctx()
    with patch(
        "tools.ap_monitoring.MonitoringAPs.get_ap_stats",
        return_value=[{"cpuUtilization": 44}],
    ):
        result = await tools["central_get_ap_statistics"](ctx, serial_number="AP123456")
    assert result.startswith("Error parsing access point statistics:")


@pytest.mark.asyncio
async def test_get_ap_statistics_explicit_time_window(tools):
    ctx = make_ctx()
    with patch(
        "tools.ap_monitoring.MonitoringAPs.get_ap_stats",
        return_value=[RAW_STATS],
    ) as mock_api:
        await tools["central_get_ap_statistics"](
            ctx,
            serial_number="AP123456",
            start_time="2026-03-21T00:00:00.000Z",
            end_time="2026-03-21T23:59:59.999Z",
        )
    assert (
        mock_api.call_args.kwargs["start_time"] == "2026-03-21T00:00:00.000Z"
    )
    assert mock_api.call_args.kwargs["end_time"] == "2026-03-21T23:59:59.999Z"


@pytest.mark.asyncio
async def test_get_ap_statistics_empty_returns_string(tools):
    ctx = make_ctx()
    with patch(
        "tools.ap_monitoring.MonitoringAPs.get_ap_stats",
        return_value=[],
    ):
        result = await tools["central_get_ap_statistics"](ctx, serial_number="AP123456")
    assert result == "No AP statistics found for serial number 'AP123456'."


@pytest.mark.asyncio
async def test_get_ap_statistics_error_returns_formatted_error(tools):
    ctx = make_ctx()
    with patch(
        "tools.ap_monitoring.MonitoringAPs.get_ap_stats",
        side_effect=Exception("stats unavailable"),
    ):
        result = await tools["central_get_ap_statistics"](ctx, serial_number="AP123456")
    assert result == "Error fetching access point statistics: stats unavailable"


RAW_WLAN = {
    "id": "wlan-1",
    "wlanName": "Corp-WiFi",
    "primaryUsage": "employee",
    "securityLevel": "Enterprise",
    "security": "WPA3",
    "band": "5GHz",
    "status": "enabled",
    "vlan": "10",
    "type": "standard",
}

RAW_WLAN_2 = {
    "id": "wlan-2",
    "wlanName": "Guest-WiFi",
    "primaryUsage": "guest",
    "securityLevel": "Personal",
    "security": "WPA2",
    "band": "2.4GHz",
    "status": "enabled",
    "vlan": "20",
    "type": "standard",
}


@pytest.mark.asyncio
async def test_get_ap_wlans_success(tools):
    ctx = make_ctx()
    with patch(
        "tools.ap_monitoring.MonitoringAPs.get_ap_wlans",
        return_value={"items": [RAW_WLAN, RAW_WLAN_2]},
    ) as mock_api:
        result = await tools["central_get_ap_wlans"](ctx, serial_number="AP123456")
    assert isinstance(result, list)
    assert len(result) == 2
    assert isinstance(result[0], WLAN)
    assert mock_api.call_args.kwargs["serial_number"] == "AP123456"


@pytest.mark.asyncio
async def test_get_ap_wlans_wlan_name_filter(tools):
    ctx = make_ctx()
    with patch(
        "tools.ap_monitoring.MonitoringAPs.get_ap_wlans",
        return_value={"items": [RAW_WLAN, RAW_WLAN_2]},
    ):
        result = await tools["central_get_ap_wlans"](
            ctx, serial_number="AP123456", wlan_name="Corp-WiFi"
        )
    assert len(result) == 1
    assert result[0].wlan_name == "Corp-WiFi"


@pytest.mark.asyncio
async def test_get_ap_wlans_empty_returns_string(tools):
    ctx = make_ctx()
    with patch(
        "tools.ap_monitoring.MonitoringAPs.get_ap_wlans",
        return_value={"items": []},
    ):
        result = await tools["central_get_ap_wlans"](ctx, serial_number="AP123456")
    assert result == "No WLANs found for AP 'AP123456'."


@pytest.mark.asyncio
async def test_get_ap_wlans_error_returns_formatted_error(tools):
    ctx = make_ctx()
    with patch(
        "tools.ap_monitoring.MonitoringAPs.get_ap_wlans",
        side_effect=Exception("AP unreachable"),
    ):
        result = await tools["central_get_ap_wlans"](ctx, serial_number="AP123456")
    assert result == "Error fetching AP WLANs: AP unreachable"
