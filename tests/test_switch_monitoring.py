from unittest.mock import patch

import pytest
from fastmcp.exceptions import ToolError

import tools.devices as mod
from models import DeviceEnvelope, DeviceTrendsEnvelope, Switch, SwitchDetail
from tests.conftest import FakeMCP, make_ctx
from utils.cursor import decode_cursor, hash_query

RAW_SWITCH = {
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
    "deployment": "Standalone",
    "status": "Online",
    "publicIp": "10.128.235.11",
    "macAddress": "94:d4:69:46:74:72",
    "ipv4": "10.128.235.11",
    "stackMemberId": 0,
    "switchType": "tpd",
}
RAW_DETAIL = {
    **RAW_SWITCH,
    "health": "Good",
    "healthReasons": {"poorReasons": [], "fairReasons": []},
    "manufacturer": "Cisco",
    "lastRestartReason": "PowerUp",
    "configStatus": "In Sync",
    "lastConfigChange": "2026-06-01T00:00:00Z",
}
RAW_HARDWARE_TRENDS = [
    {
        "timestamp": "2026-06-05T21:05:00Z",
        "serialNumber": "FCW2026D0KV",
        "cpuUtilization": "2",
        "memoryUtilization": "35",
    },
    {
        "timestamp": "2026-06-05T21:10:00Z",
        "serialNumber": "FCW2026D0KV",
        "cpuUtilization": "3",
        "memoryUtilization": "36",
    },
    {"timestamp": "2026-06-05T22:05:00Z"},
]
RAW_INTERFACE_TRENDS = [
    {"timestamp": "2026-06-05T21:05:00Z", "rxBytes": "89027", "txBytes": "84434"},
    {"timestamp": "2026-06-05T22:05:00Z"},
]
STACK_ID = "e8a387e6-2c8d-414a-93d1-2927ea07471e"
REAL_RESOLVER = mod._resolve_monitoring_family


def switch_page(
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


def switch_query_hash() -> str:
    return hash_query(
        {
            "device_type": "switch",
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
def resolve_as_switch():
    def resolve(_conn, serial):
        return "switch", STACK_ID if serial == "MEMBER" else serial

    with patch("tools.devices._resolve_monitoring_family", side_effect=resolve):
        yield


@pytest.mark.asyncio
async def test_get_devices_switch_page_one_uses_single_page_api_and_emits_cursor(
    tools,
):
    ctx = make_ctx()
    with (
        patch(
            "tools.devices.MonitoringSwitches.get_switches",
            return_value=switch_page([RAW_SWITCH], total=150, next_cursor="2"),
        ) as mock_api,
        patch(
            "tools.devices.MonitoringSwitches.get_all_switches",
            side_effect=AssertionError("aggregation API called"),
        ) as mock_all,
    ):
        result = await tools["central_get_devices"](ctx, device_type="switch")

    decoded = decode_cursor(
        result.next_cursor,
        expected_tool="central_get_devices:switch",
        expected_query_hash=switch_query_hash(),
    )

    assert isinstance(result, DeviceEnvelope)
    assert result.total == 150
    assert result.meta.total_available == 150
    assert result.items[0].device_type == "SWITCH"
    assert result.items[0].serial_number == "FCW2026D0KV"
    assert result.items[0].status == "ONLINE"
    assert result.items[0].name == "BO-MEX-EGSW02.owl.direct"
    assert result.items[0].model == "WS-C3850-12X48U-E"
    assert result.items[0].firmware_version == "Everest 16.6.2"
    assert result.items[0].deployment == "Standalone"
    assert result.items[0].role == "Standalone"
    assert result.items[0].site_id == "34011151398"
    assert result.items[0].site_name == "Mexico City (MEX) - Branch"
    assert result.items[0].ipv4 == "10.128.235.11"
    assert mock_api.call_args.kwargs["filter_str"] is None
    assert mock_api.call_args.kwargs["limit"] == mod.DEFAULT_DEVICE_LIMIT
    assert mock_api.call_args.kwargs["next_page"] == 1
    assert decoded.page_size == mod.DEFAULT_DEVICE_LIMIT
    assert decoded.position == {"upstream_next": "2"}
    mock_api.assert_called_once()
    mock_all.assert_not_called()


@pytest.mark.asyncio
async def test_get_devices_switch_last_page_is_terminal(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringSwitches.get_switches",
        return_value=switch_page([RAW_SWITCH], total=101, next_cursor=None),
    ):
        result = await tools["central_get_devices"](
            ctx,
            device_type="switch",
            limit=50,
        )

    assert result.next_cursor is None
    assert result.total == 101
    assert result.meta.total_available == 101
    assert result.truncated is False


@pytest.mark.asyncio
async def test_get_devices_switch_cursor_replay_fetches_next_upstream_page(tools):
    ctx = make_ctx()
    second_switch = {
        **RAW_SWITCH,
        "serialNumber": "FCW2026D0KX",
        "deviceName": "BO-MEX-EGSW03.owl.direct",
    }
    with patch(
        "tools.devices.MonitoringSwitches.get_switches",
        side_effect=[
            switch_page([RAW_SWITCH], total=2, next_cursor="2"),
            switch_page([second_switch], total=2, next_cursor=None),
        ],
    ) as mock_api:
        first_page = await tools["central_get_devices"](
            ctx,
            device_type="switch",
            limit=50,
        )
        second_page = await tools["central_get_devices"](
            ctx,
            device_type="switch",
            cursor=first_page.next_cursor,
        )

    second_call = mock_api.call_args_list[1].kwargs
    assert second_call["next_page"] == 2
    assert second_call["limit"] == 50
    assert [item.serial_number for item in second_page.items] == ["FCW2026D0KX"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_arg,tool_value,expected_filter",
    [
        ("site_id", "34011151398", "siteId eq '34011151398'"),
        (
            "site_name",
            "Mexico City (MEX) - Branch",
            "siteName eq 'Mexico City (MEX) - Branch'",
        ),
        ("model", "WS-C3850-12X48U-E", "model eq 'WS-C3850-12X48U-E'"),
        ("device_status", "ONLINE", "status eq 'Online'"),
        ("deployment", "Standalone", "deployment eq 'Standalone'"),
    ],
)
async def test_get_devices_switch_filter_mappings(
    tools, tool_arg, tool_value, expected_filter
):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringSwitches.get_switches",
        return_value=switch_page(),
    ) as mock_api:
        result = await tools["central_get_devices"](
            ctx, device_type="switch", **{tool_arg: tool_value}
        )
    assert result.items == []
    assert mock_api.call_args.kwargs["filter_str"] == expected_filter


@pytest.mark.asyncio
async def test_get_devices_switch_combined_filters_and_sort(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringSwitches.get_switches",
        return_value=switch_page(),
    ) as mock_api:
        await tools["central_get_devices"](
            ctx,
            device_type="switch",
            site_id="34011151398",
            device_status="OFFLINE",
            deployment="Stack",
            sort="deviceName desc",
        )
    assert mock_api.call_args.kwargs["filter_str"] == (
        "siteId eq '34011151398' and status eq 'Offline' and deployment eq 'Stack'"
    )
    assert mock_api.call_args.kwargs["sort"] == "deviceName DESC"


@pytest.mark.asyncio
async def test_get_devices_switch_error_raises_tool_error(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.devices.MonitoringSwitches.get_switches",
            side_effect=RuntimeError("network timeout"),
        ),
        pytest.raises(ToolError, match="network timeout"),
    ):
        await tools["central_get_devices"](ctx, device_type="switch")


@pytest.mark.asyncio
async def test_get_device_details_switch_base_uses_original_fetch(tools):
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_details",
        return_value=dict(RAW_DETAIL),
    ) as mock_details:
        result = await tools["central_get_device_details"](
            ctx, serial_number="FCW2026D0KV"
        )
    assert isinstance(result, SwitchDetail)
    assert result.health == "Good"
    assert result.manufacturer == "Cisco"
    assert result.interfaces is None
    mock_details.assert_called_once()


@pytest.mark.asyncio
async def test_get_device_details_explicit_switch_skips_family_resolution(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.devices._resolve_monitoring_family",
            side_effect=AssertionError("generic family resolver called"),
        ) as mock_family_resolver,
        patch(
            "tools.devices.resolve_switch_serial", return_value=STACK_ID
        ) as mock_switch_resolver,
        patch(
            "tools.devices.fetch_switch_snapshot", return_value=dict(RAW_DETAIL)
        ) as mock_snapshot,
    ):
        result = await tools["central_get_device_details"](
            ctx,
            serial_number="FCW2026D0KV",
            device_type="switch",
            include=["interfaces"],
        )

    assert isinstance(result, SwitchDetail)
    mock_family_resolver.assert_not_called()
    mock_switch_resolver.assert_called_once_with(
        ctx.lifespan_context["conn"], "FCW2026D0KV"
    )
    mock_snapshot.assert_called_once_with(
        ctx.lifespan_context["conn"], STACK_ID, ["interfaces"]
    )


@pytest.mark.asyncio
async def test_get_device_details_switch_preserves_stack_identifier(tools):
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_details",
        return_value={**RAW_DETAIL, "serialNumber": "MEMBER", "deployment": "Stack"},
    ) as mock_details:
        await tools["central_get_device_details"](ctx, serial_number="MEMBER")
    assert mock_details.call_args.kwargs["serial_number"] == STACK_ID


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "include,method_name,response,expected",
    [
        (
            "interfaces",
            "get_switch_interfaces",
            {"items": [{"id": "Gi1/0/1"}], "count": 1},
            {"items": [{"id": "Gi1/0/1"}], "count": 1},
        ),
        (
            "vlans",
            "get_switch_vlans",
            {"items": [{"id": "10"}]},
            {"items": [{"id": "10"}]},
        ),
        (
            "poe",
            "get_switch_interface_poe",
            {"response": {"items": [{"id": "Gi1/0/1"}], "count": 1}},
            {"items": [{"id": "Gi1/0/1"}], "count": 1},
        ),
        ("lag", "get_switch_lag", [{"id": "lag1"}], {"items": [{"id": "lag1"}]}),
        (
            "vsx",
            "get_switch_vsx",
            {"items": [{"role": "primary"}]},
            {"items": [{"role": "primary"}]},
        ),
        (
            "stack_members",
            "get_stack_members",
            {"items": [{"topology": "Ring"}]},
            {"items": [{"topology": "Ring"}]},
        ),
        (
            "hardware",
            "get_switch_hardware_categories",
            [{"category": "CPU"}],
            {"items": [{"category": "CPU"}]},
        ),
    ],
)
async def test_get_device_details_switch_routes_all_includes(
    tools, include, method_name, response, expected
):
    ctx = make_ctx()
    with (
        patch(
            "utils.monitoring.MonitoringSwitches.get_switch_details",
            return_value=dict(RAW_DETAIL),
        ),
        patch(
            f"utils.monitoring.MonitoringSwitches.{method_name}",
            return_value=response,
        ) as mock_include,
    ):
        result = await tools["central_get_device_details"](
            ctx, serial_number="FCW2026D0KV", include=[include]
        )
    mock_include.assert_called_once()
    assert getattr(result, include) == expected


@pytest.mark.asyncio
async def test_get_device_details_switch_isolates_vsx_include_failure(tools):
    ctx = make_ctx()
    with (
        patch(
            "utils.monitoring.MonitoringSwitches.get_switch_details",
            return_value=dict(RAW_DETAIL),
        ),
        patch(
            "utils.monitoring.MonitoringSwitches.get_switch_vsx",
            side_effect=Exception("VSX is not supported on this switch platform"),
        ),
    ):
        result = await tools["central_get_device_details"](
            ctx,
            serial_number="FCW2026D0KV",
            device_type="switch",
            include=["vsx"],
        )

    assert isinstance(result, SwitchDetail)
    assert result.vsx is not None
    assert "VSX is not supported" in result.vsx["error"]


@pytest.mark.asyncio
async def test_get_device_details_switch_rejects_gateway_include(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.devices._resolve_monitoring_family",
            side_effect=AssertionError("generic family resolver called"),
        ) as mock_family_resolver,
        pytest.raises(ToolError, match=r"dhcp.*device_type='switch'"),
    ):
        await tools["central_get_device_details"](
            ctx,
            serial_number="FCW2026D0KV",
            device_type="switch",
            include=["dhcp"],
        )
    mock_family_resolver.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [None, {}])
async def test_get_device_details_switch_not_found_raises_tool_error(tools, raw):
    ctx = make_ctx()
    with (
        patch(
            "utils.monitoring.MonitoringSwitches.get_switch_details", return_value=raw
        ),
        pytest.raises(ToolError, match="No switch found"),
    ):
        await tools["central_get_device_details"](ctx, serial_number="MISSING")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,extra,method_name,raw",
    [
        ("hardware", {}, "get_switch_hardware_trends", RAW_HARDWARE_TRENDS),
        (
            "interface",
            {"interface_id": "Gi1/0/1"},
            "get_switch_interface_trends",
            RAW_INTERFACE_TRENDS,
        ),
        (
            "interface",
            {"uplink": True},
            "get_switch_interface_trends",
            RAW_INTERFACE_TRENDS,
        ),
    ],
)
async def test_get_device_trends_switch_routes_and_normalizes(
    tools, scope, extra, method_name, raw
):
    ctx = make_ctx()
    with patch(
        f"utils.monitoring.MonitoringSwitches.{method_name}", return_value=raw
    ) as mock_trends:
        result = await tools["central_get_device_trends"](
            ctx, serial_number="FCW2026D0KV", scope=scope, **extra
        )
    assert isinstance(result, DeviceTrendsEnvelope)
    assert result.meta.total_available == len(raw) - 1
    assert result.items[0].model_dump()["timestamp"] == raw[0]["timestamp"]
    if scope == "hardware":
        assert result.items[0].model_dump()["cpuUtilization"] == 2
    for key, value in extra.items():
        assert mock_trends.call_args.kwargs[key] == value


@pytest.mark.asyncio
async def test_get_device_trends_switch_defaults_hardware_and_uses_stack_id(tools):
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_hardware_trends",
        return_value=RAW_HARDWARE_TRENDS,
    ) as mock_trends:
        result = await tools["central_get_device_trends"](
            ctx, serial_number="MEMBER", max_points=1
        )
    assert mock_trends.call_args.kwargs["serial_number"] == STACK_ID
    assert result.meta.total_available == 2
    assert result.meta.returned == 1
    assert result.meta.sampled is True


@pytest.mark.asyncio
async def test_get_device_trends_explicit_switch_skips_family_resolution(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.devices._resolve_monitoring_family",
            side_effect=AssertionError("generic family resolver called"),
        ) as mock_family_resolver,
        patch(
            "tools.devices.resolve_switch_serial", return_value=STACK_ID
        ) as mock_switch_resolver,
        patch(
            "tools.devices.fetch_trends", return_value=RAW_HARDWARE_TRENDS
        ) as mock_trends,
    ):
        result = await tools["central_get_device_trends"](
            ctx,
            serial_number="FCW2026D0KV",
            device_type="switch",
            scope="hardware",
        )

    assert isinstance(result, DeviceTrendsEnvelope)
    mock_family_resolver.assert_not_called()
    mock_switch_resolver.assert_called_once_with(
        ctx.lifespan_context["conn"], "FCW2026D0KV"
    )
    assert mock_trends.call_args.args[1:4] == (STACK_ID, "hardware", None)


@pytest.mark.asyncio
async def test_get_device_trends_switch_empty_is_empty_envelope(tools):
    ctx = make_ctx()
    with patch(
        "utils.monitoring.MonitoringSwitches.get_switch_hardware_trends",
        return_value=[],
    ):
        result = await tools["central_get_device_trends"](
            ctx, serial_number="FCW2026D0KV"
        )
    assert result.items == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"scope": "blade"}, "Invalid scope"),
        ({"scope": "hardware", "metric": "cpu-utilization"}, "does not take a metric"),
    ],
)
async def test_get_device_trends_switch_validation_raises_tool_error(
    tools, kwargs, message
):
    ctx = make_ctx()
    with pytest.raises(ToolError, match=message):
        await tools["central_get_device_trends"](
            ctx, serial_number="FCW2026D0KV", **kwargs
        )


def test_resolver_maps_switch_member_to_stack_id():
    inventory = {
        "serialNumber": "MEMBER",
        "deviceType": "SWITCH",
        "deployment": "Stack",
        "stackId": STACK_ID,
    }
    with patch("tools.devices.lookup_inventory_device", return_value=inventory):
        assert REAL_RESOLVER("conn", "MEMBER") == ("switch", STACK_ID)


def test_resolver_maps_each_inventory_family_without_online_requirement():
    for device_type, expected in [
        ("ACCESS_POINT", "ap"),
        ("SWITCH", "switch"),
        ("GATEWAY", "gateway"),
    ]:
        inventory = {
            "serialNumber": "SERIAL",
            "deviceType": device_type,
            "status": "OFFLINE",
        }
        with patch("tools.devices.lookup_inventory_device", return_value=inventory):
            assert REAL_RESOLVER("conn", "SERIAL") == (expected, "SERIAL")


def test_switch_model_keeps_list_specific_fields():
    switch = Switch.from_api(RAW_SWITCH)
    assert switch.switch_type == "tpd"
    assert switch.switch_trends[0].cpu_utilization == 2


def test_switch_detail_preserves_health_fields():
    detail = SwitchDetail.from_api(RAW_DETAIL)
    assert detail.health_reasons == {"poorReasons": [], "fairReasons": []}
    assert detail.last_config_change == "2026-06-01T00:00:00Z"
