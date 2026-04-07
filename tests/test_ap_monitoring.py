from unittest.mock import patch

import pytest

import tools.ap_monitoring as mod
from models import AccessPoint
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


@pytest.mark.asyncio
async def test_get_aps_no_filters(tools):
    ctx = make_ctx()
    with patch("tools.ap_monitoring.MonitoringAPs.get_all_aps", return_value=[RAW_AP]) as mock_api:
        result = await tools["central_get_aps"](ctx)
    assert isinstance(result, list)
    assert isinstance(result[0], AccessPoint)
    assert result[0].serial_number == "AP123456"
    call_kwargs = mock_api.call_args.kwargs
    assert call_kwargs["filter_str"] is None
    assert call_kwargs["sort"] is None


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
    assert result[0]["cpuUtilization"] == 44
    assert mock_api.call_args.kwargs["serial_number"] == "AP123456"
    assert mock_api.call_args.kwargs["start_time"] is not None
    assert mock_api.call_args.kwargs["end_time"] is not None


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
