import pytest

import tools.wlans as mod
from models import WLAN
from tests.conftest import FakeMCP

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


async def test_get_wlans_returns_results(tools, live_ctx):
    result = await tools["central_get_wlans"](live_ctx)
    assert isinstance(result, (list, str))
    if isinstance(result, list):
        assert all(isinstance(w, WLAN) for w in result)


async def test_get_wlans_all_have_wlan_name(tools, live_ctx):
    result = await tools["central_get_wlans"](live_ctx)
    if isinstance(result, str):
        pytest.skip("No WLANs available")
    assert all(w.wlan_name is not None for w in result)


async def test_get_wlans_with_site_id_filter(tools, live_ctx):
    import tools.sites as sites_mod
    from tests.conftest import FakeMCP as FakeMCPLocal

    fake = FakeMCPLocal()
    sites_mod.register(fake)
    site_tools = fake._tools

    mapping = await site_tools["central_get_summary"](live_ctx)
    if not mapping:
        pytest.skip("No sites available")

    first_site_id = next(iter(mapping.values()))["site_id"]
    result = await tools["central_get_wlans"](live_ctx, site_id=first_site_id)
    assert isinstance(result, (list, str))
    if isinstance(result, list):
        assert all(isinstance(w, WLAN) for w in result)


async def test_get_wlans_wlan_name_filter_client_side(tools, live_ctx):
    all_wlans = await tools["central_get_wlans"](live_ctx)
    if isinstance(all_wlans, str) or not all_wlans:
        pytest.skip("No WLANs available")

    target_name = all_wlans[0].wlan_name
    result = await tools["central_get_wlans"](live_ctx, wlan_name=target_name)
    assert isinstance(result, list)
    assert all(w.wlan_name == target_name for w in result)


async def test_get_wlans_unknown_name_returns_string(tools, live_ctx):
    result = await tools["central_get_wlans"](live_ctx, wlan_name="__nonexistent_wlan__")
    assert isinstance(result, str)
    assert "No WLANs found" in result


async def test_get_wlan_stats_for_known_wlan(tools, live_ctx):
    all_wlans = await tools["central_get_wlans"](live_ctx)
    if isinstance(all_wlans, str) or not all_wlans:
        pytest.skip("No WLANs available to test stats")

    wlan_name = all_wlans[0].wlan_name
    result = await tools["central_get_wlan_stats"](live_ctx, wlan_name=wlan_name)
    assert isinstance(result, list)
    assert all(sample.timestamp for sample in result)
    assert all(hasattr(sample, "tx") and hasattr(sample, "rx") for sample in result)


async def test_get_wlan_stats_explicit_time_window(tools, live_ctx):
    all_wlans = await tools["central_get_wlans"](live_ctx)
    if isinstance(all_wlans, str) or not all_wlans:
        pytest.skip("No WLANs available to test stats")

    wlan_name = all_wlans[0].wlan_name
    result = await tools["central_get_wlan_stats"](
        live_ctx,
        wlan_name=wlan_name,
        start_time="2026-04-07T00:00:00.000Z",
        end_time="2026-04-07T23:59:59.999Z",
    )
    assert isinstance(result, list)
    assert all(sample.timestamp for sample in result)


async def test_get_wlan_stats_unknown_wlan_returns_no_data_string(tools, live_ctx):
    result = await tools["central_get_wlan_stats"](
        live_ctx, wlan_name="__nonexistent_wlan__"
    )
    assert result == "No throughput data found for WLAN '__nonexistent_wlan__'."
