"""Tests for tools/switch_monitoring.py — central_get_switches, central_get_switch_details,
central_get_switch_trends.
"""

from unittest.mock import MagicMock, patch

import pytest

import tools.switch_monitoring as mod
from models import Switch, SwitchDetail, TrendSample
from tests.conftest import FakeMCP, make_ctx

# ---------------------------------------------------------------------------
# Representative raw payloads (from a20-switch-monitoring-payloads.md)
# ---------------------------------------------------------------------------

RAW_SWITCH_TPD = {
    "stackId": None,
    "model": "WS-C3850-12X48U-E",
    "siteId": "34011151398",
    "siteName": "Mexico City (MEX) - Branch",
    "switchRole": "Standalone",
    "switchTrends": [
        {
            "systemTemperature": 0,
            "poeAvailable": 0,
            "poeConsumption": 0,
            "powerConsumption": 0,
            "totalPowerConsumption": 0,
            "upLinkPorts": None,
            "cpuUtilization": 2,
            "memoryUtilization": 35,
            "usage": 1725726,
        }
    ],
    "firmwareVersion": "Everest 16.6.2",
    "lastSeenAt": 0,
    "uptimeInMillis": 3628003016,
    "serialNumber": "FCW2026D0KV",
    "deviceName": "BO-MEX-EGSW02.owl.direct",
    "type": "network-monitoring/switch-monitoring",
    "deployment": "Standalone",
    "status": "Online",
    "ipv6": None,
    "id": "FCW2026D0KV",
    "jNumber": None,
    "publicIp": "10.128.235.11",
    "macAddress": "94:d4:69:46:74:72",
    "ipv4": "10.128.235.11",
    "stackMemberId": 0,
    "switchType": "tpd",
}

RAW_SWITCH_STACK_CONDUCTOR = {
    "stackId": "e8a387e6-2c8d-414a-93d1-2927ea07471e",
    "model": "CX-6300M",
    "siteId": "site-lhr",
    "siteName": "London (LHR) - Campus",
    "switchRole": "Conductor",
    "switchTrends": [
        {
            "cpuUtilization": 5,
            "memoryUtilization": 42,
            "poeAvailable": 370,
            "poeConsumption": 30,
            "powerConsumption": 80,
            "totalPowerConsumption": 110,
            "upLinkPorts": "['1/1/27','1/1/28']",
            "usage": 9876543,
        }
    ],
    "firmwareVersion": "10.12.0001",
    "lastSeenAt": 0,
    "uptimeInMillis": 86400000,
    "serialNumber": "SG34L5002Y",
    "deviceName": "LHR-SW-01",
    "type": "network-monitoring/switch-monitoring",
    "deployment": "Stack",
    "status": "Online",
    "ipv6": None,
    "id": "SG34L5002Y",
    "jNumber": None,
    "publicIp": "192.0.2.10",
    "macAddress": "aa:bb:cc:dd:ee:ff",
    "ipv4": "192.168.1.10",
    "stackMemberId": 1,
    "switchType": "cx",
}

RAW_DETAIL_BASE = {
    **RAW_SWITCH_TPD,
    "health": "Good",
    "healthReasons": {"poorReasons": [], "fairReasons": []},
    "manufacturer": "Cisco",
    "lastRestartReason": "PowerUp",
    "configStatus": "In Sync",
    "switchLinkType": None,
    "lastConfigChange": "2026-06-01T00:00:00Z",
}

# Hardware trend samples from capture doc (values are strings)
RAW_HARDWARE_TRENDS = [
    {
        "timestamp": "2026-06-05T21:05:00Z",
        "serialNumber": "FCW2026D0KV",
        "cpuUtilization": "2",
        "memoryUtilization": "35",
        "systemTemperature": "0",
        "poeAvailable": "0",
        "poeConsumption": "0",
        "powerConsumption": "0",
        "totalPowerConsumption": "0",
    },
    {
        "timestamp": "2026-06-05T21:10:00Z",
        "serialNumber": "FCW2026D0KV",
        "cpuUtilization": "3",
        "memoryUtilization": "36",
        "systemTemperature": "0",
        "poeAvailable": "0",
        "poeConsumption": "0",
        "powerConsumption": "0",
        "totalPowerConsumption": "0",
    },
    # sentinel — only timestamp
    {"timestamp": "2026-06-05T22:05:00Z"},
]

# Interface trend samples (values are strings)
RAW_INTERFACE_TRENDS = [
    {
        "timestamp": "2026-06-05T21:05:00Z",
        "rxBytes": "89027",
        "txBytes": "84434",
        "inErrors": "0",
        "outErrors": "0",
        "inDiscards": "0",
        "outDiscards": "0",
        "inFcs": "0",
        "inCrcErrors": "0",
        "inFragmented": "0",
        "outCollision": "0",
        "inRunts": "0",
        "inGiants": "0",
    },
    # sentinel
    {"timestamp": "2026-06-05T22:05:00Z"},
]


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_registers_switch_tools(tools):
    assert "central_get_switches" in tools
    assert "central_get_switch_details" in tools
    assert "central_get_switch_trends" in tools
    # No other tools leaked
    assert len(tools) == 3


# ---------------------------------------------------------------------------
# central_get_switches — filter construction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_arg,tool_value,expected_filter",
    [
        ("site_id", "34011151398", "siteId eq '34011151398'"),
        ("site_name", "Mexico City (MEX) - Branch", "siteName eq 'Mexico City (MEX) - Branch'"),
        ("model", "WS-C3850-12X48U-E", "model eq 'WS-C3850-12X48U-E'"),
        ("status", "Online", "status eq 'Online'"),
        ("deployment", "Standalone", "deployment eq 'Standalone'"),
    ],
)
async def test_get_switches_filter_field_mappings(tools, tool_arg, tool_value, expected_filter):
    ctx = make_ctx()
    with patch(
        "tools.switch_monitoring.MonitoringSwitches.get_all_switches", return_value=[]
    ) as mock_api:
        await tools["central_get_switches"](ctx, **{tool_arg: tool_value})
    assert mock_api.call_args.kwargs["filter_str"] == expected_filter


@pytest.mark.asyncio
async def test_get_switches_no_filters_passes_none_filter(tools):
    ctx = make_ctx()
    with patch(
        "tools.switch_monitoring.MonitoringSwitches.get_all_switches",
        return_value=[RAW_SWITCH_TPD],
    ) as mock_api:
        result = await tools["central_get_switches"](ctx)
    assert mock_api.call_args.kwargs["filter_str"] is None
    assert mock_api.call_args.kwargs["sort"] is None
    assert isinstance(result, list)
    assert isinstance(result[0], Switch)
    assert result[0].serial_number == "FCW2026D0KV"


@pytest.mark.asyncio
async def test_get_switches_title_case_status_literal(tools):
    """Status filter must be 'Online' not 'ONLINE' — title-case verified live."""
    ctx = make_ctx()
    with patch(
        "tools.switch_monitoring.MonitoringSwitches.get_all_switches", return_value=[]
    ) as mock_api:
        await tools["central_get_switches"](ctx, status="Online")
    assert mock_api.call_args.kwargs["filter_str"] == "status eq 'Online'"


@pytest.mark.asyncio
async def test_get_switches_combined_filters(tools):
    ctx = make_ctx()
    with patch(
        "tools.switch_monitoring.MonitoringSwitches.get_all_switches", return_value=[]
    ) as mock_api:
        await tools["central_get_switches"](
            ctx,
            site_id="34011151398",
            status="Online",
            deployment="Stack",
            sort="deviceName asc",
        )
    filter_str = mock_api.call_args.kwargs["filter_str"]
    assert "siteId eq '34011151398'" in filter_str
    assert "status eq 'Online'" in filter_str
    assert "deployment eq 'Stack'" in filter_str
    assert " and " in filter_str
    assert mock_api.call_args.kwargs["sort"] == "deviceName ASC"


@pytest.mark.asyncio
async def test_get_switches_empty_returns_string(tools):
    ctx = make_ctx()
    with patch(
        "tools.switch_monitoring.MonitoringSwitches.get_all_switches", return_value=[]
    ):
        result = await tools["central_get_switches"](ctx, site_id="missing")
    assert result == "No switches found matching the specified criteria."


@pytest.mark.asyncio
async def test_get_switches_fetch_error_returns_formatted_error(tools):
    ctx = make_ctx()
    with patch(
        "tools.switch_monitoring.MonitoringSwitches.get_all_switches",
        side_effect=Exception("network timeout"),
    ):
        result = await tools["central_get_switches"](ctx)
    assert "Error fetching switches" in result
    assert "network timeout" in result


@pytest.mark.asyncio
async def test_get_switches_parse_error_returns_formatted_error(tools):
    ctx = make_ctx()
    # Provide a list where parsing fails (missing required serialNumber field)
    with patch(
        "tools.switch_monitoring.MonitoringSwitches.get_all_switches",
        return_value=[{"model": "CX-6300M"}],  # no serialNumber → validation error
    ):
        result = await tools["central_get_switches"](ctx)
    assert isinstance(result, str)
    assert "Error parsing switch data" in result


# ---------------------------------------------------------------------------
# central_get_switches — payload validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_switches_tpd_switch_fields(tools):
    """All key fields from the captured tpd payload are correctly mapped."""
    ctx = make_ctx()
    with patch(
        "tools.switch_monitoring.MonitoringSwitches.get_all_switches",
        return_value=[RAW_SWITCH_TPD],
    ):
        result = await tools["central_get_switches"](ctx)

    sw = result[0]
    assert sw.serial_number == "FCW2026D0KV"
    assert sw.model == "WS-C3850-12X48U-E"
    assert sw.status == "Online"
    assert sw.deployment == "Standalone"
    assert sw.switch_type == "tpd"
    assert sw.switch_role == "Standalone"
    assert sw.site_id == "34011151398"
    assert sw.site_name == "Mexico City (MEX) - Branch"
    # switchTrends embedded
    assert sw.switch_trends is not None
    assert len(sw.switch_trends) == 1
    assert sw.switch_trends[0].cpu_utilization == 2
    assert sw.switch_trends[0].memory_utilization == 35
    assert sw.switch_trends[0].up_link_ports is None


@pytest.mark.asyncio
async def test_get_switches_stack_conductor_uplink_ports_parsed(tools):
    """UpLinkPorts stringified Python list is parsed into a real list."""
    ctx = make_ctx()
    with patch(
        "tools.switch_monitoring.MonitoringSwitches.get_all_switches",
        return_value=[RAW_SWITCH_STACK_CONDUCTOR],
    ):
        result = await tools["central_get_switches"](ctx)

    sw = result[0]
    assert sw.switch_role == "Conductor"
    assert sw.deployment == "Stack"
    assert sw.switch_trends[0].up_link_ports == ["1/1/27", "1/1/28"]


# ---------------------------------------------------------------------------
# central_get_switch_details
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_switch_details_base_only(tools):
    """Base snapshot (no include) returns SwitchDetail; no sub-resource methods called."""
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_details",
        return_value=dict(RAW_DETAIL_BASE),
    ) as mock_details:
        result = await tools["central_get_switch_details"](ctx, serial_number="FCW2026D0KV")

    assert isinstance(result, SwitchDetail)
    assert result.serial_number == "FCW2026D0KV"
    assert result.health == "Good"
    assert result.manufacturer == "Cisco"
    assert result.config_status == "In Sync"
    mock_details.assert_called_once()

    serialized = result.model_dump()
    # Include sub-resources absent when not requested
    assert "interfaces" not in serialized
    assert "vlans" not in serialized
    assert "poe" not in serialized
    assert "hardware" not in serialized


@pytest.mark.asyncio
async def test_get_switch_details_include_interfaces(tools):
    """include=['interfaces'] calls get_switch_interfaces and attaches result."""
    ctx = make_ctx()
    interfaces_response = {
        "count": 1,
        "total": 48,
        "offset": 0,
        "items": [
            {
                "id": "Gi1/0/1",
                "name": "Gi1/0/1",
                "alias": "GigabitEthernet1/0/1",
                "status": "Connected",
                "adminStatus": "Up",
                "operStatus": "Up",
                "speed": 1000000000,
                "uplink": False,
            }
        ],
    }
    with (
        patch(
            "utils.monitoring.MonitoringSwitches.get_switch_details",
            return_value=dict(RAW_DETAIL_BASE),
        ),
        patch(
            "utils.monitoring.MonitoringSwitches.get_switch_interfaces",
            return_value=interfaces_response,
        ) as mock_ifaces,
    ):
        result = await tools["central_get_switch_details"](
            ctx, serial_number="FCW2026D0KV", include=["interfaces"]
        )

    assert isinstance(result, SwitchDetail)
    mock_ifaces.assert_called_once()
    serialized = result.model_dump()
    assert "interfaces" in serialized
    assert serialized["interfaces"]["count"] == 1


@pytest.mark.asyncio
async def test_get_switch_details_include_poe_double_wrap_unwrapped(tools):
    """include=['poe'] unwraps the {response: {items, count}} double-wrapper."""
    ctx = make_ctx()
    poe_response = {"response": {"items": [], "count": 0}}
    with (
        patch(
            "utils.monitoring.MonitoringSwitches.get_switch_details",
            return_value=dict(RAW_DETAIL_BASE),
        ),
        patch(
            "utils.monitoring.MonitoringSwitches.get_switch_interface_poe",
            return_value=poe_response,
        ),
    ):
        result = await tools["central_get_switch_details"](
            ctx, serial_number="FCW2026D0KV", include=["poe"]
        )

    assert isinstance(result, SwitchDetail)
    serialized = result.model_dump()
    assert "poe" in serialized
    # Double-wrap should be stripped: no 'response' key inside poe
    assert "response" not in serialized["poe"]
    assert "items" in serialized["poe"]
    assert serialized["poe"]["count"] == 0


@pytest.mark.asyncio
async def test_get_switch_details_include_vsx_error_isolated(tools):
    """include=['vsx'] on a non-VSX switch stores error dict instead of raising."""
    ctx = make_ctx()
    with (
        patch(
            "utils.monitoring.MonitoringSwitches.get_switch_details",
            return_value=dict(RAW_DETAIL_BASE),
        ),
        patch(
            "utils.monitoring.MonitoringSwitches.get_switch_vsx",
            side_effect=Exception("VSX is not supported on this switch platform"),
        ),
    ):
        result = await tools["central_get_switch_details"](
            ctx, serial_number="FCW2026D0KV", include=["vsx"]
        )

    assert isinstance(result, SwitchDetail)
    serialized = result.model_dump()
    assert "vsx" in serialized
    assert "error" in serialized["vsx"]
    assert "VSX" in serialized["vsx"]["error"]


@pytest.mark.asyncio
async def test_get_switch_details_include_stack_members(tools):
    """include=['stack_members'] calls get_stack_members using conductor serial."""
    ctx = make_ctx()
    stack_response = {
        "count": 1,
        "items": [
            {
                "topology": "Ring",
                "stackType": "vsf",
                "id": "e8a387e6-2c8d-414a-93d1-2927ea07471e",
                "members": [
                    {"serialNumber": "SG34L5002Y", "switchRole": "Conductor", "health": "Good"},
                    {"serialNumber": "SG34L5006M", "switchRole": "Standby", "health": "Good"},
                ],
                "portLinks": [],
            }
        ],
    }
    base_stack = {**RAW_DETAIL_BASE, "serialNumber": "SG34L5002Y", "deployment": "Stack"}
    with (
        patch(
            "utils.monitoring.MonitoringSwitches.get_switch_details",
            return_value=base_stack,
        ),
        patch(
            "utils.monitoring.MonitoringSwitches.get_stack_members",
            return_value=stack_response,
        ) as mock_stack,
    ):
        result = await tools["central_get_switch_details"](
            ctx, serial_number="SG34L5002Y", include=["stack_members"]
        )

    assert isinstance(result, SwitchDetail)
    mock_stack.assert_called_once()
    serialized = result.model_dump()
    assert "stack_members" in serialized


@pytest.mark.asyncio
async def test_get_switch_details_not_found(tools):
    """fetch_switch_snapshot returning falsy yields a 'not found' message."""
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_details", return_value=None
    ):
        result = await tools["central_get_switch_details"](ctx, serial_number="MISSING")
    assert "No switch found for serial number 'MISSING'" in result


@pytest.mark.asyncio
async def test_get_switch_details_empty_dict_not_found(tools):
    """fetch_switch_snapshot returning empty dict also yields a 'not found' message."""
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_details", return_value={}
    ):
        result = await tools["central_get_switch_details"](ctx, serial_number="EMPTY")
    assert "No switch found for serial number 'EMPTY'" in result


@pytest.mark.asyncio
async def test_get_switch_details_fetch_error(tools):
    """Exception from get_switch_details is returned as a formatted error string."""
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_details",
        side_effect=Exception("connection refused"),
    ):
        result = await tools["central_get_switch_details"](ctx, serial_number="FCW2026D0KV")
    assert "Error fetching switch details" in result
    assert "connection refused" in result


# ---------------------------------------------------------------------------
# central_get_switch_trends — hardware scope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_switch_trends_hardware_sentinel_stripped_and_coerced(tools):
    """Sentinel sample is stripped; string metric values are coerced to int."""
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_hardware_trends",
        return_value=RAW_HARDWARE_TRENDS,
    ) as mock_trends:
        result = await tools["central_get_switch_trends"](
            ctx,
            serial_number="FCW2026D0KV",
            scope="hardware",
        )

    assert isinstance(result, list)
    # 3 raw samples → 1 sentinel stripped → 2 returned
    assert len(result) == 2
    assert isinstance(result[0], TrendSample)
    dumped = result[0].model_dump()
    assert dumped["timestamp"] == "2026-06-05T21:05:00Z"
    # Values coerced from str to int
    assert dumped["cpuUtilization"] == 2
    assert isinstance(dumped["cpuUtilization"], int)
    assert dumped["memoryUtilization"] == 35
    assert isinstance(dumped["memoryUtilization"], int)
    # No sentinel: last sample should have metrics, not be timestamp-only
    last = result[-1].model_dump()
    assert "cpuUtilization" in last

    # Verify mock called with correct API args
    call_kwargs = mock_trends.call_args.kwargs
    assert call_kwargs["serial_number"] == "FCW2026D0KV"
    assert call_kwargs["start_time"] is not None
    assert call_kwargs["end_time"] is not None
    # metric is not forwarded (multi-metric scope)
    assert "metric" not in call_kwargs


@pytest.mark.asyncio
async def test_get_switch_trends_hardware_is_default_scope(tools):
    """Default scope is 'hardware'."""
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_hardware_trends",
        return_value=RAW_HARDWARE_TRENDS,
    ) as mock_hw:
        result = await tools["central_get_switch_trends"](
            ctx,
            serial_number="FCW2026D0KV",
        )
    mock_hw.assert_called_once()
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# central_get_switch_trends — interface scope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_switch_trends_interface_scope(tools):
    """scope='interface' calls get_switch_interface_trends; metrics coerced."""
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_interface_trends",
        return_value=RAW_INTERFACE_TRENDS,
    ) as mock_iface:
        result = await tools["central_get_switch_trends"](
            ctx,
            serial_number="FCW2026D0KV",
            scope="interface",
        )

    assert isinstance(result, list)
    assert len(result) == 1  # 2 raw - 1 sentinel
    dumped = result[0].model_dump()
    assert dumped["rxBytes"] == 89027
    assert isinstance(dumped["rxBytes"], int)
    assert dumped["txBytes"] == 84434
    mock_iface.assert_called_once()


@pytest.mark.asyncio
async def test_get_switch_trends_interface_with_interface_id(tools):
    """interface_id is forwarded as an extra param to the underlying API."""
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_interface_trends",
        return_value=RAW_INTERFACE_TRENDS,
    ) as mock_iface:
        await tools["central_get_switch_trends"](
            ctx,
            serial_number="FCW2026D0KV",
            scope="interface",
            interface_id="Gi1/0/1",
        )

    call_kwargs = mock_iface.call_args.kwargs
    assert call_kwargs["interface_id"] == "Gi1/0/1"


@pytest.mark.asyncio
async def test_get_switch_trends_interface_with_uplink(tools):
    """uplink=True is forwarded as an extra param to the underlying API."""
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_interface_trends",
        return_value=RAW_INTERFACE_TRENDS,
    ) as mock_iface:
        await tools["central_get_switch_trends"](
            ctx,
            serial_number="FCW2026D0KV",
            scope="interface",
            uplink=True,
        )

    call_kwargs = mock_iface.call_args.kwargs
    assert call_kwargs["uplink"] is True


@pytest.mark.asyncio
async def test_get_switch_trends_none_interface_id_not_forwarded(tools):
    """interface_id=None is dropped from kwargs (not forwarded to API)."""
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_interface_trends",
        return_value=RAW_INTERFACE_TRENDS,
    ) as mock_iface:
        await tools["central_get_switch_trends"](
            ctx,
            serial_number="FCW2026D0KV",
            scope="interface",
            interface_id=None,
            uplink=None,
        )

    call_kwargs = mock_iface.call_args.kwargs
    assert "interface_id" not in call_kwargs
    assert "uplink" not in call_kwargs


# ---------------------------------------------------------------------------
# central_get_switch_trends — invalid scope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_switch_trends_invalid_scope_returns_error(tools):
    """An invalid scope returns a formatted validation error."""
    ctx = make_ctx()
    result = await tools["central_get_switch_trends"](
        ctx,
        serial_number="FCW2026D0KV",
        scope="ap",  # type: ignore[arg-type]  — invalid for switch
    )
    assert isinstance(result, str)
    assert "Error validating switch trend request" in result


# ---------------------------------------------------------------------------
# central_get_switch_trends — explicit start/end override
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_switch_trends_explicit_time_window(tools):
    """Explicit start_time/end_time are passed through to the underlying API call."""
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_hardware_trends",
        return_value=RAW_HARDWARE_TRENDS,
    ) as mock_trends:
        await tools["central_get_switch_trends"](
            ctx,
            serial_number="FCW2026D0KV",
            scope="hardware",
            start_time="2026-06-05T21:02:34.000Z",
            end_time="2026-06-05T22:02:34.000Z",
        )

    call_kwargs = mock_trends.call_args.kwargs
    assert call_kwargs["start_time"] == "2026-06-05T21:02:34.000Z"
    assert call_kwargs["end_time"] == "2026-06-05T22:02:34.000Z"


# ---------------------------------------------------------------------------
# central_get_switch_trends — empty result and API error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_switch_trends_empty_result(tools):
    """Empty API response returns a 'no trend data found' message."""
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_hardware_trends", return_value=[]
    ):
        result = await tools["central_get_switch_trends"](
            ctx,
            serial_number="FCW2026D0KV",
            scope="hardware",
        )
    assert "No hardware trend data found for serial number 'FCW2026D0KV'" in result


@pytest.mark.asyncio
async def test_get_switch_trends_sentinel_only_treated_as_empty(tools):
    """A list containing only the sentinel sample is reported as no trend data.

    When the API returns just the trailing sentinel (timestamp-only), normalize_switch_trends
    strips it, yielding [].  The tool then returns the 'no trend data found' message rather
    than an empty list.
    """
    ctx = make_ctx()
    # Only the sentinel
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_hardware_trends",
        return_value=[{"timestamp": "2026-06-05T22:05:00Z"}],
    ):
        result = await tools["central_get_switch_trends"](
            ctx,
            serial_number="FCW2026D0KV",
            scope="hardware",
        )
    assert isinstance(result, str)
    assert "No hardware trend data found for serial number 'FCW2026D0KV'" in result


@pytest.mark.asyncio
async def test_get_switch_trends_api_error(tools):
    """RuntimeError from the API is returned as a formatted 'fetching switch trends' error."""
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_hardware_trends",
        side_effect=RuntimeError("upstream timeout"),
    ):
        result = await tools["central_get_switch_trends"](
            ctx,
            serial_number="FCW2026D0KV",
            scope="hardware",
        )
    assert "Error fetching switch trends" in result
    assert "upstream timeout" in result


# ---------------------------------------------------------------------------
# Model behaviour — Switch sparse serialization
# ---------------------------------------------------------------------------


def test_switch_model_dump_nulls_dropped():
    """Switch.model_dump() excludes None fields."""
    sw = Switch.from_api(
        {
            "serialNumber": "FCW2026D0KV",
            "status": "Online",
            "model": "WS-C3850-12X48U-E",
        }
    )
    dumped = sw.model_dump()
    assert dumped["serial_number"] == "FCW2026D0KV"
    assert dumped["status"] == "Online"
    assert dumped["model"] == "WS-C3850-12X48U-E"
    assert "site_id" not in dumped
    assert "ipv4" not in dumped
    assert "switch_trends" not in dumped


def test_switch_detail_health_reasons_preserved():
    """SwitchDetail.from_api preserves health and healthReasons dicts."""
    detail = SwitchDetail.from_api(
        {
            "serialNumber": "FCW2026D0KV",
            "status": "Online",
            "health": "Fair",
            "healthReasons": {"poorReasons": [], "fairReasons": ["High CPU"]},
        }
    )
    dumped = detail.model_dump()
    assert dumped["health"] == "Fair"
    assert dumped["health_reasons"]["fairReasons"] == ["High CPU"]
