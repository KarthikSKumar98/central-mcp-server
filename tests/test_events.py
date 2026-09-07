import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

import tools.events as mod
from constants import MAX_PAGE_SIZE
from models import (
    CompactEventFilters,
    Event,
    EventEnvelope,
    EventFacetsEnvelope,
    EventFilters,
)
from tests.conftest import FakeMCP, make_ctx
from utils.cursor import decode_cursor, hash_query
from utils.events import (
    _resolve_time_window,
    clean_event_filters,
    compact_event_filters,
)


@pytest.fixture
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


def _fake_time_window():
    start = datetime(2026, 3, 21, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 3, 21, 1, 0, 0, tzinfo=timezone.utc)
    return start, end


def _make_events_response(events=None, total=0, next_cursor=None):
    return {"code": 200, "msg": {"events": events or [], "total": total, "next": next_cursor}}


RAW_EVENT = {
    "eventId": "ev-type-1",
    "eventIdentifier": "ev-uid-1",
    "serialNumber": "SN001",
    "timeAt": "2026-03-21T00:00:00.000Z",
    "eventName": "AP Down",
    "category": "System",
    "sourceType": "Access Point",
    "sourceName": "ap-lobby",
    "description": "AP went offline",
    "clientMacAddress": None,
    "deviceMacAddress": "aa:bb:cc:dd:ee:ff",
    "stackId": None,
    "bssid": None,
    "reason": None,
    "severity": "High",
}


@pytest.mark.parametrize(
    "start_time,end_time",
    [
        ("2026-03-21T00:00:00.000Z", None),
        (None, "2026-03-21T01:00:00.000Z"),
    ],
)
def test_resolve_time_window_rejects_partial_custom_window(start_time, end_time):
    with pytest.raises(ValueError, match="start_time and end_time"):
        _resolve_time_window("last_1h", start_time, end_time)


# ---------------------------------------------------------------------------
# get_events tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_events_required_params_in_query(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_events"](
            ctx, site_id="site-abc"
        )
    params = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
    assert params["context-type"] == "SITE"
    assert params["context-identifier"] == "site-abc"
    assert params["site-id"] == "site-abc"


@pytest.mark.asyncio
async def test_get_events_site_context_rejects_context_identifier(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    with pytest.raises(
        ToolError,
        match="context_identifier must not be provided when context_type=SITE",
    ):
        await tools["central_get_events"](
            ctx,
            site_id="s1",
            context_type="SITE",
            context_identifier="s1",
        )


@pytest.mark.asyncio
async def test_get_events_non_site_context_requires_context_identifier(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    with pytest.raises(ToolError, match="context_identifier is required"):
        await tools["central_get_events"](
            ctx,
            site_id="s1",
            context_type="ACCESS_POINT",
        )


@pytest.mark.asyncio
async def test_get_events_default_time_range(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()) as mock_ctw:
        await tools["central_get_events"](
            ctx, site_id="s1"
        )
    mock_ctw.assert_called_once_with("last_1h", None, None)


@pytest.mark.asyncio
async def test_get_events_custom_time_range(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()) as mock_ctw:
        await tools["central_get_events"](
            ctx,
            site_id="s1",
            time_range="last_7d",
        )
    mock_ctw.assert_called_once_with("last_7d", None, None)


@pytest.mark.asyncio
async def test_get_events_explicit_times_override_time_range(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    await tools["central_get_events"](
        ctx,
        site_id="s1",
        start_time="2026-03-21T00:00:00.000Z",
        end_time="2026-03-21T23:59:59.999Z",
    )
    params = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
    assert params["start-at"] == "2026-03-21T00:00:00.000Z"
    assert params["end-at"] == "2026-03-21T23:59:59.999Z"


@pytest.mark.asyncio
async def test_get_events_search_included(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_events"](
            ctx,
            site_id="s1",
            search="ap-1",
        )
    assert ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]["search"] == "ap-1"


@pytest.mark.asyncio
async def test_get_events_no_search_when_omitted(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_events"](
            ctx, site_id="s1"
        )
    assert "search" not in ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]


@pytest.mark.asyncio
async def test_get_events_event_id_filter_included(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_events"](
            ctx,
            site_id="s1",
            event_id="32",
        )
    params = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
    assert params["filter"] == "eventId eq '32'"


@pytest.mark.asyncio
async def test_get_events_category_and_source_type_filters_combined(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_events"](
            ctx,
            site_id="s1",
            category="System",
            source_type="Access Point",
        )
    params = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
    assert params["filter"] == "category eq 'System' and sourceType eq 'Access Point'"


@pytest.mark.asyncio
async def test_get_events_filters_support_comma_separated_values(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_events"](
            ctx,
            site_id="s1",
            event_id="32,33",
        )
    params = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
    assert params["filter"] == "eventId in ('32', '33')"


@pytest.mark.asyncio
async def test_get_events_no_filter_when_filter_args_omitted(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_events"](
            ctx, site_id="s1"
        )
    params = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
    assert "filter" not in params


@pytest.mark.asyncio
async def test_get_events_returns_event_objects(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response(events=[RAW_EVENT], total=1)
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events"](
            ctx, site_id="s1"
        )
    assert len(result.items) == 1
    assert isinstance(result.items[0], Event)
    assert result.items[0].event_id == "ev-type-1"


@pytest.mark.asyncio
async def test_get_events_default_limit(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_events"](
            ctx, site_id="s1"
        )
    assert ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]["limit"] == 50


@pytest.mark.asyncio
async def test_get_events_no_cursor_when_none(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_events"](
            ctx, site_id="s1"
        )
    assert "next" not in ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]


@pytest.mark.asyncio
async def test_get_events_cursor_forwarded(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.side_effect = [
        _make_events_response(next_cursor="5"),
        _make_events_response(),
    ]
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        first = await tools["central_get_events"](
            ctx, site_id="s1"
        )
        await tools["central_get_events"](
            ctx, site_id="s1", cursor=first.next_cursor
        )
    assert ctx.lifespan_context["conn"].command.call_args_list[1].kwargs[
        "api_params"
    ]["next"] == "5"


@pytest.mark.asyncio
async def test_get_events_returns_paginated_model(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response(
        events=[RAW_EVENT], total=200, next_cursor="3"
    )
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events"](
            ctx, site_id="s1"
        )
    assert isinstance(result, EventEnvelope)
    assert result.total == 200
    assert isinstance(result.next_cursor, str)
    assert result.next_cursor
    decoded = decode_cursor(
        result.next_cursor,
        expected_tool="central_get_events",
        expected_query_hash=hash_query(
            {
                "site_id": "s1",
                "context_type": "SITE",
                "context_identifier": None,
                "event_id": None,
                "category": None,
                "source_type": None,
                "search": None,
                "include": None,
                "time_range": "last_1h",
                "start_time": None,
                "end_time": None,
            }
        ),
    )
    assert decoded.position == {"upstream_next": "3"}
    assert isinstance(result.items[0], Event)


@pytest.mark.asyncio
async def test_get_events_cursor_round_trip_and_query_binding(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.side_effect = [
        _make_events_response(events=[RAW_EVENT], total=2, next_cursor="2"),
        _make_events_response(events=[RAW_EVENT], total=2),
    ]

    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        first = await tools["central_get_events"](
            ctx,
            site_id="s1",
            category="System",
            limit=1,
        )
        decoded = decode_cursor(
            first.next_cursor,
            expected_tool="central_get_events",
            expected_query_hash=hash_query(
                {
                    "site_id": "s1",
                    "context_type": "SITE",
                    "context_identifier": None,
                    "event_id": None,
                    "category": "System",
                    "source_type": None,
                    "search": None,
                    "include": None,
                    "time_range": "last_1h",
                    "start_time": None,
                    "end_time": None,
                }
            ),
        )
        assert decoded.page_size == 1
        assert decoded.position == {"upstream_next": "2"}

        second = await tools["central_get_events"](
            ctx,
            site_id="s1",
            category="System",
            cursor=first.next_cursor,
        )

    assert second.next_cursor is None
    assert ctx.lifespan_context["conn"].command.call_args_list[1].kwargs[
        "api_params"
    ] == {
        "context-type": "SITE",
        "context-identifier": "s1",
        "start-at": _fake_time_window()[0],
        "end-at": _fake_time_window()[1],
        "site-id": "s1",
        "limit": 1,
        "filter": "category eq 'System'",
        "next": "2",
    }


@pytest.mark.asyncio
async def test_get_events_rejects_cross_query_cursor_replay(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response(
        next_cursor="2"
    )

    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        first = await tools["central_get_events"](
            ctx,
            site_id="s1",
            category="System",
            limit=1,
        )
        with pytest.raises(ToolError) as exc_info:
            await tools["central_get_events"](
                ctx,
                site_id="s1",
                category="Clients",
                cursor=first.next_cursor,
            )

    error = json.loads(str(exc_info.value))
    assert error["code"] == "validation_error"
    assert "invalid or stale cursor" in error["message"]


@pytest.mark.asyncio
async def test_get_events_rejects_cursor_limit_conflict(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response(
        next_cursor="2"
    )

    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        first = await tools["central_get_events"](
            ctx,
            site_id="s1",
            limit=2,
        )
        with pytest.raises(ToolError) as exc_info:
            await tools["central_get_events"](
                ctx,
                site_id="s1",
                limit=3,
                cursor=first.next_cursor,
            )

    error = json.loads(str(exc_info.value))
    assert error["code"] == "validation_error"
    assert "limit conflicts with the cursor page_size" in error["message"]


@pytest.mark.asyncio
async def test_get_events_uses_events_key_from_response(tools):
    """Items must come from msg["events"], not msg["items"]."""
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {
        "code": 200, "msg": {"items": [RAW_EVENT], "total": 1, "next": None}
    }
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events"](
            ctx, site_id="s1"
        )
    assert result.items == []


@pytest.mark.asyncio
async def test_get_events_empty_returns_empty_paginated(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events"](
            ctx, site_id="s1"
        )
    assert isinstance(result, EventEnvelope)
    assert result.items == []
    assert result.next_cursor is None


# ---------------------------------------------------------------------------
# get_events mode=facets tests
# ---------------------------------------------------------------------------


def _make_count_response(total: int):
    # categories must sum to total since clean_event_filters computes total from them
    categories = [{"category": "System", "count": total}] if total else []
    return {
        "code": 200,
        "msg": {
            "total": total,
            "categories": categories,
            "eventNames": [],
            "sourceTypes": [],
        }
    }


@pytest.mark.asyncio
async def test_get_events_facets_returns_total(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_count_response(42)
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events"](
            ctx, site_id="s1", mode="facets"
        )
    assert isinstance(result, EventFacetsEnvelope)
    assert isinstance(result.items[0], EventFilters)
    assert result.items[0].total == 42
    assert result.total == 42


@pytest.mark.asyncio
async def test_get_events_facets_site_context_rejects_context_identifier(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_count_response(0)
    with pytest.raises(
        ToolError,
        match="context_identifier must not be provided when context_type=SITE",
    ):
        await tools["central_get_events"](
            ctx,
            site_id="s1",
            mode="facets",
            context_type="SITE",
            context_identifier="s1",
        )


@pytest.mark.asyncio
async def test_get_events_facets_non_site_context_requires_context_identifier(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_count_response(0)
    with pytest.raises(ToolError, match="context_identifier is required"):
        await tools["central_get_events"](
            ctx,
            site_id="s1",
            mode="facets",
            context_type="ACCESS_POINT",
        )


@pytest.mark.asyncio
async def test_get_events_facets_required_params(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_count_response(0)
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_events"](
            ctx,
            mode="facets",
            context_type="ACCESS_POINT",
            context_identifier="SN123",
            site_id="site-99",
        )
    params = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
    assert params["context-type"] == "ACCESS_POINT"
    assert params["context-identifier"] == "SN123"
    assert params["site-id"] == "site-99"


@pytest.mark.asyncio
async def test_get_events_facets_default_time_range(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_count_response(0)
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()) as mock_ctw:
        await tools["central_get_events"](
            ctx, site_id="s1", mode="facets"
        )
    mock_ctw.assert_called_once_with("last_1h", None, None)


@pytest.mark.asyncio
async def test_get_events_facets_explicit_times_override_time_range(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_count_response(0)
    await tools["central_get_events"](
        ctx,
        site_id="s1",
        mode="facets",
        start_time="2026-03-21T00:00:00.000Z",
        end_time="2026-03-21T23:59:59.999Z",
    )
    params = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
    assert params["start-at"] == "2026-03-21T00:00:00.000Z"
    assert params["end-at"] == "2026-03-21T23:59:59.999Z"


@pytest.mark.asyncio
async def test_get_events_facets_missing_total_returns_zero(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {"code": 200, "msg": {}}
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events"](
            ctx, site_id="s1", mode="facets"
        )
    assert result.total == 0
    assert result.items[0].total == 0


@pytest.mark.asyncio
async def test_get_events_facets_compact_returns_ranked_lists_with_event_ids(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {
        "code": 200,
        "msg": {
            "categories": [
                {"category": "System", "count": 5},
                {"category": "Clients", "count": 10},
                {"category": "Audit", "count": 10},
            ],
            "eventNames": [
                {"eventId": "11", "eventName": "Zulu Event", "count": 2},
                {"eventId": "12", "eventName": "Alpha Event", "count": 2},
                {"eventId": "13", "eventName": "Beta Event", "count": 3},
            ],
            "sourceTypes": [
                {"sourceType": "Switch", "count": 1},
                {"sourceType": "Access Point", "count": 7},
                {"sourceType": "Gateway", "count": 7},
            ],
        },
    }
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events"](
            ctx,
            site_id="s1",
            mode="facets",
            response_mode="compact",
        )
    assert isinstance(result, EventFacetsEnvelope)
    facets = result.items[0]
    assert isinstance(facets, CompactEventFilters)
    assert facets.total == 25
    assert [item.model_dump() for item in facets.event_names] == [
        {"event_id": "13", "event_name": "Beta Event"},
        {"event_id": "12", "event_name": "Alpha Event"},
        {"event_id": "11", "event_name": "Zulu Event"},
    ]
    assert facets.source_types == ["Access Point", "Gateway", "Switch"]
    assert facets.categories == ["Audit", "Clients", "System"]


@pytest.mark.asyncio
async def test_get_events_facets_compact_empty_response(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {"code": 200, "msg": {}}
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events"](
            ctx,
            site_id="s1",
            mode="facets",
            response_mode="compact",
        )
    assert isinstance(result, EventFacetsEnvelope)
    facets = result.items[0]
    assert isinstance(facets, CompactEventFilters)
    assert facets.total == 0
    assert facets.event_names == []
    assert facets.source_types == []
    assert facets.categories == []


@pytest.mark.asyncio
async def test_get_events_facets_invalid_response_mode_raises_tool_error(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_count_response(0)
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        with pytest.raises(ToolError, match="response_mode must be one of"):
            await tools["central_get_events"](
                ctx,
                site_id="s1",
                mode="facets",
                response_mode="invalid",  # type: ignore[arg-type]
            )


@pytest.mark.asyncio
async def test_get_events_returns_error_on_non_200(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {
        "code": 500, "msg": "Internal Server Error"
    }
    with (
        patch("tools.events._resolve_time_window", return_value=_fake_time_window()),
        pytest.raises(ToolError, match="Internal Server Error"),
    ):
        await tools["central_get_events"](ctx, site_id="s1")


@pytest.mark.asyncio
async def test_get_events_facets_returns_error_on_non_200(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {
        "code": 500, "msg": "Internal Server Error"
    }
    with (
        patch("tools.events._resolve_time_window", return_value=_fake_time_window()),
        pytest.raises(ToolError, match="Internal Server Error"),
    ):
        await tools["central_get_events"](ctx, site_id="s1", mode="facets")


@pytest.mark.asyncio
async def test_get_events_returns_error_on_404(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {
        "code": 404, "msg": "Not Found"
    }
    with (
        patch("tools.events._resolve_time_window", return_value=_fake_time_window()),
        pytest.raises(ToolError, match="Not Found"),
    ):
        await tools["central_get_events"](ctx, site_id="s1")


def test_events_count_tool_is_removed(tools):
    assert set(tools) == {"central_get_events"}


@pytest.mark.asyncio
async def test_get_events_fastmcp_contract_is_bounded_and_read_only():
    mcp = FastMCP("events-contract")
    mod.register(mcp)

    tool = await mcp.get_tool("central_get_events")
    limit_schema = tool.parameters["properties"]["limit"]
    integer_schema = next(
        schema for schema in limit_schema["anyOf"] if schema.get("type") == "integer"
    )

    assert integer_schema["minimum"] == 1
    assert integer_schema["maximum"] == MAX_PAGE_SIZE
    cursor_schema = tool.parameters["properties"]["cursor"]
    assert {schema["type"] for schema in cursor_schema["anyOf"]} == {
        "string",
        "null",
    }
    assert tool.annotations.readOnlyHint is True
    assert "EventEnvelope" in tool.output_schema["$defs"]
    assert "EventFacetsEnvelope" in tool.output_schema["$defs"]
    event_cursor_schema = tool.output_schema["$defs"]["EventEnvelope"]["properties"][
        "next_cursor"
    ]
    assert {schema["type"] for schema in event_cursor_schema["anyOf"]} == {
        "string",
        "null",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs,param",
    [
        ({"mode": "facets", "search": "AP"}, "search"),
        ({"mode": "facets", "limit": 10}, "limit"),
        ({"mode": "facets", "cursor": "2"}, "cursor"),
        ({"mode": "facets", "include": "attributes"}, "include"),
        ({"response_mode": "compact"}, "response_mode"),
    ],
)
async def test_get_events_rejects_mode_specific_params_before_connection(
    tools, kwargs, param
):
    ctx = make_ctx()
    with (
        patch(
            "tools.events.api_context",
            side_effect=AssertionError("connection opened"),
        ) as mock_context,
        pytest.raises(ToolError, match=param),
    ):
        await tools["central_get_events"](ctx, site_id="s1", **kwargs)
    mock_context.assert_not_called()


@pytest.mark.asyncio
async def test_get_events_include_attributes_enriches_each_record(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.side_effect = [
        _make_events_response(events=[RAW_EVENT], total=1),
        {
            "code": 200,
            "msg": {
                "eventExtraAttributes": [
                    {"label": "New EIRP", "value": "90 dBm"}
                ]
            },
        },
    ]

    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events"](
            ctx,
            site_id="s1",
            include="attributes",
        )

    assert result.items[0].attributes is not None
    assert result.items[0].attributes[0].label == "New EIRP"
    detail_call = ctx.lifespan_context["conn"].command.call_args_list[1]
    assert detail_call.kwargs["api_path"] == (
        "network-troubleshooting/v1/event-extra-attributes"
    )
    assert detail_call.kwargs["api_params"] == {
        "event-identifier": "ev-uid-1",
        "site-id": "s1",
        "time-at": "2026-03-21T00:00:00.000Z",
    }


# ---------------------------------------------------------------------------
# clean_event_filters
# ---------------------------------------------------------------------------

_RAW_EVENT_FILTERS = {
    "categories": [
        {"category": "Clients", "count": 30},
        {"category": "System", "count": 10},
    ],
    "eventNames": [
        {"eventId": "32", "eventName": "Client DHCP Acknowledge", "count": 25},
    ],
    "sourceTypes": [
        {"sourceType": "Wireless Client", "count": 30},
    ],
}


def test_clean_event_filters_returns_model():
    result = clean_event_filters(_RAW_EVENT_FILTERS)
    assert isinstance(result, EventFilters)


def test_clean_event_filters_total_is_sum_of_categories():
    result = clean_event_filters(_RAW_EVENT_FILTERS)
    assert result.total == 40  # 30 + 10


def test_clean_event_filters_categories():
    result = clean_event_filters(_RAW_EVENT_FILTERS)
    assert len(result.categories) == 2
    assert result.categories[0].category == "Clients"
    assert result.categories[0].count == 30


def test_clean_event_filters_event_names():
    result = clean_event_filters(_RAW_EVENT_FILTERS)
    assert len(result.event_names) == 1
    assert result.event_names[0].event_id == "32"
    assert result.event_names[0].event_name == "Client DHCP Acknowledge"
    assert result.event_names[0].count == 25


def test_clean_event_filters_source_types():
    result = clean_event_filters(_RAW_EVENT_FILTERS)
    assert len(result.source_types) == 1
    assert result.source_types[0].source_type == "Wireless Client"


def test_clean_event_filters_empty_response():
    result = clean_event_filters({})
    assert result.total == 0
    assert result.categories == []
    assert result.event_names == []
    assert result.source_types == []


def test_compact_event_filters_returns_ranked_full_lists():
    filters = EventFilters(
        total=20,
        event_names=[
            {"event_id": "1", "event_name": "Zulu Event", "count": 2},
            {"event_id": "2", "event_name": "Alpha Event", "count": 2},
            {"event_id": "3", "event_name": "Beta Event", "count": 4},
        ],
        source_types=[
            {"source_type": "Switch", "count": 1},
            {"source_type": "Gateway", "count": 3},
            {"source_type": "Access Point", "count": 3},
        ],
        categories=[
            {"category": "System", "count": 5},
            {"category": "Audit", "count": 5},
            {"category": "Clients", "count": 10},
        ],
    )
    result = compact_event_filters(filters)
    assert isinstance(result, CompactEventFilters)
    assert result.total == 20
    assert [item.model_dump() for item in result.event_names] == [
        {"event_id": "3", "event_name": "Beta Event"},
        {"event_id": "2", "event_name": "Alpha Event"},
        {"event_id": "1", "event_name": "Zulu Event"},
    ]
    assert result.source_types == ["Access Point", "Gateway", "Switch"]
    assert result.categories == ["Clients", "Audit", "System"]


@pytest.mark.asyncio
async def test_get_events_attributes_rejects_oversized_limit(tools):
    ctx = make_ctx()
    with pytest.raises(ToolError) as exc:
        await tools["central_get_events"](
            ctx, site_id="site-abc", include="attributes", limit=100
        )
    assert "include='attributes'" in str(exc.value)


@pytest.mark.asyncio
async def test_get_events_attributes_default_limit_capped(tools):
    from tools.events import EVENT_ATTRIBUTES_MAX

    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_events"](
            ctx, site_id="site-abc", include="attributes"
        )
    # first call is the records fetch; its limit must be the attributes cap, not EVENT_LIMIT
    first_call = ctx.lifespan_context["conn"].command.call_args_list[0]
    assert first_call.kwargs["api_params"]["limit"] == EVENT_ATTRIBUTES_MAX


@pytest.mark.asyncio
async def test_get_events_attributes_caps_overreturned_records_and_fanout(tools):
    from tools.events import EVENT_ATTRIBUTES_MAX

    ctx = make_ctx()
    raw_events = [
        {
            **RAW_EVENT,
            "eventIdentifier": f"ev-uid-{index}",
            "timeAt": f"2026-03-21T00:00:{index:02d}.000Z",
        }
        for index in range(EVENT_ATTRIBUTES_MAX + 5)
    ]

    def command_response(*, api_path, **kwargs):
        if api_path == "network-troubleshooting/v1/events":
            return _make_events_response(events=raw_events, total=len(raw_events))
        return {
            "code": 200,
            "msg": {"eventExtraAttributes": []},
        }

    ctx.lifespan_context["conn"].command.side_effect = command_response
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events"](
            ctx,
            site_id="site-abc",
            include="attributes",
            limit=EVENT_ATTRIBUTES_MAX,
        )

    attribute_calls = [
        call
        for call in ctx.lifespan_context["conn"].command.call_args_list
        if call.kwargs["api_path"]
        == "network-troubleshooting/v1/event-extra-attributes"
    ]
    assert len(attribute_calls) == EVENT_ATTRIBUTES_MAX
    assert len(result.items) == EVENT_ATTRIBUTES_MAX
    assert result.truncated is True
    assert result.meta.returned == EVENT_ATTRIBUTES_MAX
    assert result.meta.total_available == len(raw_events)
