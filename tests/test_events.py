from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import tools.events as mod
from models import Event, EventFilters, PaginatedEvents
from tests.conftest import FakeMCP, make_ctx
from utils.events import clean_event_filters


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
    return {"msg": {"events": events or [], "total": total, "next": next_cursor}}


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
    with (
        patch(
            "tools.events.retry_central_command", return_value=_make_events_response()
        ) as mock_cmd,
        patch("tools.events.compute_time_window", return_value=_fake_time_window()),
    ):
        await tools["central_get_events"](
            ctx, context_type="SITE", context_identifier="site-abc", site_id="site-abc"
        )
    params = mock_cmd.call_args.kwargs["api_params"]
    assert params["context-type"] == "SITE"
    assert params["context-identifier"] == "site-abc"
    assert params["site-id"] == "site-abc"


@pytest.mark.asyncio
async def test_get_events_default_time_range(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.events.retry_central_command", return_value=_make_events_response()
        ),
        patch(
            "tools.events.compute_time_window", return_value=_fake_time_window()
        ) as mock_ctw,
    ):
        await tools["central_get_events"](
            ctx, context_type="SITE", context_identifier="s1", site_id="s1"
        )
    mock_ctw.assert_called_once_with("last_1h")


@pytest.mark.asyncio
async def test_get_events_custom_time_range(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.events.retry_central_command", return_value=_make_events_response()
        ),
        patch(
            "tools.events.compute_time_window", return_value=_fake_time_window()
        ) as mock_ctw,
    ):
        await tools["central_get_events"](
            ctx,
            context_type="SITE",
            context_identifier="s1",
            site_id="s1",
            time_range="last_7d",
        )
    mock_ctw.assert_called_once_with("last_7d")


@pytest.mark.asyncio
async def test_get_events_explicit_times_override_time_range(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.events.retry_central_command", return_value=_make_events_response()
        ) as mock_cmd,
        patch("tools.events.compute_time_window") as mock_ctw,
    ):
        await tools["central_get_events"](
            ctx,
            context_type="SITE",
            context_identifier="s1",
            site_id="s1",
            start_time="2026-03-21T00:00:00.000Z",
            end_time="2026-03-21T23:59:59.999Z",
        )
    mock_ctw.assert_not_called()
    params = mock_cmd.call_args.kwargs["api_params"]
    assert params["start-at"] == "2026-03-21T00:00:00.000Z"
    assert params["end-at"] == "2026-03-21T23:59:59.999Z"


@pytest.mark.asyncio
async def test_get_events_search_included(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.events.retry_central_command", return_value=_make_events_response()
        ) as mock_cmd,
        patch("tools.events.compute_time_window", return_value=_fake_time_window()),
    ):
        await tools["central_get_events"](
            ctx,
            context_type="SITE",
            context_identifier="s1",
            site_id="s1",
            search="ap-1",
        )
    assert mock_cmd.call_args.kwargs["api_params"]["search"] == "ap-1"


@pytest.mark.asyncio
async def test_get_events_no_search_when_omitted(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.events.retry_central_command", return_value=_make_events_response()
        ) as mock_cmd,
        patch("tools.events.compute_time_window", return_value=_fake_time_window()),
    ):
        await tools["central_get_events"](
            ctx, context_type="SITE", context_identifier="s1", site_id="s1"
        )
    assert "search" not in mock_cmd.call_args.kwargs["api_params"]


@pytest.mark.asyncio
async def test_get_events_returns_event_objects(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.events.retry_central_command",
            return_value=_make_events_response(events=[RAW_EVENT], total=1),
        ),
        patch("tools.events.compute_time_window", return_value=_fake_time_window()),
    ):
        result = await tools["central_get_events"](
            ctx, context_type="SITE", context_identifier="s1", site_id="s1"
        )
    assert len(result.items) == 1
    assert isinstance(result.items[0], Event)
    assert result.items[0].eventId == "ev-type-1"


@pytest.mark.asyncio
async def test_get_events_default_limit(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.events.retry_central_command", return_value=_make_events_response()
        ) as mock_cmd,
        patch("tools.events.compute_time_window", return_value=_fake_time_window()),
    ):
        await tools["central_get_events"](
            ctx, context_type="SITE", context_identifier="s1", site_id="s1"
        )
    assert mock_cmd.call_args.kwargs["api_params"]["limit"] == 50


@pytest.mark.asyncio
async def test_get_events_no_cursor_when_none(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.events.retry_central_command", return_value=_make_events_response()
        ) as mock_cmd,
        patch("tools.events.compute_time_window", return_value=_fake_time_window()),
    ):
        await tools["central_get_events"](
            ctx, context_type="SITE", context_identifier="s1", site_id="s1"
        )
    assert "next" not in mock_cmd.call_args.kwargs["api_params"]


@pytest.mark.asyncio
async def test_get_events_cursor_forwarded(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.events.retry_central_command", return_value=_make_events_response()
        ) as mock_cmd,
        patch("tools.events.compute_time_window", return_value=_fake_time_window()),
    ):
        await tools["central_get_events"](
            ctx, context_type="SITE", context_identifier="s1", site_id="s1", cursor=5
        )
    assert mock_cmd.call_args.kwargs["api_params"]["next"] == 5


@pytest.mark.asyncio
async def test_get_events_returns_paginated_model(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.events.retry_central_command",
            return_value=_make_events_response(
                events=[RAW_EVENT], total=200, next_cursor=3
            ),
        ),
        patch("tools.events.compute_time_window", return_value=_fake_time_window()),
    ):
        result = await tools["central_get_events"](
            ctx, context_type="SITE", context_identifier="s1", site_id="s1"
        )
    assert isinstance(result, PaginatedEvents)
    assert result.total == 200
    assert result.next_cursor == 3
    assert isinstance(result.items[0], Event)


@pytest.mark.asyncio
async def test_get_events_uses_events_key_from_response(tools):
    """Items must come from msg["events"], not msg["items"]."""
    ctx = make_ctx()
    wrong_key_response = {"msg": {"items": [RAW_EVENT], "total": 1, "next": None}}
    with (
        patch("tools.events.retry_central_command", return_value=wrong_key_response),
        patch("tools.events.compute_time_window", return_value=_fake_time_window()),
    ):
        result = await tools["central_get_events"](
            ctx, context_type="SITE", context_identifier="s1", site_id="s1"
        )
    assert result.items == []


@pytest.mark.asyncio
async def test_get_events_empty_returns_empty_paginated(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.events.retry_central_command", return_value=_make_events_response()
        ),
        patch("tools.events.compute_time_window", return_value=_fake_time_window()),
    ):
        result = await tools["central_get_events"](
            ctx, context_type="SITE", context_identifier="s1", site_id="s1"
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
    with (
        patch(
            "tools.events.retry_central_command", return_value=_make_count_response(42)
        ),
        patch("tools.events.compute_time_window", return_value=_fake_time_window()),
    ):
        result = await tools["central_get_events_count"](
            ctx, context_type="SITE", context_identifier="s1", site_id="s1"
        )
    assert result.total == 42


@pytest.mark.asyncio
async def test_get_events_count_required_params(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.events.retry_central_command", return_value=_make_count_response(0)
        ) as mock_cmd,
        patch("tools.events.compute_time_window", return_value=_fake_time_window()),
    ):
        await tools["central_get_events_count"](
            ctx,
            context_type="ACCESS_POINT",
            context_identifier="SN123",
            site_id="site-99",
        )
    params = mock_cmd.call_args.kwargs["api_params"]
    assert params["context-type"] == "ACCESS_POINT"
    assert params["context-identifier"] == "SN123"
    assert params["site-id"] == "site-99"


@pytest.mark.asyncio
async def test_get_events_count_default_time_range(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.events.retry_central_command", return_value=_make_count_response(0)
        ),
        patch(
            "tools.events.compute_time_window", return_value=_fake_time_window()
        ) as mock_ctw,
    ):
        await tools["central_get_events_count"](
            ctx, context_type="SITE", context_identifier="s1", site_id="s1"
        )
    mock_ctw.assert_called_once_with("last_1h")


@pytest.mark.asyncio
async def test_get_events_count_explicit_times_override_time_range(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.events.retry_central_command", return_value=_make_count_response(0)
        ) as mock_cmd,
        patch("tools.events.compute_time_window") as mock_ctw,
    ):
        await tools["central_get_events_count"](
            ctx,
            context_type="SITE",
            context_identifier="s1",
            site_id="s1",
            start_time="2026-03-21T00:00:00.000Z",
            end_time="2026-03-21T23:59:59.999Z",
        )
    mock_ctw.assert_not_called()
    params = mock_cmd.call_args.kwargs["api_params"]
    assert params["start-at"] == "2026-03-21T00:00:00.000Z"
    assert params["end-at"] == "2026-03-21T23:59:59.999Z"


@pytest.mark.asyncio
async def test_get_events_count_missing_total_returns_zero(tools):
    ctx = make_ctx()
    with (
        patch("tools.events.retry_central_command", return_value={"msg": {}}),
        patch("tools.events.compute_time_window", return_value=_fake_time_window()),
    ):
        result = await tools["central_get_events_count"](
            ctx, context_type="SITE", context_identifier="s1", site_id="s1"
        )
    assert result.total == 0


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
