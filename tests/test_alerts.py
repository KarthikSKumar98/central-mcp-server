from unittest.mock import patch

import pytest

import tools.alerts as mod
from models import Alert, PaginatedAlerts
from tests.conftest import FakeMCP, make_ctx
from utils.alerts import clean_alert_data


@pytest.fixture
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


def _make_alert_response(items=None, total=0, next_cursor=None):
    return {"msg": {"items": items or [], "total": total, "next": next_cursor}}


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
    with patch(
        "tools.alerts.retry_central_command", return_value=_make_alert_response()
    ) as mock_cmd:
        await tools["central_get_alerts"](ctx, site_id="site-1")
    params = mock_cmd.call_args.kwargs["api_params"]
    assert "status eq 'Active'" in params["filter"]
    assert "siteId eq 'site-1'" in params["filter"]


@pytest.mark.asyncio
async def test_get_alerts_cleared_status(tools):
    ctx = make_ctx()
    with patch(
        "tools.alerts.retry_central_command", return_value=_make_alert_response()
    ) as mock_cmd:
        await tools["central_get_alerts"](ctx, site_id="site-1", status="Cleared")
    assert "status eq 'Cleared'" in mock_cmd.call_args.kwargs["api_params"]["filter"]


@pytest.mark.asyncio
async def test_get_alerts_with_device_type(tools):
    ctx = make_ctx()
    with patch(
        "tools.alerts.retry_central_command", return_value=_make_alert_response()
    ) as mock_cmd:
        await tools["central_get_alerts"](ctx, site_id="site-1", device_type="Switch")
    assert "deviceType eq 'Switch'" in mock_cmd.call_args.kwargs["api_params"]["filter"]


@pytest.mark.asyncio
async def test_get_alerts_with_category(tools):
    ctx = make_ctx()
    with patch(
        "tools.alerts.retry_central_command", return_value=_make_alert_response()
    ) as mock_cmd:
        await tools["central_get_alerts"](ctx, site_id="site-1", category="Security")
    assert "category eq 'Security'" in mock_cmd.call_args.kwargs["api_params"]["filter"]


@pytest.mark.asyncio
async def test_get_alerts_default_sort(tools):
    ctx = make_ctx()
    with patch(
        "tools.alerts.retry_central_command", return_value=_make_alert_response()
    ) as mock_cmd:
        await tools["central_get_alerts"](ctx, site_id="site-1")
    assert mock_cmd.call_args.kwargs["api_params"]["sort"] == "severity desc"


@pytest.mark.asyncio
async def test_get_alerts_custom_sort(tools):
    ctx = make_ctx()
    with patch(
        "tools.alerts.retry_central_command", return_value=_make_alert_response()
    ) as mock_cmd:
        await tools["central_get_alerts"](ctx, site_id="site-1", sort="createdAt asc")
    assert mock_cmd.call_args.kwargs["api_params"]["sort"] == "createdAt asc"


@pytest.mark.asyncio
async def test_get_alerts_all_filters_combined(tools):
    ctx = make_ctx()
    with patch(
        "tools.alerts.retry_central_command", return_value=_make_alert_response()
    ) as mock_cmd:
        await tools["central_get_alerts"](
            ctx,
            site_id="site-1",
            status="Active",
            device_type="Gateway",
            category="WAN",
        )
    filter_str = mock_cmd.call_args.kwargs["api_params"]["filter"]
    assert "status eq 'Active'" in filter_str
    assert "deviceType eq 'Gateway'" in filter_str
    assert "category eq 'WAN'" in filter_str
    assert "siteId eq 'site-1'" in filter_str


@pytest.mark.asyncio
async def test_get_alerts_default_limit(tools):
    ctx = make_ctx()
    with patch(
        "tools.alerts.retry_central_command", return_value=_make_alert_response()
    ) as mock_cmd:
        await tools["central_get_alerts"](ctx, site_id="site-1")
    assert mock_cmd.call_args.kwargs["api_params"]["limit"] == 50


@pytest.mark.asyncio
async def test_get_alerts_custom_limit(tools):
    ctx = make_ctx()
    with patch(
        "tools.alerts.retry_central_command", return_value=_make_alert_response()
    ) as mock_cmd:
        await tools["central_get_alerts"](ctx, site_id="site-1", limit=25)
    assert mock_cmd.call_args.kwargs["api_params"]["limit"] == 25


@pytest.mark.asyncio
async def test_get_alerts_no_cursor_when_none(tools):
    ctx = make_ctx()
    with patch(
        "tools.alerts.retry_central_command", return_value=_make_alert_response()
    ) as mock_cmd:
        await tools["central_get_alerts"](ctx, site_id="site-1")
    assert "next" not in mock_cmd.call_args.kwargs["api_params"]


@pytest.mark.asyncio
async def test_get_alerts_cursor_forwarded(tools):
    ctx = make_ctx()
    with patch(
        "tools.alerts.retry_central_command", return_value=_make_alert_response()
    ) as mock_cmd:
        await tools["central_get_alerts"](ctx, site_id="site-1", cursor=42)
    assert mock_cmd.call_args.kwargs["api_params"]["next"] == 42


@pytest.mark.asyncio
async def test_get_alerts_returns_paginated_model(tools):
    ctx = make_ctx()
    with patch(
        "tools.alerts.retry_central_command",
        return_value=_make_alert_response(items=[RAW_ALERT], total=100, next_cursor=2),
    ):
        result = await tools["central_get_alerts"](ctx, site_id="site-1")
    assert isinstance(result, PaginatedAlerts)
    assert result.total == 100
    assert result.next_cursor == 2
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_get_alerts_next_cursor_none_at_last_page(tools):
    ctx = make_ctx()
    with patch(
        "tools.alerts.retry_central_command",
        return_value=_make_alert_response(items=[RAW_ALERT], total=1, next_cursor=None),
    ):
        result = await tools["central_get_alerts"](ctx, site_id="site-1")
    assert isinstance(result, PaginatedAlerts)
    assert result.next_cursor is None


@pytest.mark.asyncio
async def test_get_alerts_empty_returns_string(tools):
    ctx = make_ctx()
    with patch(
        "tools.alerts.retry_central_command", return_value=_make_alert_response()
    ):
        result = await tools["central_get_alerts"](ctx, site_id="site-1")
    assert result == "No alerts found matching criteria"


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
