import inspect
import json
from typing import get_type_hints
from unittest.mock import patch

import pytest
from fastmcp.exceptions import ToolError

import tools.devices as mod
from constants import MAX_PAGE_SIZE
from models import Device, DeviceEnvelope
from tests.conftest import FakeMCP, annotated_field, make_ctx
from utils.cursor import decode_cursor, hash_query
from utils.devices import clean_device_data

RAW_DEVICE = {
    "serialNumber": "SN123",
    "macAddress": "aa:bb:cc:dd:ee:ff",
    "deviceType": "SWITCH",
    "model": "CX-6300",
    "partNumber": "PN1",
    "deviceName": "switch-01",
    "deviceFunction": "SWITCH",
    "status": "ONLINE",
    "isProvisioned": "Yes",
    "role": None,
    "deployment": None,
    "tier": None,
    "firmwareVersion": "10.12",
    "siteId": "site-1",
    "siteName": "HQ",
    "deviceGroupName": "Switches",
    "scopeId": None,
    "ipv4": "10.0.0.1",
    "stackId": None,
}
RAW_DEVICE_2 = {**RAW_DEVICE, "serialNumber": "SN456", "deviceName": "switch-02"}
RAW_AP_DEVICE = {
    **RAW_DEVICE,
    "serialNumber": "AP123",
    "deviceType": "ACCESS_POINT",
    "model": "AP-635",
    "deviceName": "ap-01",
}
RAW_GATEWAY_DEVICE = {
    **RAW_DEVICE,
    "serialNumber": "GW123",
    "deviceType": "GATEWAY",
    "model": "A7240XM",
    "deviceName": "gateway-01",
}


def device_page(
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


@pytest.fixture
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


def test_registers_only_device_survivors(tools):
    assert list(tools) == [
        "central_get_devices",
        "central_get_device_details",
        "central_get_device_trends",
    ]


def test_device_type_filter_mapping_matches_family_capabilities():
    assert mod.DEVICE_TYPE_FILTER_PARAMS == {
        "ap": frozenset(
            {
                "site_id",
                "site_name",
                "serial_number",
                "device_name",
                "device_status",
                "model",
                "firmware_version",
                "deployment",
                "cluster_id",
                "cluster_name",
            }
        ),
        "switch": frozenset(
            {"site_id", "site_name", "model", "device_status", "deployment"}
        ),
        "gateway": frozenset(
            {
                "site_id",
                "site_name",
                "serial_number",
                "device_name",
                "model",
                "device_status",
                "cluster_name",
            }
        ),
    }


def test_device_type_include_mapping_matches_family_capabilities():
    assert mod.DEVICE_TYPE_INCLUDES == {
        "ap": frozenset({"radios", "ports"}),
        "switch": frozenset(
            {
                "interfaces",
                "vlans",
                "poe",
                "lag",
                "vsx",
                "stack_members",
                "hardware",
            }
        ),
        "gateway": frozenset({"ports", "tunnels", "uplinks", "vlans", "dhcp"}),
    }


def test_get_devices_limit_has_schema_bounds(tools):
    parameter = inspect.signature(tools["central_get_devices"]).parameters["limit"]
    assert parameter.default is None
    annotation = get_type_hints(tools["central_get_devices"], include_extras=True)[
        "limit"
    ]
    field = annotated_field(annotation)
    assert field.metadata[0].ge == 1
    assert field.metadata[1].le == MAX_PAGE_SIZE


@pytest.mark.asyncio
async def test_get_devices_inventory_page_one_emits_resumable_cursor(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.devices.MonitoringDevices.get_device_inventory",
            return_value=device_page(
                [RAW_DEVICE, RAW_DEVICE_2],
                total=250,
                next_cursor="2",
            ),
        ) as mock_api,
        patch(
            "tools.devices.MonitoringDevices.get_all_device_inventory",
            side_effect=AssertionError("aggregation API called"),
        ) as mock_all,
    ):
        result = await tools["central_get_devices"](ctx)

    decoded = decode_cursor(
        result.next_cursor,
        expected_tool="central_get_devices:inventory",
        expected_query_hash=hash_query(
            {
                "device_type": None,
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
        ),
    )

    assert isinstance(result, DeviceEnvelope)
    assert result.total == 250
    assert result.meta.total_available == 250
    assert result.meta.returned == 2
    assert [item.serial_number for item in result.items] == ["SN123", "SN456"]
    assert decoded.page_size == mod.DEFAULT_DEVICE_LIMIT
    assert decoded.position == {"upstream_next": "2"}
    assert mock_api.call_args.kwargs["filter_str"] is None
    assert mock_api.call_args.kwargs["limit"] == mod.DEFAULT_DEVICE_LIMIT
    assert mock_api.call_args.kwargs["next"] == 1
    mock_api.assert_called_once()
    mock_all.assert_not_called()


@pytest.mark.asyncio
async def test_get_devices_empty_is_empty_envelope(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_device_inventory",
        return_value=device_page(),
    ):
        result = await tools["central_get_devices"](ctx)
    assert isinstance(result, DeviceEnvelope)
    assert result.items == []
    assert result.meta.returned == 0


@pytest.mark.asyncio
async def test_get_devices_inventory_last_page_is_terminal(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_device_inventory",
        return_value=device_page([RAW_DEVICE], total=2, next_cursor=None),
    ):
        result = await tools["central_get_devices"](ctx, limit=1)
    assert len(result.items) == 1
    assert result.next_cursor is None
    assert result.truncated is False
    assert result.total == 2
    assert result.meta.total_available == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provisioned,expected",
    [(True, "isProvisioned eq 'Yes'"), (False, "isProvisioned eq 'No'")],
)
async def test_get_devices_inventory_filter_mapping(tools, provisioned, expected):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_device_inventory",
        return_value=device_page(),
    ) as mock_api:
        await tools["central_get_devices"](ctx, is_provisioned=provisioned)
    assert mock_api.call_args.kwargs["filter_str"] == expected


@pytest.mark.asyncio
async def test_get_devices_inventory_status_filter_is_local(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_device_inventory",
        return_value=device_page(
            [RAW_DEVICE, {**RAW_DEVICE_2, "status": "OFFLINE"}],
            total=2,
        ),
    ):
        result = await tools["central_get_devices"](ctx, device_status="ONLINE")
    assert [item.serial_number for item in result.items] == ["SN123"]


@pytest.mark.asyncio
async def test_get_devices_inventory_cursor_replay_fetches_next_upstream_page(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_device_inventory",
        side_effect=[
            device_page([RAW_DEVICE], total=2, next_cursor="2"),
            device_page([RAW_DEVICE_2], total=2, next_cursor=None),
        ],
    ) as mock_api:
        first_page = await tools["central_get_devices"](ctx, limit=50)
        second_page = await tools["central_get_devices"](
            ctx,
            cursor=first_page.next_cursor,
        )

    second_call = mock_api.call_args_list[1].kwargs
    assert second_call["next"] == 2
    assert second_call["limit"] == 50
    assert [item.serial_number for item in second_page.items] == ["SN456"]
    assert second_page.next_cursor is None


@pytest.mark.asyncio
async def test_get_devices_rejects_cross_family_cursor_replay(tools):
    # A device cursor is bound to its family tool (central_get_devices:ap);
    # replaying an AP cursor against the switch family must be rejected before
    # the switch API is ever called.
    source_device_type = "ap"
    target_device_type = "switch"
    ctx = make_ctx()
    with (
        patch(
            "tools.devices.MonitoringAPs.get_aps",
            return_value=device_page(
                [RAW_AP_DEVICE],
                total=2,
                next_cursor="2",
            ),
        ),
        patch("tools.devices.MonitoringSwitches.get_switches") as mock_switch_api,
    ):
        first_page = await tools["central_get_devices"](
            ctx,
            device_type=source_device_type,
        )
        with pytest.raises(ToolError) as exc_info:
            await tools["central_get_devices"](
                ctx,
                device_type=target_device_type,
                cursor=first_page.next_cursor,
            )

    error = json.loads(str(exc_info.value))
    assert error["code"] == "validation_error"
    assert error["retryable"] is False
    assert "invalid or stale cursor" in error["message"]
    mock_switch_api.assert_not_called()


@pytest.mark.asyncio
async def test_get_devices_rejects_limit_conflicting_with_cursor_page_size(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_device_inventory",
        return_value=device_page([RAW_DEVICE], total=2, next_cursor="2"),
    ) as mock_api:
        first_page = await tools["central_get_devices"](ctx, limit=50)
        with pytest.raises(ToolError) as exc_info:
            await tools["central_get_devices"](
                ctx,
                limit=25,
                cursor=first_page.next_cursor,
            )

    error = json.loads(str(exc_info.value))
    assert error["code"] == "validation_error"
    assert error["retryable"] is False
    assert "limit conflicts with the cursor page_size" in error["message"]
    assert mock_api.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "identifier,expected_filter",
    [
        ({"serial_number": "SN123"}, "serialNumber eq 'SN123'"),
        ({"device_name": "switch-01"}, "deviceName eq 'switch-01'"),
    ],
)
async def test_get_devices_exact_lookup(tools, identifier, expected_filter):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_device_inventory",
        return_value={"items": [RAW_DEVICE]},
    ) as mock_api:
        result = await tools["central_get_devices"](ctx, **identifier)
    assert mock_api.call_args.kwargs["filter_str"] == expected_filter
    assert isinstance(result, DeviceEnvelope)
    assert [item.serial_number for item in result.items] == ["SN123"]


@pytest.mark.asyncio
async def test_get_devices_switch_exact_serial_uses_inventory(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_device_inventory",
        return_value={"items": [RAW_DEVICE]},
    ) as mock_api:
        result = await tools["central_get_devices"](
            ctx,
            device_type="switch",
            serial_number="SN123",
        )

    assert mock_api.call_args.kwargs["filter_str"] == "serialNumber eq 'SN123'"
    assert [item.serial_number for item in result.items] == ["SN123"]
    assert result.items[0].device_type == "SWITCH"


@pytest.mark.asyncio
async def test_get_devices_exact_lookup_rejects_device_type_mismatch(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.devices.MonitoringDevices.get_device_inventory",
            return_value={"items": [RAW_GATEWAY_DEVICE]},
        ),
        pytest.raises(ToolError) as exc_info,
    ):
        await tools["central_get_devices"](
            ctx,
            device_type="ap",
            serial_number="GW123",
        )

    error = json.loads(str(exc_info.value))
    assert error["code"] == "validation_error"
    assert "actual device_type='gateway'" in error["message"]
    assert "requested device_type='ap'" in error["message"]


@pytest.mark.asyncio
async def test_get_devices_exact_lookup_accepts_matching_gateway_family(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_device_inventory",
        return_value={"items": [RAW_GATEWAY_DEVICE]},
    ):
        result = await tools["central_get_devices"](
            ctx,
            device_type="gateway",
            serial_number="GW123",
        )

    assert [item.serial_number for item in result.items] == ["GW123"]
    assert result.items[0].device_type == "GATEWAY"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw_device",
    [RAW_AP_DEVICE, RAW_DEVICE, RAW_GATEWAY_DEVICE],
    ids=["ap", "switch", "gateway"],
)
async def test_get_devices_exact_lookup_without_device_type_accepts_all_families(
    tools,
    raw_device,
):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_device_inventory",
        return_value={"items": [raw_device]},
    ):
        result = await tools["central_get_devices"](
            ctx,
            serial_number=raw_device["serialNumber"],
        )

    assert [item.serial_number for item in result.items] == [
        raw_device["serialNumber"]
    ]
    assert result.items[0].device_type == raw_device["deviceType"]


@pytest.mark.asyncio
async def test_get_devices_exact_lookup_empty_is_empty_envelope(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_device_inventory",
        return_value={"items": []},
    ):
        result = await tools["central_get_devices"](ctx, serial_number="MISSING")
    assert result.items == []


@pytest.mark.asyncio
async def test_get_devices_exact_lookup_ignores_cursor_and_is_terminal(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_device_inventory",
        return_value={"items": [RAW_DEVICE]},
    ):
        result = await tools["central_get_devices"](
            ctx,
            serial_number="SN123",
            cursor="not-valid-base64!",
        )

    assert [item.serial_number for item in result.items] == ["SN123"]
    assert result.next_cursor is None
    assert result.truncated is False
    assert result.total == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs,response,message",
    [
        (
            {"serial_number": "SN123", "device_name": "switch-01"},
            None,
            "Provide only one exact identifier",
        ),
        (
            {"device_name": "switch-01"},
            {"items": [RAW_DEVICE, RAW_DEVICE_2]},
            "Multiple devices found",
        ),
        (
            {"serial_number": "SN123"},
            {"unexpected": []},
            "missing 'items'",
        ),
    ],
)
async def test_get_devices_lookup_errors_raise_tool_error(
    tools, kwargs, response, message
):
    ctx = make_ctx()
    patcher = patch(
        "tools.devices.MonitoringDevices.get_device_inventory",
        return_value=response,
    )
    with patcher, pytest.raises(ToolError, match=message):
        await tools["central_get_devices"](ctx, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "device_type,param,value",
    [
        ("ap", "site_assigned", True),
        ("switch", "firmware_version", "10.12"),
        ("gateway", "deployment", "Standalone"),
    ],
)
async def test_get_devices_rejects_unsupported_family_filters_before_connection(
    tools, device_type, param, value
):
    ctx = make_ctx()
    with (
        patch(
            "tools.devices.api_context", side_effect=AssertionError("connection opened")
        ) as mock_context,
        pytest.raises(ToolError, match=rf"{param}.*device_type='{device_type}'"),
    ):
        await tools["central_get_devices"](
            ctx, device_type=device_type, **{param: value}
        )
    mock_context.assert_not_called()


@pytest.mark.asyncio
async def test_get_devices_rejects_filters_ignored_by_exact_lookup_before_connection(
    tools,
):
    ctx = make_ctx()
    with (
        patch(
            "tools.devices.api_context", side_effect=AssertionError("connection opened")
        ) as mock_context,
        pytest.raises(ToolError, match=r"site_id.*exact.*device_type='ap'"),
    ):
        await tools["central_get_devices"](
            ctx,
            device_type="ap",
            serial_number="SN123",
            site_id="site-1",
        )
    mock_context.assert_not_called()


@pytest.mark.asyncio
async def test_get_devices_rejects_unsupported_inventory_filter_before_connection(
    tools,
):
    ctx = make_ctx()
    with (
        patch(
            "tools.devices.api_context", side_effect=AssertionError("connection opened")
        ) as mock_context,
        pytest.raises(ToolError, match=r"cluster_name.*device_type is omitted"),
    ):
        await tools["central_get_devices"](ctx, cluster_name="cluster-1")
    mock_context.assert_not_called()


@pytest.mark.asyncio
async def test_get_devices_upstream_error_raises_tool_error(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.devices.MonitoringDevices.get_device_inventory",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(ToolError, match="boom"),
    ):
        await tools["central_get_devices"](ctx)


@pytest.mark.asyncio
async def test_get_device_details_auto_resolution_failure_recommends_device_type(
    tools,
):
    ctx = make_ctx()
    stack_filter_error = RuntimeError(
        'HTTP 400: Filtering on field "stackId" is not supported'
    )
    with (
        patch(
            "utils.common.MonitoringDevices.get_all_device_inventory",
            # serialNumber miss, stackId filter rejected, unfiltered rescan miss.
            side_effect=[[], stack_filter_error, []],
        ),
        pytest.raises(ToolError) as exc_info,
    ):
        await tools["central_get_device_details"](ctx, serial_number="FCW2026D0KV")

    error = json.loads(str(exc_info.value))
    assert error["code"] == "validation_error"
    assert "pass device_type explicitly" in error["message"]
    assert "stackId" not in error["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs,error_fragment",
    [
        (
            {
                "device_type": "ap",
                "scope": "ap",
                "metric": "cpu-utilization",
                "interface_id": "1/1/1",
            },
            "interface_id",
        ),
        (
            {"device_type": "switch", "scope": "hardware", "metric": "throughput"},
            "metric",
        ),
        (
            {"device_type": "ap", "scope": "radio", "metric": "throughput"},
            "radio_number",
        ),
    ],
)
async def test_get_device_trends_rejects_inapplicable_params_before_api_access(
    tools, kwargs, error_fragment
):
    ctx = make_ctx()
    with (
        patch(
            "tools.devices.api_context", side_effect=AssertionError("connection opened")
        ) as mock_api_context,
        pytest.raises(ToolError, match=error_fragment),
    ):
        await tools["central_get_device_trends"](
            ctx,
            serial_number="SN123",
            **kwargs,
        )

    mock_api_context.assert_not_called()

def test_clean_device_data_returns_device_models():
    result = clean_device_data([RAW_DEVICE])
    assert len(result) == 1
    assert isinstance(result[0], Device)


def test_clean_device_data_field_mapping():
    device = clean_device_data([RAW_DEVICE])[0]
    assert device.serial_number == "SN123"
    assert device.mac_address == "aa:bb:cc:dd:ee:ff"
    assert device.device_type == "SWITCH"
    assert device.name == "switch-01"
    assert device.firmware_version == "10.12"


def test_clean_device_data_is_provisioned_no():
    device = clean_device_data([{**RAW_DEVICE, "isProvisioned": "No"}])[0]
    assert device.is_provisioned is False
