from unittest.mock import patch

import pytest

import tools.wlans as mod
from models import WLAN, WLANThroughputSample
from tests.conftest import FakeMCP, make_ctx

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


def test_registers_wlan_tools(tools):
    assert "central_get_wlans" in tools
    assert "central_get_wlan_stats" in tools


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
async def test_get_wlans_no_filters(tools):
    ctx = make_ctx()
    with patch("tools.wlans.get_all_wlans", return_value=[RAW_WLAN, RAW_WLAN_2]) as mock_fn:
        result = await tools["central_get_wlans"](ctx)
    assert isinstance(result, list)
    assert len(result) == 2
    assert isinstance(result[0], WLAN)
    assert result[0].model_dump() == {
        "wlan_name": "Corp-WiFi",
        "security_level": "Enterprise",
        "security": "WPA3",
        "band": "5GHz",
        "status": "enabled",
        "vlan": "10",
    }
    call_kwargs = mock_fn.call_args.kwargs
    assert call_kwargs["site_id"] is None
    assert call_kwargs["sort"] is None


@pytest.mark.asyncio
async def test_get_wlans_site_id_passed_to_api(tools):
    ctx = make_ctx()
    with patch("tools.wlans.get_all_wlans", return_value=[RAW_WLAN]) as mock_fn:
        result = await tools["central_get_wlans"](ctx, site_id="site-abc")
    assert mock_fn.call_args.kwargs["site_id"] == "site-abc"
    assert len(result) == 1


@pytest.mark.asyncio
async def test_get_wlans_wlan_name_uses_direct_api_call(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {"code": 200, "msg": RAW_WLAN}
    with (
        patch("tools.wlans.get_all_wlans") as mock_get_all,
        patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)),
    ):
        result = await tools["central_get_wlans"](ctx, wlan_name="Corp-WiFi")
    assert len(result) == 1
    assert result[0].wlan_name == "Corp-WiFi"
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
    assert result == "No WLANs found matching the specified criteria."


@pytest.mark.asyncio
async def test_get_wlans_wlan_name_passes_site_id_to_direct_api(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {"code": 200, "msg": RAW_WLAN}
    with patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
        result = await tools["central_get_wlans"](
            ctx, wlan_name="Corp-WiFi", site_id="site-abc"
        )
    assert len(result) == 1
    assert (
        ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]
        == {"site_id": "site-abc"}
    )


@pytest.mark.asyncio
async def test_get_wlans_empty_returns_string(tools):
    ctx = make_ctx()
    with patch("tools.wlans.get_all_wlans", return_value=[]):
        result = await tools["central_get_wlans"](ctx)
    assert result == "No WLANs found matching the specified criteria."


@pytest.mark.asyncio
async def test_get_wlans_api_error_returns_formatted_error(tools):
    ctx = make_ctx()
    with patch("tools.wlans.get_all_wlans", side_effect=Exception("network error")):
        result = await tools["central_get_wlans"](ctx)
    assert result == "Error fetching WLANs: network error"


@pytest.mark.asyncio
async def test_get_wlans_sort_passed_to_api(tools):
    ctx = make_ctx()
    with patch("tools.wlans.get_all_wlans", return_value=[]) as mock_fn:
        await tools["central_get_wlans"](ctx, sort="wlanName asc")
    assert mock_fn.call_args.kwargs["sort"] == "wlanName asc"


@pytest.mark.asyncio
async def test_get_wlans_wlan_name_non_200_returns_formatted_error(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {
        "code": 404,
        "msg": "not found",
    }
    with patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
        result = await tools["central_get_wlans"](ctx, wlan_name="Bad-WLAN")
    assert result == "Error fetching WLANs: API returned 404: not found"


# --- central_get_wlan_stats ---


@pytest.mark.asyncio
async def test_get_wlan_stats_success(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {"code": 200, "msg": RAW_STATS}
    with patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
        result = await tools["central_get_wlan_stats"](ctx, wlan_name="Corp-WiFi")
    assert all(isinstance(sample, WLANThroughputSample) for sample in result)
    assert [sample.model_dump() for sample in result] == CLEANED_STATS


@pytest.mark.asyncio
async def test_get_wlan_stats_uses_default_time_range(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {"code": 200, "msg": RAW_STATS}
    with patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
        await tools["central_get_wlan_stats"](ctx, wlan_name="Corp-WiFi")
    call_kwargs = ctx.lifespan_context["conn"].command.call_args.kwargs
    assert call_kwargs["api_path"] == "network-monitoring/v1/wlans/Corp-WiFi/throughput-trends"
    assert "timestamp gt" in call_kwargs["api_params"]["filter"]
    assert "timestamp lt" in call_kwargs["api_params"]["filter"]


@pytest.mark.asyncio
async def test_get_wlan_stats_explicit_time_window(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {"code": 200, "msg": RAW_STATS}
    with patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
        await tools["central_get_wlan_stats"](
            ctx,
            wlan_name="Corp-WiFi",
            start_time="2026-04-07T00:00:00.000Z",
            end_time="2026-04-07T23:59:59.999Z",
        )
    filter_str = ctx.lifespan_context["conn"].command.call_args.kwargs["api_params"]["filter"]
    assert "2026-04-07T00:00:00.000Z" in filter_str
    assert "2026-04-07T23:59:59.999Z" in filter_str


@pytest.mark.asyncio
async def test_get_wlan_stats_non_200_returns_error(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {
        "code": 404,
        "msg": "not found",
    }
    with patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
        result = await tools["central_get_wlan_stats"](ctx, wlan_name="Bad-WLAN")
    assert "Error fetching WLAN statistics" in result


@pytest.mark.asyncio
async def test_get_wlan_stats_empty_msg_returns_string(tools):
    ctx = make_ctx()
    ctx.lifespan_context["conn"].command.return_value = {"code": 200, "msg": None}
    with patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
        result = await tools["central_get_wlan_stats"](ctx, wlan_name="Corp-WiFi")
    assert result == "No throughput data found for WLAN 'Corp-WiFi'."


@pytest.mark.asyncio
async def test_get_wlan_stats_all_null_samples_returns_string(tools):
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
    ctx.lifespan_context["conn"].command.return_value = {"code": 200, "msg": null_stats}
    with patch("tools.wlans.asyncio.to_thread", side_effect=lambda fn, **kw: fn(**kw)):
        result = await tools["central_get_wlan_stats"](ctx, wlan_name="__nonexistent__")
    assert result == "No throughput data found for WLAN '__nonexistent__'."


@pytest.mark.asyncio
async def test_get_wlan_stats_exception_returns_error(tools):
    ctx = make_ctx()
    with patch(
        "tools.wlans.asyncio.to_thread",
        side_effect=Exception("connection refused"),
    ):
        result = await tools["central_get_wlan_stats"](ctx, wlan_name="Corp-WiFi")
    assert result == "Error fetching WLAN statistics: connection refused"
