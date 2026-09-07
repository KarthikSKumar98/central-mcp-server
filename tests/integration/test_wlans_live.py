import datetime

import pytest

import tools.wlans as mod
from models import WLAN, WlanEnvelope
from tests.conftest import FakeMCP

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


async def test_get_wlans_returns_results(tools, live_ctx):
    result = await tools["central_get_wlans"](live_ctx)
    assert isinstance(result, WlanEnvelope)
    assert all(isinstance(w, WLAN) for w in result.items)


async def test_get_wlans_all_have_wlan_name(tools, live_ctx):
    result = await tools["central_get_wlans"](live_ctx)
    if not result.items:
        pytest.skip("No WLANs available")
    assert all(w.wlan_name is not None for w in result.items)


async def test_get_wlans_with_site_id_filter(tools, live_ctx):
    import tools.sites as sites_mod
    from tests.conftest import FakeMCP as FakeMCPLocal

    fake = FakeMCPLocal()
    sites_mod.register(fake)
    site_tools = fake._tools

    summary = await site_tools["central_get_sites"](live_ctx, view="summary")
    if not summary.items:
        pytest.skip("No sites available")

    first_site_id = summary.items[0].site_id
    result = await tools["central_get_wlans"](live_ctx, site_id=first_site_id)
    assert isinstance(result, WlanEnvelope)
    assert all(isinstance(w, WLAN) for w in result.items)


async def test_get_wlans_wlan_name_filter_client_side(tools, live_ctx):
    all_wlans = await tools["central_get_wlans"](live_ctx)
    if not all_wlans.items:
        pytest.skip("No WLANs available")

    target_name = all_wlans.items[0].wlan_name
    result = await tools["central_get_wlans"](live_ctx, wlan_name=target_name)
    assert all(w.wlan_name == target_name for w in result.items)


async def test_get_wlans_unknown_name_returns_string(tools, live_ctx):
    result = await tools["central_get_wlans"](
        live_ctx, wlan_name="__nonexistent_wlan__"
    )
    assert result.items == []


async def test_get_wlan_stats_for_known_wlan(tools, live_ctx):
    all_wlans = await tools["central_get_wlans"](live_ctx)
    if not all_wlans.items:
        pytest.skip("No WLANs available to test stats")

    wlan_name = all_wlans.items[0].wlan_name
    result = await tools["central_get_wlans"](
        live_ctx,
        wlan_name=wlan_name,
        include=["throughput"],
    )
    assert isinstance(result, WlanEnvelope)
    assert result.items[0].throughput is not None
    assert all(sample.timestamp for sample in result.items[0].throughput)


async def test_get_wlan_stats_explicit_time_window(tools, live_ctx):
    all_wlans = await tools["central_get_wlans"](live_ctx)
    if not all_wlans.items:
        pytest.skip("No WLANs available to test stats")

    wlan_name = all_wlans.items[0].wlan_name
    # Use a date 7 days ago to stay within the API's 30-day rolling window
    seven_days_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=7
    )
    start_time = seven_days_ago.strftime("%Y-%m-%dT00:00:00.000Z")
    end_time = seven_days_ago.strftime("%Y-%m-%dT23:59:59.999Z")
    result = await tools["central_get_wlans"](
        live_ctx,
        wlan_name=wlan_name,
        include=["throughput"],
        start_time=start_time,
        end_time=end_time,
    )
    assert isinstance(result, WlanEnvelope)
    assert result.items[0].throughput is not None
    assert all(sample.timestamp for sample in result.items[0].throughput)


async def test_get_wlan_stats_unknown_wlan_returns_no_data_string(tools, live_ctx):
    result = await tools["central_get_wlans"](
        live_ctx,
        wlan_name="__nonexistent_wlan__",
        include=["throughput"],
    )
    assert result.items == []
