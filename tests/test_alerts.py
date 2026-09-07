import json

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

import tools.alerts as mod
from constants import MAX_PAGE_SIZE
from models import Alert, AlertEnvelope
from tests.conftest import FakeMCP, make_ctx
from utils.alerts import clean_alert_data
from utils.cursor import decode_cursor, hash_query


@pytest.fixture
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


def _make_alert_response(items=None, total=0, next_cursor=None):
    return {"code": 200, "msg": {"items": items or [], "total": total, "next": next_cursor}}


@pytest.mark.asyncio
async def test_get_alerts_fastmcp_contract_is_bounded_and_read_only():
    mcp = FastMCP("alerts-contract")
    mod.register(mcp)

    tool = await mcp.get_tool("central_get_alerts")
    limit_schema = tool.parameters["properties"]["limit"]

    assert limit_schema["minimum"] == 1
    assert limit_schema["maximum"] == MAX_PAGE_SIZE
    cursor_schema = tool.parameters["properties"]["cursor"]
    assert {schema["type"] for schema in cursor_schema["anyOf"]} == {
        "string",
        "null",
    }
    assert tool.annotations.readOnlyHint is True
    assert tool.output_schema["description"].startswith("Typed response envelope")
    output_cursor_schema = tool.output_schema["properties"]["next_cursor"]
    assert {schema["type"] for schema in output_cursor_schema["anyOf"]} == {
        "string",
        "null",
    }


RAW_ALERT = {
    "summary": "AP Down",
    "clearedReason": None,
    "createdAt": "2026-03-01T00:00:00Z",
    "priority": "High",
    "updatedAt": None,
    "deviceType": "Access Point",
    "updatedBy": None,
    "name": "ap-down",
    "status": "Active",
    "category": "System",
    "severity": "Critical",
}


@pytest.mark.asyncio
async def test_get_alerts_default_status_active(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_alert_response()
    await tools["central_get_alerts"](ctx, site_id="site-1")
    params = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
    assert "status eq 'Active'" in params["filter"]
    assert "siteId eq 'site-1'" in params["filter"]


@pytest.mark.asyncio
async def test_get_alerts_cleared_status(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_alert_response()
    await tools["central_get_alerts"](ctx, site_id="site-1", status="Cleared")
    assert "status eq 'Cleared'" in ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]["filter"]


@pytest.mark.asyncio
async def test_get_alerts_with_device_type(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_alert_response()
    await tools["central_get_alerts"](ctx, site_id="site-1", device_type="Switch")
    assert "deviceType eq 'Switch'" in ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]["filter"]


@pytest.mark.asyncio
async def test_get_alerts_with_category(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_alert_response()
    await tools["central_get_alerts"](ctx, site_id="site-1", category="Security")
    assert "category eq 'Security'" in ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]["filter"]


@pytest.mark.asyncio
async def test_get_alerts_default_sort(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_alert_response()
    await tools["central_get_alerts"](ctx, site_id="site-1")
    assert ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]["sort"] == "severity desc"


@pytest.mark.asyncio
async def test_get_alerts_custom_sort(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_alert_response()
    await tools["central_get_alerts"](ctx, site_id="site-1", sort="createdAt asc")
    assert ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]["sort"] == "createdAt asc"


@pytest.mark.asyncio
async def test_get_alerts_all_filters_combined(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_alert_response()
    await tools["central_get_alerts"](
        ctx,
        site_id="site-1",
        status="Active",
        device_type="Gateway",
        category="WAN",
    )
    filter_str = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]["filter"]
    assert "status eq 'Active'" in filter_str
    assert "deviceType eq 'Gateway'" in filter_str
    assert "category eq 'WAN'" in filter_str
    assert "siteId eq 'site-1'" in filter_str


@pytest.mark.asyncio
async def test_get_alerts_default_limit(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_alert_response()
    await tools["central_get_alerts"](ctx, site_id="site-1")
    assert ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]["limit"] == 50


@pytest.mark.asyncio
async def test_get_alerts_custom_limit(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_alert_response()
    await tools["central_get_alerts"](ctx, site_id="site-1", limit=25)
    assert ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]["limit"] == 25


@pytest.mark.asyncio
async def test_get_alerts_no_cursor_when_none(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_alert_response()
    await tools["central_get_alerts"](ctx, site_id="site-1")
    assert "next" not in ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]


@pytest.mark.asyncio
async def test_get_alerts_cursor_forwarded(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.side_effect = [
        _make_alert_response(next_cursor="42"),
        _make_alert_response(),
    ]

    first = await tools["central_get_alerts"](ctx, site_id="site-1")
    await tools["central_get_alerts"](
        ctx,
        site_id="site-1",
        cursor=first.next_cursor,
    )

    assert ctx.lifespan_context["conn"].command.call_args_list[1].kwargs[
        "api_params"
    ]["next"] == "42"


@pytest.mark.asyncio
async def test_get_alerts_returns_paginated_model(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_alert_response(
        items=[RAW_ALERT], total=100, next_cursor="2"
    )
    result = await tools["central_get_alerts"](ctx, site_id="site-1")
    assert isinstance(result, AlertEnvelope)
    assert result.total == 100
    assert isinstance(result.next_cursor, str)
    assert result.next_cursor
    decoded = decode_cursor(
        result.next_cursor,
        expected_tool="central_get_alerts",
        expected_query_hash=hash_query(
            {
                "status": "Active",
                "device_type": None,
                "category": None,
                "site_id": "site-1",
                "sort": "severity desc",
            }
        ),
    )
    assert decoded.position == {"upstream_next": "2"}
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_get_alerts_next_cursor_none_at_last_page(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_alert_response(
        items=[RAW_ALERT], total=1, next_cursor=None
    )
    result = await tools["central_get_alerts"](ctx, site_id="site-1")
    assert isinstance(result, AlertEnvelope)
    assert result.next_cursor is None


@pytest.mark.asyncio
async def test_get_alerts_cursor_round_trip_and_query_binding(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.side_effect = [
        _make_alert_response(items=[RAW_ALERT], total=2, next_cursor="2"),
        _make_alert_response(
            items=[{**RAW_ALERT, "summary": "Switch Down"}],
            total=2,
        ),
    ]

    first = await tools["central_get_alerts"](
        ctx,
        site_id="site-1",
        limit=1,
    )
    decoded = decode_cursor(
        first.next_cursor,
        expected_tool="central_get_alerts",
        expected_query_hash=hash_query(
            {
                "status": "Active",
                "device_type": None,
                "category": None,
                "site_id": "site-1",
                "sort": "severity desc",
            }
        ),
    )
    assert decoded.page_size == 1
    assert decoded.position == {"upstream_next": "2"}

    second = await tools["central_get_alerts"](
        ctx,
        site_id="site-1",
        cursor=first.next_cursor,
    )
    assert second.items[0].summary == "Switch Down"
    assert second.next_cursor is None
    assert ctx.lifespan_context["conn"].command.call_args_list[1].kwargs[
        "api_params"
    ] == {
        "sort": "severity desc",
        "limit": 1,
        "filter": "status eq 'Active' and siteId eq 'site-1'",
        "next": "2",
    }


@pytest.mark.asyncio
async def test_get_alerts_rejects_cross_query_cursor_replay(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_alert_response(
        next_cursor="2"
    )
    first = await tools["central_get_alerts"](ctx, site_id="site-1")

    with pytest.raises(ToolError) as exc_info:
        await tools["central_get_alerts"](
            ctx,
            site_id="site-1",
            status="Cleared",
            cursor=first.next_cursor,
        )

    error = json.loads(str(exc_info.value))
    assert "invalid or stale cursor" in error["message"]


@pytest.mark.asyncio
async def test_get_alerts_empty_returns_empty_envelope(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_alert_response()
    result = await tools["central_get_alerts"](ctx, site_id="site-1")
    assert isinstance(result, AlertEnvelope)
    assert result.items == []
    assert result.meta.returned == 0


@pytest.mark.asyncio
async def test_get_alerts_returns_tool_error_on_non_200(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {
        "code": 500, "msg": "Internal Server Error"
    }
    with pytest.raises(ToolError, match="Internal Server Error"):
        await tools["central_get_alerts"](ctx, site_id="site-1")


# ---------------------------------------------------------------------------
# clean_alert_data
# ---------------------------------------------------------------------------

_RAW_ALERT_DATA = {
    "summary": "Device Offline",
    "clearedReason": None,
    "createdAt": "2026-03-21T10:00:00Z",
    "priority": "High",
    "updatedAt": "2026-03-21T10:05:00Z",
    "deviceType": "Access Point",
    "updatedBy": "system",
    "name": "AP Offline",
    "status": "Active",
    "category": "System",
    "severity": "Critical",
}


def test_clean_alert_data_returns_alert_models():
    result = clean_alert_data([_RAW_ALERT_DATA])
    assert len(result) == 1
    assert isinstance(result[0], Alert)


def test_clean_alert_data_field_mapping():
    a = clean_alert_data([_RAW_ALERT_DATA])[0]
    assert a.summary == "Device Offline"
    assert a.severity == "Critical"
    assert a.status == "Active"
    assert a.category == "System"
    assert a.priority == "High"
    assert a.cleared_reason is None
    assert a.device_type == "Access Point"


def test_clean_alert_data_multiple():
    raw2 = {**_RAW_ALERT_DATA, "summary": "CPU High", "severity": "Major"}
    result = clean_alert_data([_RAW_ALERT_DATA, raw2])
    assert len(result) == 2
    assert result[1].summary == "CPU High"
    assert result[1].severity == "Major"
