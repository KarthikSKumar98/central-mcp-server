from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import tools.applications as mod
from models import App, PaginatedApps
from tests.conftest import FakeMCP, make_ctx


@pytest.fixture
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


def _fake_time_window():
    start = datetime(2026, 3, 21, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 3, 21, 1, 0, 0, tzinfo=timezone.utc)
    return start, end


def _make_apps_response(items=None, total=0):
    return {"code": 200, "msg": {"items": items or [], "total": total}}


RAW_APP = {
    "type": "/network-monitoring/applications",
    "id": "244",
    "name": "Facebook",
    "categories": ["Social Networking", "Social Networking Web"],
    "experience": {
        "groups": [
            {"count": 0, "name": "Poor"},
            {"count": 0, "name": "Fair"},
            {"count": 4, "name": "Good"},
        ]
    },
    "risk": "LOW",
    "txBytes": 4615170,
    "rxBytes": 82949479,
    "state": "ALLOWED",
    "lastUsedTime": "1725574810044",
    "tlsVersion": "TLS 1.2",
    "certificateExpiryDate": "",
    "applicationHostType": "Public",
    "destLocation": [{"countryName": "United States"}],
}


@pytest.mark.asyncio
async def test_get_apps_happy_path(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_apps_response(
        items=[RAW_APP], total=1
    )
    with patch("tools.applications._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_apps"](ctx, site_id="site-xyz")
    assert isinstance(result, PaginatedApps)
    assert result.total == 1
    assert len(result.items) == 1
    assert isinstance(result.items[0], App)
    assert result.offset == 0
    assert result.limit == 100


@pytest.mark.asyncio
async def test_get_apps_required_params_in_query(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_apps_response()
    with patch(
        "tools.applications._resolve_time_window",
        return_value=("2026-03-21T00:00:00Z", "2026-03-21T01:00:00Z"),
    ):
        await tools["central_get_apps"](ctx, site_id="site-xyz")
    params = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
    assert params["site-id"] == "site-xyz"
    assert params["start-at"] == "2026-03-21T00:00:00Z"
    assert params["end-at"] == "2026-03-21T01:00:00Z"
    assert params["limit"] == 100
    assert params["offset"] == 0


@pytest.mark.asyncio
async def test_get_apps_custom_limit_and_offset(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_apps_response()
    with patch("tools.applications._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_apps"](ctx, site_id="site-xyz", limit=10, offset=20)
    params = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
    assert params["limit"] == 10
    assert params["offset"] == 20


@pytest.mark.asyncio
async def test_get_apps_filter_combined(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_apps_response()
    with patch("tools.applications._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_apps"](
            ctx,
            site_id="site-xyz",
            client_id="client-abc",
            risk="High",
            state="blocked",
        )
    params = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
    assert "filter" in params
    f = params["filter"]
    assert "clientId eq 'client-abc'" in f
    assert "RISK eq 'High'" in f
    assert "STATE eq 'blocked'" in f


@pytest.mark.asyncio
async def test_get_apps_no_filter_when_none(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_apps_response()
    with patch("tools.applications._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_apps"](ctx, site_id="site-xyz")
    params = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
    assert "filter" not in params


@pytest.mark.asyncio
async def test_get_apps_non_200_returns_error(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {
        "code": 400,
        "msg": "Bad Request",
    }
    with patch("tools.applications._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_apps"](ctx, site_id="site-xyz")
    assert isinstance(result, str)
    assert "fetching apps" in result


@pytest.mark.asyncio
async def test_get_apps_empty_items(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_apps_response(
        items=[], total=0
    )
    with patch("tools.applications._resolve_time_window", return_value=_fake_time_window()):
        result = await tools["central_get_apps"](ctx, site_id="site-xyz")
    assert isinstance(result, PaginatedApps)
    assert result.items == []
    assert result.total == 0


@pytest.mark.asyncio
async def test_get_apps_api_path(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_apps_response()
    with patch("tools.applications._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_apps"](ctx, site_id="site-xyz")
    call_kwargs = ctx.lifespan_context["conn"].command.call_args.kwargs
    assert call_kwargs["api_method"] == "GET"
    assert call_kwargs["api_path"] == "network-monitoring/v1/apps"


@pytest.mark.asyncio
async def test_get_apps_app_category_filter(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_apps_response()
    with patch("tools.applications._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_apps"](
            ctx, site_id="site-xyz", app_category="Encrypted"
        )
    params = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
    assert params["filter"] == "APP_CAT eq 'Encrypted'"


@pytest.mark.asyncio
async def test_get_apps_host_type_and_country(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = _make_apps_response()
    with patch("tools.applications._resolve_time_window", return_value=_fake_time_window()):
        await tools["central_get_apps"](
            ctx, site_id="site-xyz", host_type="Public", country="IN"
        )
    params = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
    assert "APPLICATION_HOST_TYPE eq 'Public'" in params["filter"]
    assert "COUNTRY eq 'IN'" in params["filter"]
