import inspect
import json
from typing import get_type_hints
from unittest.mock import patch

import pytest
from fastmcp.exceptions import ToolError

import tools.wlans as mod
from constants import MAX_PAGE_SIZE
from models import WLAN, WlanEnvelope, WLANThroughputSample
from tests.conftest import FakeMCP, annotated_field, make_ctx
from utils.cursor import decode_cursor, hash_query

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

RAW_STATS = {
    "graph": {
        "keys": ["tx", "rx"],
        "samples": [
            {"data": [100, 200], "timestamp": "2026-04-07T10:00:00Z"},
            {"data": [150, 250], "timestamp": "2026-04-07T10:05:00Z"},
        ],
    },
    "id": "wlans/Corp-WiFi",
    "metric": "wlan_throughput",
    "type": "network-monitoring/access-point-monitoring",
}

CLEANED_STATS = [
    {"timestamp": "2026-04-07T10:00:00Z", "tx": 100, "rx": 200},
    {"timestamp": "2026-04-07T10:05:00Z", "tx": 150, "rx": 250},
]


@pytest.fixture
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


def wlan_page(
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


def test_registers_wlan_tools(tools):
    assert list(tools) == ["central_get_wlans"]


def test_get_wlans_limit_has_schema_bounds(tools):
    parameter = inspect.signature(tools["central_get_wlans"]).parameters["limit"]
    assert parameter.default is None
    annotation = get_type_hints(tools["central_get_wlans"], include_extras=True)[
        "limit"
    ]
    field = annotated_field(annotation)
    assert field.metadata[0].ge == 1
    assert field.metadata[1].le == MAX_PAGE_SIZE


def test_wlan_model_accepts_api_camelcase_and_serializes_snake_case():
    wlan = WLAN(**RAW_WLAN)
    assert wlan.wlan_name == "Corp-WiFi"
    assert wlan.security_level == "Enterprise"
    assert wlan.model_dump() == {
        "wlan_name": "Corp-WiFi",
        "security_level": "Enterprise",
        "security": "WPA3",
        "band": "5GHz",
        "status": "enabled",
        "vlan": "10",
    }


def test_wlan_throughput_sample_model_serializes_expected_shape():
    sample = WLANThroughputSample(
        timestamp="2026-04-07T10:00:00Z",
        tx=100,
        rx=200,
    )
    assert sample.model_dump() == {
        "timestamp": "2026-04-07T10:00:00Z",
        "tx": 100,
        "rx": 200,
    }


# --- central_get_wlans ---


@pytest.mark.asyncio
async def test_get_wlans_page_one_emits_resumable_cursor(tools):
    ctx = make_ctx()
    with (
        patch(
            "pycentral.new_monitoring.wlans.WLAN.get_wlans",
            return_value=wlan_page([RAW_WLAN], total=125, next_cursor="2"),
        ) as mock_api,
        patch(
            "tools.wlans.get_all_wlans",
            side_effect=AssertionError("aggregation wrapper called"),
        ) as mock_get_all,
    ):
        result = await tools["central_get_wlans"](
            ctx,
            site_id="site-A",
            limit=50,
        )

    decoded = decode_cursor(
        result.next_cursor,
        expected_tool="central_get_wlans",
        expected_query_hash=hash_query(
            {
                "wlan_name": None,
                "site_id": "site-A",
                "serial_number": None,
                "sort": None,
                "include": None,
                "time_range": None,
                "start_time": None,
                "end_time": None,
            }
        ),
    )

    assert isinstance(result, WlanEnvelope)
    assert len(result.items) == 1
    assert isinstance(result.items[0], WLAN)
    assert result.items[0].model_dump() == {
        "wlan_name": "Corp-WiFi",
        "security_level": "Enterprise",
        "security": "WPA3",
        "band": "5GHz",
        "status": "enabled",
        "vlan": "10",
    }
    assert decoded.page_size == 50
    assert decoded.position == {"upstream_next": "2"}
    assert result.total == 125
    assert result.meta.total_available == 125
    assert result.truncated is False
    call_kwargs = mock_api.call_args.kwargs
    assert call_kwargs["site_id"] == "site-A"
    assert call_kwargs["serial_number"] is None
    assert call_kwargs["sort"] is None
    assert call_kwargs["limit"] == 50
    assert call_kwargs["next_page"] == 1
    mock_get_all.assert_not_called()


@pytest.mark.asyncio
async def test_get_wlans_last_page_is_terminal(tools):
    ctx = make_ctx()
    with patch(
        "tools.wlans.WLAN.get_wlans",
        return_value=wlan_page([RAW_WLAN], total=101, next_cursor=None),
    ):
        result = await tools["central_get_wlans"](ctx, limit=50)

    assert result.next_cursor is None
    assert result.total == 101
    assert result.meta.total_available == 101
    assert result.truncated is False


@pytest.mark.asyncio
async def test_get_wlans_cursor_replay_fetches_next_upstream_page(tools):
    ctx = make_ctx()
    with patch(
        "tools.wlans.WLAN.get_wlans",
        side_effect=[
            wlan_page([RAW_WLAN], total=75, next_cursor="2"),
            wlan_page([RAW_WLAN_2], total=75, next_cursor=None),
        ],
    ) as mock_api:
        first_page = await tools["central_get_wlans"](
            ctx,
            site_id="site-A",
            limit=50,
        )
        second_page = await tools["central_get_wlans"](
            ctx,
            site_id="site-A",
            cursor=first_page.next_cursor,
        )

    second_call = mock_api.call_args_list[1].kwargs
    assert second_call["next_page"] == 2
    assert second_call["limit"] == 50
    assert [item.wlan_name for item in second_page.items] == ["Guest-WiFi"]
    assert second_page.next_cursor is None


@pytest.mark.asyncio
async def test_get_wlans_rejects_limit_conflicting_with_cursor_page_size(tools):
    ctx = make_ctx()
    with patch(
        "tools.wlans.WLAN.get_wlans",
        return_value=wlan_page([RAW_WLAN], total=75, next_cursor="2"),
    ) as mock_api:
        first_page = await tools["central_get_wlans"](ctx, limit=50)
        with pytest.raises(ToolError) as exc_info:
            await tools["central_get_wlans"](
                ctx,
                limit=25,
                cursor=first_page.next_cursor,
            )

    error = json.loads(str(exc_info.value))
    assert error["code"] == "validation_error"
    assert error["retryable"] is False
    assert mock_api.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "replay_filters",
    [
        {"site_id": "site-B", "serial_number": "USTWM5206L"},
        {"site_id": "site-A", "serial_number": "CNBRK12345"},
    ],
)
async def test_get_wlans_rejects_cursor_replayed_with_different_query(
    tools,
    replay_filters,
):
    ctx = make_ctx()
    with patch(
        "tools.wlans.WLAN.get_wlans",
        return_value=wlan_page([RAW_WLAN], total=75, next_cursor="2"),
    ) as mock_api:
        first_page = await tools["central_get_wlans"](
            ctx,
            site_id="site-A",
            serial_number="USTWM5206L",
            limit=50,
        )
        with pytest.raises(ToolError) as exc_info:
            await tools["central_get_wlans"](
                ctx,
                cursor=first_page.next_cursor,
                **replay_filters,
            )

    error = json.loads(str(exc_info.value))
    assert error["code"] == "validation_error"
    assert "invalid or stale cursor" in error["message"]
    assert error["retryable"] is False
    assert mock_api.call_count == 1


@pytest.mark.asyncio
async def test_get_wlans_site_id_passed_to_api(tools):
    ctx = make_ctx()
    with patch(
        "tools.wlans.WLAN.get_wlans",
        return_value=wlan_page([RAW_WLAN]),
    ) as mock_fn:
        result = await tools["central_get_wlans"](ctx, site_id="site-abc")
    assert mock_fn.call_args.kwargs["site_id"] == "site-abc"
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_get_wlans_wlan_name_uses_direct_api_call(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {"code": 200, "msg": RAW_WLAN}
    with (
        patch("tools.wlans.get_all_wlans") as mock_get_all,
        patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)),
    ):
        result = await tools["central_get_wlans"](
            ctx,
            wlan_name="Corp-WiFi",
            cursor="not-valid-base64!",
        )
    assert len(result.items) == 1
    assert result.items[0].wlan_name == "Corp-WiFi"
    assert result.next_cursor is None
    assert result.truncated is False
    mock_get_all.assert_not_called()
    call_kwargs = ctx.lifespan_context["conn"].command.call_args.kwargs
    assert call_kwargs["api_method"] == "GET"
    assert call_kwargs["api_path"] == "network-monitoring/v1/wlans/Corp-WiFi"
    assert call_kwargs["api_params"] is None


@pytest.mark.asyncio
async def test_get_wlans_wlan_name_no_match(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {"code": 200, "msg": None}
    with patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
        result = await tools["central_get_wlans"](ctx, wlan_name="Unknown-SSID")
    assert isinstance(result, WlanEnvelope)
    assert result.items == []


@pytest.mark.asyncio
async def test_get_wlans_wlan_name_passes_site_id_to_direct_api(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {"code": 200, "msg": RAW_WLAN}
    with patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
        result = await tools["central_get_wlans"](
            ctx, wlan_name="Corp-WiFi", site_id="site-abc"
        )
    assert len(result.items) == 1
    assert ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"] == {
        "site_id": "site-abc"
    }


@pytest.mark.asyncio
async def test_get_wlans_empty_returns_string(tools):
    ctx = make_ctx()
    with patch("tools.wlans.WLAN.get_wlans", return_value=wlan_page()):
        result = await tools["central_get_wlans"](ctx)
    assert isinstance(result, WlanEnvelope)
    assert result.items == []
    assert result.meta.returned == 0


@pytest.mark.asyncio
async def test_get_wlans_api_error_returns_formatted_error(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.wlans.WLAN.get_wlans",
            side_effect=Exception("network error"),
        ),
        pytest.raises(ToolError, match="network error"),
    ):
        await tools["central_get_wlans"](ctx)


@pytest.mark.asyncio
async def test_get_wlans_sort_passed_to_api(tools):
    ctx = make_ctx()
    with patch(
        "tools.wlans.WLAN.get_wlans",
        return_value=wlan_page(),
    ) as mock_fn:
        await tools["central_get_wlans"](ctx, sort="wlanName asc")
    assert mock_fn.call_args.kwargs["sort"] == "wlanName ASC"


@pytest.mark.asyncio
async def test_get_wlans_serial_number_uses_list_path(tools):
    ctx = make_ctx()
    with patch(
        "tools.wlans.WLAN.get_wlans",
        return_value=wlan_page([RAW_WLAN, RAW_WLAN_2]),
    ) as mock_fn:
        result = await tools["central_get_wlans"](ctx, serial_number="USTWM5206L")
    assert isinstance(result, WlanEnvelope)
    assert len(result.items) == 2
    assert isinstance(result.items[0], WLAN)
    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs["serial_number"] == "USTWM5206L"
    assert call_kwargs["site_id"] is None
    assert call_kwargs["sort"] is None


@pytest.mark.asyncio
async def test_get_wlans_serial_number_and_wlan_name_client_side_filter(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.wlans.get_all_wlans",
            return_value=[RAW_WLAN_2, RAW_WLAN],
        ) as mock_get_all,
        patch("tools.wlans.WLAN.get_wlans") as mock_get_page,
    ):
        result = await tools["central_get_wlans"](
            ctx,
            serial_number="USTWM5206L",
            wlan_name="Corp-WiFi",
            cursor="not-valid-base64!",
        )
    assert isinstance(result, WlanEnvelope)
    assert len(result.items) == 1
    assert result.items[0].wlan_name == "Corp-WiFi"
    assert result.next_cursor is None
    assert result.truncated is False
    mock_get_all.assert_called_once()
    mock_get_page.assert_not_called()


@pytest.mark.asyncio
async def test_get_wlans_serial_number_wlan_name_no_match_returns_empty_string(tools):
    ctx = make_ctx()
    with patch("tools.wlans.get_all_wlans", return_value=[RAW_WLAN, RAW_WLAN_2]):
        result = await tools["central_get_wlans"](
            ctx, serial_number="USTWM5206L", wlan_name="NonExistent-SSID"
        )
    assert result.items == []


@pytest.mark.asyncio
async def test_get_wlans_serial_number_with_site_id(tools):
    ctx = make_ctx()
    with patch(
        "tools.wlans.WLAN.get_wlans",
        return_value=wlan_page([RAW_WLAN]),
    ) as mock_fn:
        result = await tools["central_get_wlans"](
            ctx, serial_number="USTWM5206L", site_id="site-xyz"
        )
    assert len(result.items) == 1
    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs["serial_number"] == "USTWM5206L"
    assert call_kwargs["site_id"] == "site-xyz"


@pytest.mark.asyncio
async def test_get_wlans_wlan_name_non_200_returns_formatted_error(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {
        "code": 404,
        "msg": "not found",
    }
    with patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
        result = await tools["central_get_wlans"](ctx, wlan_name="Bad-WLAN")
    assert result.items == []


# --- central_get_wlans include=throughput ---


@pytest.mark.asyncio
async def test_get_wlans_include_throughput_success(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.side_effect = [
        {"code": 200, "msg": RAW_WLAN},
        {"code": 200, "msg": RAW_STATS},
    ]
    with patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
        result = await tools["central_get_wlans"](
            ctx,
            wlan_name="Corp-WiFi",
            include=["throughput"],
            cursor="not-valid-base64!",
        )
    assert isinstance(result, WlanEnvelope)
    assert result.next_cursor is None
    assert result.truncated is False
    samples = result.items[0].throughput
    assert samples is not None
    assert all(isinstance(sample, WLANThroughputSample) for sample in samples)
    assert [sample.model_dump() for sample in samples] == CLEANED_STATS


@pytest.mark.asyncio
async def test_get_wlans_include_throughput_uses_default_time_range(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.side_effect = [
        {"code": 200, "msg": RAW_WLAN},
        {"code": 200, "msg": RAW_STATS},
    ]
    with patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
        await tools["central_get_wlans"](
            ctx,
            wlan_name="Corp-WiFi",
            include=["throughput"],
        )
    call_kwargs = ctx.lifespan_context["conn"].command.call_args_list[1].kwargs
    assert (
        call_kwargs["api_path"]
        == "network-monitoring/v1/wlans/Corp-WiFi/throughput-trends"
    )
    assert "timestamp gt" in call_kwargs["api_params"]["filter"]
    assert "timestamp lt" in call_kwargs["api_params"]["filter"]


@pytest.mark.asyncio
async def test_get_wlans_include_throughput_explicit_time_window(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.side_effect = [
        {"code": 200, "msg": RAW_WLAN},
        {"code": 200, "msg": RAW_STATS},
    ]
    with patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
        await tools["central_get_wlans"](
            ctx,
            wlan_name="Corp-WiFi",
            include=["throughput"],
            start_time="2026-04-07T00:00:00.000Z",
            end_time="2026-04-07T23:59:59.999Z",
        )
    filter_str = (
        ctx.lifespan_context["conn"]
        .command.call_args_list[1]
        .kwargs["api_params"]["filter"]
    )
    assert "2026-04-07T00:00:00.000Z" in filter_str
    assert "2026-04-07T23:59:59.999Z" in filter_str


@pytest.mark.asyncio
async def test_get_wlans_include_throughput_non_200_raises_tool_error(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.side_effect = [
        {"code": 200, "msg": RAW_WLAN},
        {"code": 404, "msg": "not found"},
    ]
    with (
        patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)),
        pytest.raises(ToolError, match="404"),
    ):
        await tools["central_get_wlans"](
            ctx,
            wlan_name="Corp-WiFi",
            include=["throughput"],
        )


@pytest.mark.asyncio
async def test_get_wlans_include_throughput_empty_is_additive_empty_list(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.side_effect = [
        {"code": 200, "msg": RAW_WLAN},
        {"code": 200, "msg": None},
    ]
    with patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
        result = await tools["central_get_wlans"](
            ctx,
            wlan_name="Corp-WiFi",
            include=["throughput"],
        )
    assert result.items[0].throughput == []


@pytest.mark.asyncio
async def test_get_wlans_include_throughput_all_null_samples_is_empty_list(tools):
    ctx = make_ctx()
    null_stats = {
        "graph": {
            "keys": ["tx", "rx"],
            "samples": [
                {"data": [None, None], "timestamp": "2026-04-07T10:00:00Z"},
                {"data": [None, None], "timestamp": "2026-04-07T10:05:00Z"},
            ],
        },
        "id": "wlans/__nonexistent__",
        "metric": "wlan_throughput",
        "type": "network-monitoring/access-point-monitoring",
    }
    ctx.lifespan_context["conn"].command.side_effect = [
        {"code": 200, "msg": RAW_WLAN},
        {"code": 200, "msg": null_stats},
    ]
    with patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
        result = await tools["central_get_wlans"](
            ctx,
            wlan_name="Corp-WiFi",
            include=["throughput"],
        )
    assert result.items[0].throughput == []


@pytest.mark.asyncio
async def test_get_wlans_include_throughput_exception_raises_tool_error(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.wlans.asyncio.to_thread",
            side_effect=Exception("connection refused"),
        ),
        pytest.raises(ToolError, match="connection refused"),
    ):
        await tools["central_get_wlans"](
            ctx,
            wlan_name="Corp-WiFi",
            include=["throughput"],
        )


@pytest.mark.asyncio
async def test_get_wlans_throughput_requires_name_before_connection(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.wlans.api_context",
            side_effect=AssertionError("connection opened"),
        ) as mock_context,
        pytest.raises(ToolError, match=r"throughput.*wlan_name"),
    ):
        await tools["central_get_wlans"](ctx, include=["throughput"])
    mock_context.assert_not_called()


@pytest.mark.asyncio
async def test_get_wlans_time_params_require_throughput_before_connection(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.wlans.api_context",
            side_effect=AssertionError("connection opened"),
        ) as mock_context,
        pytest.raises(ToolError, match=r"time_range.*include='throughput'"),
    ):
        await tools["central_get_wlans"](ctx, time_range="last_24h")
    mock_context.assert_not_called()


@pytest.mark.asyncio
async def test_get_wlans_limit_is_passed_with_authoritative_accounting(tools):
    ctx = make_ctx()
    with patch(
        "tools.wlans.WLAN.get_wlans",
        return_value=wlan_page([RAW_WLAN], total=2, next_cursor="2"),
    ) as mock_api:
        result = await tools["central_get_wlans"](ctx, limit=1)
    assert len(result.items) == 1
    assert result.truncated is False
    assert result.total == 2
    assert result.meta.total_available == 2
    assert result.next_cursor is not None
    assert mock_api.call_args.kwargs["limit"] == 1
