import json
from unittest.mock import call, patch

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

import tools.client_analytics as mod
from tests.conftest import FakeMCP, make_ctx
from utils.cursor import decode_cursor, hash_query

START_AT = "2026-07-24T06:00:00.000Z"
END_AT = "2026-07-24T09:00:00.000Z"

USAGE_SAMPLE = {"data": [1048576, 524288], "ts": "2026-07-24T06:00:00Z"}
TOP_CLIENT = {
    "clientName": "laptop-1",
    "macAddress": "aa:bb:cc:dd:ee:ff",
    "usage": 8339422,
    "clientConnectionType": "Wireless",
    "type": "network-monitoring/client-monitoring",
    "id": "aa:bb:cc:dd:ee:ff",
    "siteName": "HQ",
    "siteId": "site-1",
}
TREND_SAMPLE = {"data": [2, 4, 1], "ts": "2026-07-24T06:00:00Z"}
MOBILITY_EVENT = {
    "occurredAt": "2026-07-24T08:30:00.000Z",
    "roamTime": "168",
    "wlanName": "corp",
    "sourceAp": "ap-1",
    "destinationAp": "ap-2",
    "fromChannel": "1",
    "toChannel": "50",
    "fromBssid": "32:44:3a:31:44:3a",
    "toBssid": "dc:0b:8e:d5:d0:00",
    "rssi": "-42",
    "radioBand": "5 GHz",
    "roamProtocol": "11r",
    "type": "network-monitoring/client-monitoring",
    "id": "roam-1",
}
# Shape recorded from a live export call: nulls for absent dimensions, numbers
# as strings, servers keyed by stage.
EXPORT_STAGE_AUTH = {
    "type": "auth",
    "data": [
        {
            "type": "SUMMARY",
            "attempts": "1307",
            "failures": "197",
            "success": "779",
            "delays": "331",
            "clients": None,
            "topReasons": None,
        },
        {
            "type": "DELAY",
            "delays": "331",
            "clients": ["e8:9c:25:5c:a4:a1"],
            "accessDevice": ["8c:79:09:c2:15:b8"],
            "band": ["5 GHz"],
            "wlans": ["1X"],
            "topReasons": ["UNKNOWN"],
            "authTopServers": ["10.128.195.2", ""],
            "dhcpTopServers": None,
        },
        {
            "type": "FAILED",
            "failures": "197",
            "clients": ["d0:ee:00:00:00:28"],
            "accessDevice": ["68:51:34:c3:46:9f"],
            "band": ["5 GHz"],
            "wlans": ["BLR-PSK-1"],
            "topReasons": ["Auth Failure: MIC Failure"],
            "authTopServers": ["10.97.55.234"],
        },
    ],
}
EXPORT_STAGE_DNS_EMPTY = {
    "type": "dns",
    "data": [
        {
            "type": "SUMMARY",
            "attempts": "-1",
            "failures": "-1",
            "success": "-1",
            "delays": "-1",
        },
        {"type": "DELAY", "clients": [], "topReasons": [], "dnsTopServers": []},
        {"type": "FAILED", "clients": [], "topReasons": [], "dnsTopServers": []},
    ],
}


@pytest.fixture
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


def response(payload: dict, code: int = 200) -> dict:
    return {"code": code, "msg": payload}


def fixed_window():
    return patch(
        "tools.client_analytics._resolve_time_window",
        return_value=(START_AT, END_AT),
    )


def assert_get_only(ctx) -> None:
    for api_call in ctx.lifespan_context["conn"].command.call_args_list:
        assert api_call.kwargs["api_method"] == "GET"


def validation_error(exc_info) -> str:
    error = json.loads(str(exc_info.value))
    assert error["code"] == "validation_error"
    return error["message"]


def test_registers_only_client_analytics_tool(tools):
    assert list(tools) == ["central_get_client_analytics"]


@pytest.mark.asyncio
async def test_fastmcp_contract_bounds_limit_and_is_read_only():
    mcp = FastMCP("client-analytics-contract")
    mod.register(mcp)

    tool = await mcp.get_tool("central_get_client_analytics")
    limit_schema = tool.parameters["properties"]["limit"]
    integer_schema = next(
        schema for schema in limit_schema["anyOf"] if schema.get("type") == "integer"
    )

    assert integer_schema["minimum"] == 1
    assert integer_schema["maximum"] == mod.CLIENT_ANALYTICS_MAX_LIMIT
    assert tool.parameters["properties"]["time_range"]["default"] == "last_24h"
    assert "score" not in tool.parameters["properties"]["view"]["anyOf"][0]["enum"]
    assert tool.annotations.readOnlyHint is True
    assert set(tool.output_schema["properties"]) == {
        "items",
        "next_cursor",
        "truncated",
        "total",
        "meta",
        "overall_score",
    }
    assert "OnboardingStageSummary" in tool.output_schema["$defs"]


@pytest.mark.asyncio
async def test_usage_defaults_to_primary_usage_endpoint(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = response(
        {
            "interval": "5 mins",
            "keys": ["txUsage", "rxUsage"],
            "samples": [USAGE_SAMPLE],
            "type": "network-monitoring/client-monitoring",
        }
    )

    with fixed_window():
        result = await tools["central_get_client_analytics"](
            ctx,
            metric="usage",
            site_id="site-1",
            mac_address="aa:bb:cc:dd:ee:ff",
        )

    assert result.items[0].kind == "usage_sample"
    assert result.items[0].data == [1048576, 524288]
    api_call = ctx.lifespan_context["conn"].command.call_args
    assert api_call.kwargs["api_path"] == mod.USAGE_PATH
    assert api_call.kwargs["api_params"]["filter"] == (
        f"timestamp gt {START_AT} and timestamp lt {END_AT} "
        "and siteId eq 'site-1' "
        "and macAddress eq 'aa:bb:cc:dd:ee:ff'"
    )
    assert_get_only(ctx)


@pytest.mark.asyncio
async def test_usage_top_view_maps_top_n_to_endpoint_limit(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = response(
        {"items": [TOP_CLIENT], "count": 1}
    )

    with fixed_window():
        result = await tools["central_get_client_analytics"](
            ctx,
            metric="usage",
            view="top",
            site_name="HQ",
            top_n=3,
        )

    assert result.items[0].kind == "top_client_usage"
    assert result.items[0].mac_address == "aa:bb:cc:dd:ee:ff"
    assert not hasattr(result.items[0], "resource_id")
    api_call = ctx.lifespan_context["conn"].command.call_args
    assert api_call.kwargs["api_path"] == mod.TOP_USAGE_PATH
    assert api_call.kwargs["api_params"] == {
        "start-at": START_AT,
        "end-at": END_AT,
        "site-name": "HQ",
        "limit": 3,
    }
    assert_get_only(ctx)


@pytest.mark.asyncio
async def test_usage_trend_view_maps_grouping_parameters(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = response(
        {
            "interval": "5 mins",
            "keys": ["Wired", "Wireless", "Remote"],
            "samples": [TREND_SAMPLE],
            "id": "trend-1",
            "type": "network-monitoring/client-monitoring",
        }
    )

    with fixed_window():
        result = await tools["central_get_client_analytics"](
            ctx,
            metric="usage",
            view="trend",
            group_by="TYPE",
            client_type="ALL",
        )

    assert result.items[0].kind == "client_trend_sample"
    api_call = ctx.lifespan_context["conn"].command.call_args
    assert api_call.kwargs["api_path"] == mod.TREND_PATH
    assert api_call.kwargs["api_params"]["group-by"] == "TYPE"
    assert api_call.kwargs["api_params"]["type"] == "ALL"
    assert_get_only(ctx)


@pytest.mark.asyncio
async def test_view_from_another_metric_is_rejected_before_api_call(tools):
    ctx = make_ctx()

    with pytest.raises(ToolError) as exc_info:
        await tools["central_get_client_analytics"](
            ctx, metric="usage", view="summary"
        )

    assert "must be one of: usage, top, trend" in validation_error(exc_info)
    ctx.lifespan_context["conn"].command.assert_not_called()


@pytest.mark.asyncio
async def test_mobility_requires_mac_before_api_call(tools):
    ctx = make_ctx()

    with pytest.raises(ToolError) as exc_info:
        await tools["central_get_client_analytics"](ctx, metric="mobility")

    assert "mac_address is required" in validation_error(exc_info)
    ctx.lifespan_context["conn"].command.assert_not_called()


@pytest.mark.asyncio
async def test_mobility_encodes_mac_and_round_trips_opaque_cursor(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.side_effect = [
        response({"items": [MOBILITY_EVENT], "count": 1, "total": 2, "next": "2"}),
        response(
            {
                "items": [{**MOBILITY_EVENT, "sourceAp": "ap-2"}],
                "count": 1,
                "total": 2,
                "next": None,
            }
        ),
    ]

    with fixed_window():
        first = await tools["central_get_client_analytics"](
            ctx,
            metric="mobility",
            mac_address="aa:bb:cc:dd:ee:ff",
            site_id="site-1",
            limit=1,
        )
        second = await tools["central_get_client_analytics"](
            ctx,
            metric="mobility",
            mac_address="aa:bb:cc:dd:ee:ff",
            site_id="site-1",
            cursor=first.next_cursor,
        )

    assert first.next_cursor is not None
    assert first.next_cursor != "2"
    decoded = decode_cursor(
        first.next_cursor,
        expected_tool=mod.CLIENT_ANALYTICS_TOOL_NAME,
        expected_query_hash=hash_query(
            {
                "metric": "mobility",
                "mac_address": "aa:bb:cc:dd:ee:ff",
                "site_id": "site-1",
                "site_name": None,
                "time_range": "last_24h",
                "start_time": None,
                "end_time": None,
            }
        ),
    )
    assert decoded.page_size == 1
    assert decoded.position == {"upstream_next": "2"}
    assert second.next_cursor is None
    assert second.items[0].source_ap == "ap-2"
    mobility_path = (
        "network-monitoring/v1/clients/aa%3Abb%3Acc%3Add%3Aee%3Aff/mobility-trail"
    )
    assert ctx.lifespan_context["conn"].command.call_args_list == [
        call(
            api_method="GET",
            api_path=mobility_path,
            api_params={
                "start-at": START_AT,
                "end-at": END_AT,
                "site-id": "site-1",
                "limit": 1,
            },
        ),
        call(
            api_method="GET",
            api_path=mobility_path,
            api_params={
                "start-at": START_AT,
                "end-at": END_AT,
                "site-id": "site-1",
                "limit": 1,
                "next": "2",
            },
        ),
    ]
    assert_get_only(ctx)


@pytest.mark.asyncio
async def test_mobility_cursor_is_query_bound(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = response(
        {"items": [MOBILITY_EVENT], "count": 1, "total": 2, "next": "2"}
    )

    with fixed_window():
        first = await tools["central_get_client_analytics"](
            ctx,
            metric="mobility",
            mac_address="aa:bb:cc:dd:ee:ff",
            site_id="site-1",
            limit=1,
        )
        with pytest.raises(ToolError, match="invalid or stale cursor"):
            await tools["central_get_client_analytics"](
                ctx,
                metric="mobility",
                mac_address="aa:bb:cc:dd:ee:ff",
                site_id="site-2",
                cursor=first.next_cursor,
            )

    assert ctx.lifespan_context["conn"].command.call_count == 1


@pytest.mark.asyncio
async def test_onboarding_defaults_to_summary_view_with_stage_items(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = response(
        {
            "id": "64c4c4e2-2832-482a-be51-7b6734fccd39",
            "type": "CLIENT_CONNECTIVITY",
            "count": 2,
            "items": [EXPORT_STAGE_AUTH, EXPORT_STAGE_DNS_EMPTY],
            "overallSuccessScore": "68.25",
        }
    )

    with fixed_window():
        result = await tools["central_get_client_analytics"](
            ctx,
            metric="onboarding",
            site_id="site-1",
            view_type="BY_ATTEMPTS",
            version="1",
        )

    auth, dns = result.items
    assert result.total == 2
    assert result.overall_score == 68.25
    assert auth.kind == "onboarding_summary"
    assert auth.stage == "auth"
    assert (auth.attempts, auth.failures, auth.success, auth.delays) == (
        1307,
        197,
        779,
        331,
    )
    # Central's stage score counts delayed attempts as successful.
    assert auth.success_percent == round((1307 - 197) / 1307 * 100, 2) == 84.93
    assert auth.failure_reasons == ["Auth Failure: MIC Failure"]
    assert auth.delay_reasons == ["UNKNOWN"]
    assert auth.failed.servers == ["10.97.55.234"]
    assert auth.delayed.access_devices == ["8c:79:09:c2:15:b8"]
    assert dns.attempts is None
    assert dns.success_percent is None
    assert dns.failed.clients == []
    serialized = result.model_dump()
    assert "failed" not in serialized["items"][0]
    assert serialized["meta"]["omitted_fields"] == ["delayed", "failed"]
    assert "resource_id" not in serialized["items"][0]
    api_call = ctx.lifespan_context["conn"].command.call_args
    assert api_call.kwargs["api_path"] == mod.ONBOARDING_SUMMARY_PATH
    assert api_call.kwargs["api_params"] == {
        "start-at": START_AT,
        "end-at": END_AT,
        "site-id": "site-1",
        "version": "1",
        "view-type": "BY_ATTEMPTS",
    }
    assert_get_only(ctx)


@pytest.mark.asyncio
async def test_onboarding_summary_detailed_keeps_dimensions(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = response(
        {"count": 1, "items": [EXPORT_STAGE_AUTH], "overallSuccessScore": "68.25"}
    )

    with fixed_window():
        result = await tools["central_get_client_analytics"](
            ctx, metric="onboarding", stage="auth", response_format="detailed"
        )

    item = result.model_dump()["items"][0]
    assert item["failed"]["wlans"] == ["BLR-PSK-1"]
    assert item["delayed"]["servers"] == ["10.128.195.2", ""]
    api_call = ctx.lifespan_context["conn"].command.call_args
    assert api_call.kwargs["api_params"]["stage"] == "auth"


@pytest.mark.asyncio
async def test_onboarding_summary_rejects_status_and_field(tools):
    ctx = make_ctx()

    with pytest.raises(ToolError) as exc_info:
        await tools["central_get_client_analytics"](
            ctx, metric="onboarding", status="FAILED"
        )

    assert "'status' is not supported" in validation_error(exc_info)
    ctx.lifespan_context["conn"].command.assert_not_called()


@pytest.mark.asyncio
async def test_onboarding_reasons_view_lowercases_stage(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = response(
        {
            "id": "reasons-1",
            "type": "TOP_FAILED_REASONS",
            "items": [
                {"type": "AUTH", "reasons": ["timeout", "bad password"]},
                {"type": "DNS", "reasons": []},
            ],
            "count": 2,
        }
    )

    with fixed_window():
        result = await tools["central_get_client_analytics"](
            ctx,
            metric="onboarding",
            view="reasons",
            status="FAILED",
        )

    assert result.total == 2
    assert result.overall_score is None
    assert result.items[0].kind == "onboarding_reasons"
    assert result.items[0].stage == "auth"
    assert result.items[0].reasons == ["timeout", "bad password"]
    api_call = ctx.lifespan_context["conn"].command.call_args
    assert api_call.kwargs["api_path"] == mod.ONBOARDING_REASONS_PATH
    assert api_call.kwargs["api_params"]["status"] == "FAILED"
    assert_get_only(ctx)


@pytest.mark.asyncio
async def test_onboarding_count_view(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = response(
        {
            "id": "count-1",
            "type": "TOP_FAILED_COUNT",
            "items": [
                {
                    "type": "auth",
                    "data": [
                        {
                            "type": "TOPCLIENTS_FAILED_COUNT",
                            "value": "AA:AA:AA:AA:AA:AA",
                            "field": "topclients",
                            "count": 42,
                            "stage": "auth",
                        }
                    ],
                }
            ],
            "count": 1,
        }
    )

    with fixed_window():
        result = await tools["central_get_client_analytics"](
            ctx,
            metric="onboarding",
            view="count",
            status="FAILED",
            field="topclients",
        )

    assert result.items[0].kind == "onboarding_count"
    assert result.items[0].stage == "auth"
    assert result.items[0].data[0].count == 42
    assert result.items[0].data[0].model_dump() == {
        "value": "AA:AA:AA:AA:AA:AA",
        "field": "topclients",
        "count": 42,
        "stage": "auth",
    }
    api_call = ctx.lifespan_context["conn"].command.call_args
    assert api_call.kwargs["api_path"] == mod.ONBOARDING_COUNT_PATH
    assert api_call.kwargs["api_params"]["field"] == "topclients"
    assert_get_only(ctx)


@pytest.mark.asyncio
async def test_onboarding_null_items_shape_is_empty_envelope(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = response(
        {"overallSuccessScore": None, "items": None, "count": None}
    )

    with fixed_window():
        result = await tools["central_get_client_analytics"](ctx, metric="onboarding")

    assert result.items == []
    assert result.total == 0
    assert result.overall_score is None
    assert result.meta.returned == 0


@pytest.mark.asyncio
async def test_empty_result_is_empty_envelope(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = response(
        {"items": [], "count": 0}
    )

    with fixed_window():
        result = await tools["central_get_client_analytics"](
            ctx, metric="usage", view="top"
        )

    assert result.items == []
    assert result.total == 0
    assert result.meta.returned == 0
    assert result.next_cursor is None


@pytest.mark.asyncio
async def test_usage_samples_respect_shared_response_ceiling(tools):
    ctx = make_ctx()
    samples = [
        {"data": [index, index], "ts": f"2026-07-24T06:{index % 60:02d}:00Z"}
        for index in range(mod.MAX_RESPONSE_ITEMS + 1)
    ]
    ctx.lifespan_context["conn"].command.return_value = response(
        {
            "interval": "5 mins",
            "keys": ["txUsage", "rxUsage"],
            "samples": samples,
            "type": "network-monitoring/client-monitoring",
        }
    )

    with fixed_window():
        result = await tools["central_get_client_analytics"](ctx, metric="usage")

    assert len(result.items) == mod.MAX_RESPONSE_ITEMS
    assert result.truncated is True
    assert result.total == mod.MAX_RESPONSE_ITEMS + 1
    assert result.meta.total_available == mod.MAX_RESPONSE_ITEMS + 1


@pytest.mark.asyncio
async def test_limit_over_max_is_rejected_before_api_call(tools):
    ctx = make_ctx()

    with pytest.raises(ToolError) as exc_info:
        await tools["central_get_client_analytics"](
            ctx,
            metric="mobility",
            mac_address="aa:bb:cc:dd:ee:ff",
            limit=mod.CLIENT_ANALYTICS_MAX_LIMIT + 1,
        )

    assert "limit must be between" in validation_error(exc_info)
    ctx.lifespan_context["conn"].command.assert_not_called()


@pytest.mark.asyncio
async def test_non_200_is_structured_error(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = response(
        {"detail": "service unavailable"}, code=503
    )

    with fixed_window(), pytest.raises(ToolError) as exc_info:
        await tools["central_get_client_analytics"](ctx, metric="usage")

    error = json.loads(str(exc_info.value))
    assert error["code"] == "upstream_server_error"
    assert error["retryable"] is True
    assert "503" in error["message"]
    assert_get_only(ctx)
