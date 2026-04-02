from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import tools.events as mod
from models import CompactEventFilters, Event, EventFilters, PaginatedEvents
from tests.conftest import FakeMCP, make_ctx
from utils.events import clean_event_filters, compact_event_filters


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
    result = await tools["central_get_events"](
        ctx,
        site_id="s1",
        context_type="SITE",
        context_identifier="s1",
    )
    assert isinstance(result, str)
    assert "context_identifier must not be provided when context_type=SITE" in result


@pytest.mark.asyncio
async def test_get_events_non_site_context_requires_context_identifier(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    result = await tools["central_get_events"](
        ctx,
        site_id="s1",
        context_type="ACCESS_POINT",
    )
    assert isinstance(result, str)
    assert (
        "context_identifier is required when context_type is ACCESS_POINT/SWITCH/GATEWAY/WIRELESS_CLIENT/WIRED_CLIENT/BRIDGE"
        in result
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
    ctx.lifespan_context["conn"].command.return_value = _make_events_response()
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_events"](
            ctx, site_id="s1", cursor=5
        )
    assert ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]["next"] == 5


@pytest.mark.asyncio
async def test_get_events_returns_paginated_model(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_events_response(
        events=[RAW_EVENT], total=200, next_cursor=3
    )
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events"](
            ctx, site_id="s1"
        )
    assert isinstance(result, PaginatedEvents)
    assert result.total == 200
    assert result.next_cursor == 3
    assert isinstance(result.items[0], Event)


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
    assert isinstance(result, PaginatedEvents)
    assert result.items == []
    assert result.next_cursor is None


# ---------------------------------------------------------------------------
# get_events_count tests
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
async def test_get_events_count_returns_total(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_count_response(42)
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events_count"](
            ctx, site_id="s1"
        )
    assert isinstance(result, EventFilters)
    assert result.total == 42


@pytest.mark.asyncio
async def test_get_events_count_site_context_rejects_context_identifier(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_count_response(0)
    result = await tools["central_get_events_count"](
        ctx,
        site_id="s1",
        context_type="SITE",
        context_identifier="s1",
    )
    assert isinstance(result, str)
    assert "context_identifier must not be provided when context_type=SITE" in result


@pytest.mark.asyncio
async def test_get_events_count_non_site_context_requires_context_identifier(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_count_response(0)
    result = await tools["central_get_events_count"](
        ctx,
        site_id="s1",
        context_type="ACCESS_POINT",
    )
    assert isinstance(result, str)
    assert (
        "context_identifier is required when context_type is ACCESS_POINT/SWITCH/GATEWAY/WIRELESS_CLIENT/WIRED_CLIENT/BRIDGE"
        in result
    )


@pytest.mark.asyncio
async def test_get_events_count_required_params(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_count_response(0)
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_events_count"](
            ctx,
            context_type="ACCESS_POINT",
            context_identifier="SN123",
            site_id="site-99",
        )
    params = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
    assert params["context-type"] == "ACCESS_POINT"
    assert params["context-identifier"] == "SN123"
    assert params["site-id"] == "site-99"


@pytest.mark.asyncio
async def test_get_events_count_default_time_range(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_count_response(0)
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()) as mock_ctw:
        await tools["central_get_events_count"](
            ctx, site_id="s1"
        )
    mock_ctw.assert_called_once_with("last_1h", None, None)


@pytest.mark.asyncio
async def test_get_events_count_explicit_times_override_time_range(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_count_response(0)
    await tools["central_get_events_count"](
        ctx,
        site_id="s1",
        start_time="2026-03-21T00:00:00.000Z",
        end_time="2026-03-21T23:59:59.999Z",
    )
    params = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
    assert params["start-at"] == "2026-03-21T00:00:00.000Z"
    assert params["end-at"] == "2026-03-21T23:59:59.999Z"


@pytest.mark.asyncio
async def test_get_events_count_missing_total_returns_zero(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {"code": 200, "msg": {}}
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events_count"](
            ctx, site_id="s1"
        )
    assert result.total == 0


@pytest.mark.asyncio
async def test_get_events_count_compact_returns_ranked_lists_with_event_ids(tools):
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
        result = await tools["central_get_events_count"](
            ctx,
            site_id="s1",
            response_mode="compact",
        )
    assert isinstance(result, CompactEventFilters)
    assert result.total == 25
    assert [item.model_dump() for item in result.event_names] == [
        {"event_id": "13", "event_name": "Beta Event"},
        {"event_id": "12", "event_name": "Alpha Event"},
        {"event_id": "11", "event_name": "Zulu Event"},
    ]
    assert result.source_types == ["Access Point", "Gateway", "Switch"]
    assert result.categories == ["Audit", "Clients", "System"]


@pytest.mark.asyncio
async def test_get_events_count_compact_empty_response(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {"code": 200, "msg": {}}
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events_count"](
            ctx,
            site_id="s1",
            response_mode="compact",
        )
    assert isinstance(result, CompactEventFilters)
    assert result.total == 0
    assert result.event_names == []
    assert result.source_types == []
    assert result.categories == []


@pytest.mark.asyncio
async def test_get_events_count_invalid_response_mode_returns_error(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_count_response(0)
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events_count"](
            ctx,
            site_id="s1",
            response_mode="invalid",  # type: ignore[arg-type]
        )
    assert isinstance(result, str)
    assert "response_mode must be one of: full, compact" in result


@pytest.mark.asyncio
async def test_get_events_returns_error_on_non_200(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {
        "code": 500, "msg": "Internal Server Error"
    }
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events"](
            ctx, site_id="s1"
        )
    assert isinstance(result, str)
    assert "fetching events" in result


@pytest.mark.asyncio
async def test_get_events_count_returns_error_on_non_200(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {
        "code": 500, "msg": "Internal Server Error"
    }
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events_count"](
            ctx, site_id="s1"
        )
    assert isinstance(result, str)
    assert "fetching event filters" in result


@pytest.mark.asyncio
async def test_get_events_returns_error_on_404(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {
        "code": 404, "msg": "Not Found"
    }
    with patch("tools.events._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_events"](
            ctx, site_id="s1"
        )
    assert isinstance(result, str)
    assert "fetching events" in result


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
