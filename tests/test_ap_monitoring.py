from unittest.mock import patch

import pytest

import tools.ap_monitoring as mod
from models import AccessPoint, APDetail, APPort, APRadio, TrendSample
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

# Realistic base detail dict — no dedicated radios/ports yet
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


@pytest.fixture
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_registers_ap_tools(tools):
    assert "central_get_aps" in tools
    assert "central_get_ap_details" in tools
    assert "central_get_ap_trends" in tools
    assert "central_get_ap_statistics" not in tools
    assert "central_get_ap_wlans" not in tools


# ---------------------------------------------------------------------------
# central_get_aps (unchanged)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# central_get_ap_details
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_ap_details_base_only(tools):
    """Base snapshot (no include) returns APDetail; dedicated radios/ports not called."""
    ctx = make_ctx()
    with (
        patch(
            "utils.monitoring.MonitoringAPs.get_ap_details",
            return_value=dict(RAW_DETAIL_BASE),
        ) as mock_details,
        patch("utils.monitoring.MonitoringAPs.get_ap_radios") as mock_radios,
        patch("utils.monitoring.MonitoringAPs.get_ap_ports") as mock_ports,
    ):
        result = await tools["central_get_ap_details"](ctx, serial_number="AP123456")

    assert isinstance(result, APDetail)
    assert result.serial_number == "AP123456"
    assert result.client_count == 5
    assert result.cpu_utilization == 20
    mock_details.assert_called_once()
    mock_radios.assert_not_called()
    mock_ports.assert_not_called()

    serialized = result.model_dump()
    # radios are embedded from base (not None), so they will be present
    assert "radios" in serialized
    # wlans are embedded too
    assert "wlans" in serialized


@pytest.mark.asyncio
async def test_get_ap_details_include_radios(tools):
    """include=['radios'] calls get_ap_radios and returns richer radio data."""
    ctx = make_ctx()
    dedicated_radios = {
        "items": [
            {
                "radioNumber": 0,
                "band": "5GHz",
                "channelQuality": 95,
                "clientCount": 3,
                "noiseFloor": -88,
                "channelUtilization": 12,
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
        patch("utils.monitoring.MonitoringAPs.get_ap_ports") as mock_ports,
    ):
        result = await tools["central_get_ap_details"](
            ctx, serial_number="AP123456", include=["radios"]
        )

    assert isinstance(result, APDetail)
    mock_radios.assert_called_once()
    mock_ports.assert_not_called()
    # richer radio data should be reflected
    assert result.radios is not None
    assert result.radios[0].channel_quality == 95
    assert result.radios[0].client_count == 3


@pytest.mark.asyncio
async def test_get_ap_details_include_radios_and_ports(tools):
    """include=['radios', 'ports'] calls both dedicated methods."""
    ctx = make_ctx()
    dedicated_radios = {"items": [{"radioNumber": 0, "band": "5GHz", "channelQuality": 80}]}
    dedicated_ports = {"items": [{"portIndex": 0, "name": "eth0", "status": "UP", "id": "port-0", "type": "ethernet"}]}
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
        result = await tools["central_get_ap_details"](
            ctx, serial_number="AP123456", include=["radios", "ports"]
        )

    assert isinstance(result, APDetail)
    mock_radios.assert_called_once()
    mock_ports.assert_called_once()
    assert result.ports is not None
    assert result.ports[0].id == "port-0"


@pytest.mark.asyncio
async def test_get_ap_details_not_found(tools):
    """fetch_snapshot returning falsy value yields a 'not found' message."""
    ctx = make_ctx()
    with patch("utils.monitoring.MonitoringAPs.get_ap_details", return_value=None):
        result = await tools["central_get_ap_details"](ctx, serial_number="MISSING")
    assert "No AP found for serial number 'MISSING'" in result


@pytest.mark.asyncio
async def test_get_ap_details_empty_dict_not_found(tools):
    """fetch_snapshot returning empty dict also yields a 'not found' message."""
    ctx = make_ctx()
    with patch("utils.monitoring.MonitoringAPs.get_ap_details", return_value={}):
        result = await tools["central_get_ap_details"](ctx, serial_number="MISSING2")
    assert "No AP found for serial number 'MISSING2'" in result


@pytest.mark.asyncio
async def test_get_ap_details_fetch_error(tools):
    """Exception from get_ap_details is returned as a formatted error string."""
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringAPs.get_ap_details",
        side_effect=Exception("connection refused"),
    ):
        result = await tools["central_get_ap_details"](ctx, serial_number="AP123456")
    assert "Error fetching AP details" in result
    assert "connection refused" in result


# ---------------------------------------------------------------------------
# central_get_ap_trends
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_ap_trends_ap_cpu(tools):
    """scope='ap' metric='cpu-utilization': returns list[TrendSample] with cpu_utilization."""
    ctx = make_ctx()
    samples = [{"timestamp": "2026-06-01T17:50:00Z", "cpu_utilization": 6}]
    with patch(
        "utils.monitoring.MonitoringAPs.get_ap_trends",
        return_value=samples,
    ) as mock_trends:
        result = await tools["central_get_ap_trends"](
            ctx,
            serial_number="AP123456",
            metric="cpu-utilization",
            scope="ap",
        )

    assert isinstance(result, list)
    assert isinstance(result[0], TrendSample)
    assert result[0].model_dump()["cpu_utilization"] == 6
    call_kwargs = mock_trends.call_args.kwargs
    assert call_kwargs["start_time"] is not None
    assert call_kwargs["end_time"] is not None


@pytest.mark.asyncio
async def test_get_ap_trends_ap_throughput(tools):
    """scope='ap' metric='throughput': tx and rx are preserved in TrendSample."""
    ctx = make_ctx()
    samples = [{"timestamp": "2026-06-01T17:50:00Z", "tx": 1000, "rx": 2000}]
    with patch(
        "utils.monitoring.MonitoringAPs.get_ap_trends",
        return_value=samples,
    ):
        result = await tools["central_get_ap_trends"](
            ctx,
            serial_number="AP123456",
            metric="throughput",
            scope="ap",
        )

    assert isinstance(result, list)
    dumped = result[0].model_dump()
    assert dumped["tx"] == 1000
    assert dumped["rx"] == 2000


@pytest.mark.asyncio
async def test_get_ap_trends_radio_channel_utilization(tools):
    """scope='radio' with radio_number calls get_ap_radio_trends."""
    ctx = make_ctx()
    samples = [{"timestamp": "2026-06-01T17:50:00Z", "tx": 0, "rx": 7, "non_wifi_interference": 1}]
    with patch(
        "utils.monitoring.MonitoringAPs.get_ap_radio_trends",
        return_value=samples,
    ) as mock_radio_trends:
        result = await tools["central_get_ap_trends"](
            ctx,
            serial_number="AP123456",
            metric="channel-utilization",
            scope="radio",
            radio_number=0,
        )

    assert isinstance(result, list)
    assert result[0].model_dump()["rx"] == 7
    assert mock_radio_trends.call_args.kwargs["radio_number"] == 0


@pytest.mark.asyncio
async def test_get_ap_trends_radio_missing_radio_number(tools):
    """scope='radio' without radio_number returns a formatted error containing 'radio_number'."""
    ctx = make_ctx()
    result = await tools["central_get_ap_trends"](
        ctx,
        serial_number="AP123456",
        metric="channel-utilization",
        scope="radio",
    )
    assert isinstance(result, str)
    assert "radio_number" in result


@pytest.mark.asyncio
async def test_get_ap_trends_port_missing_port_index(tools):
    """scope='port' without port_index returns a formatted error containing 'port_index'."""
    ctx = make_ctx()
    result = await tools["central_get_ap_trends"](
        ctx,
        serial_number="AP123456",
        metric="throughput",
        scope="port",
    )
    assert isinstance(result, str)
    assert "port_index" in result


@pytest.mark.asyncio
async def test_get_ap_trends_invalid_metric_for_scope(tools):
    """scope='ap' with a radio metric returns a formatted error naming a valid ap metric."""
    ctx = make_ctx()
    result = await tools["central_get_ap_trends"](
        ctx,
        serial_number="AP123456",
        metric="noise-floor",
        scope="ap",
    )
    assert isinstance(result, str)
    # error should mention a valid ap metric as hint
    assert "cpu-utilization" in result


@pytest.mark.asyncio
async def test_get_ap_trends_explicit_time_window(tools):
    """Explicit start_time/end_time are passed through to the underlying API call."""
    ctx = make_ctx()
    samples = [{"timestamp": "2026-03-21T12:00:00Z", "cpu_utilization": 10}]
    with patch(
        "utils.monitoring.MonitoringAPs.get_ap_trends",
        return_value=samples,
    ) as mock_trends:
        await tools["central_get_ap_trends"](
            ctx,
            serial_number="AP123456",
            metric="cpu-utilization",
            scope="ap",
            start_time="2026-03-21T00:00:00.000Z",
            end_time="2026-03-21T23:59:59.999Z",
        )

    assert mock_trends.call_args.kwargs["start_time"] == "2026-03-21T00:00:00.000Z"
    assert mock_trends.call_args.kwargs["end_time"] == "2026-03-21T23:59:59.999Z"


@pytest.mark.asyncio
async def test_get_ap_trends_empty_result(tools):
    """Empty API response returns a 'no trend data found' message."""
    ctx = make_ctx()
    with patch("utils.monitoring.MonitoringAPs.get_ap_trends", return_value=[]):
        result = await tools["central_get_ap_trends"](
            ctx,
            serial_number="AP123456",
            metric="cpu-utilization",
            scope="ap",
        )
    assert "No ap trend data found for serial number 'AP123456'" in result


@pytest.mark.asyncio
async def test_get_ap_trends_api_exception(tools):
    """RuntimeError from the API is returned as a formatted 'fetching AP trends' error."""
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringAPs.get_ap_trends",
        side_effect=RuntimeError("upstream failure"),
    ):
        result = await tools["central_get_ap_trends"](
            ctx,
            serial_number="AP123456",
            metric="cpu-utilization",
            scope="ap",
        )
    assert "Error fetching AP trends" in result
    assert "upstream failure" in result


# ---------------------------------------------------------------------------
# Model sparse-serialization behaviour
# ---------------------------------------------------------------------------


def test_ap_detail_model_dump_nulls_dropped():
    """APDetail.model_dump() excludes null fields."""
    detail = APDetail.from_api(
        {
            "serialNumber": "AP999",
            "status": "ONLINE",
            "apStats": [{"clientCount": 2, "cpuUtilization": 5, "memoryUtilization": 30}],
        }
    )
    serialized = detail.model_dump()
    assert serialized["serial_number"] == "AP999"
    assert serialized["client_count"] == 2
    # Null detail-only fields should be absent
    assert "manufacturer" not in serialized
    assert "notes" not in serialized
    assert "mesh_role" not in serialized
    # Embedded lists not present in raw → should be absent
    assert "radios" not in serialized
    assert "ports" not in serialized
    assert "wlans" not in serialized


def test_trend_sample_model_dump_nulls_dropped():
    """TrendSample.model_dump() preserves extra fields and drops nulls."""
    sample = TrendSample(**{"timestamp": "2026-06-01T17:50:00Z", "cpu_utilization": 6})
    dumped = sample.model_dump()
    assert dumped["timestamp"] == "2026-06-01T17:50:00Z"
    assert dumped["cpu_utilization"] == 6
    # No unexpected None keys
    assert all(v is not None for v in dumped.values())


def test_trend_sample_multi_key():
    """TrendSample preserves multiple dynamic keys (e.g. tx + rx)."""
    sample = TrendSample(**{"timestamp": "t", "tx": 100, "rx": 200})
    dumped = sample.model_dump()
    assert dumped["tx"] == 100
    assert dumped["rx"] == 200


def test_apradio_accepts_real_world_string_values():
    """Regression: a20 returns unit/display strings for some radio fields.

    The live API returns e.g. bandwidth='20 MHz', power='20 dBm',
    spatial_stream='2x2:2'. These must not be coerced to numeric types or
    parsing the whole AP detail fails.
    """
    radio = APRadio.from_api(
        {
            "radioNumber": 1,
            "band": "2.4 GHz",
            "bandwidth": "20 MHz",
            "power": "20 dBm",
            "spatialStream": "2x2:2",
            "radioStats": [{"noiseFloor": "0", "channelUtilization": "0"}],
        }
    )
    dumped = radio.model_dump()
    assert dumped["bandwidth"] == "20 MHz"
    assert dumped["power"] == "20 dBm"
    assert dumped["spatial_stream"] == "2x2:2"
    # radioStats[0] flattened to top-level numeric values
    assert dumped["noise_floor"] == 0
    assert dumped["channel_utilization"] == 0


def test_applport_accepts_placeholder_vlan_values():
    """Regression: a20 ports use '-' placeholders for unset VLAN fields."""
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
    dumped = port.model_dump()
    assert dumped["access_vlan"] == "-"
    assert dumped["native_vlan"] == "-"
    assert dumped["speed"] == "Auto"


def test_apdetail_accepts_poe_class_negotiated_power():
    """Regression: negotiatedPower can be a PoE class string like '802.3at'."""
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
    dumped = detail.model_dump()
    assert dumped["negotiated_power"] == "802.3at"
    # apStats flattened into inherited AccessPoint fields
    assert dumped["cpu_utilization"] == 6
    assert dumped["client_count"] == 1
