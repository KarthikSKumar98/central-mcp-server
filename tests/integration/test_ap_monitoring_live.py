import pytest

import tools.ap_monitoring as mod
from models import WLAN, AccessPoint, AccessPointStatistics
from tests.conftest import FakeMCP

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


async def test_get_aps_no_filter(tools, live_ctx):
    result = await tools["central_get_aps"](live_ctx)
    assert isinstance(result, list)
    assert all(isinstance(ap, AccessPoint) for ap in result)
    assert all("serial_number" in ap.model_dump() for ap in result)


async def test_get_aps_online_filter(tools, live_ctx):
    result = await tools["central_get_aps"](live_ctx, status="ONLINE")
    assert isinstance(result, list)
    assert all(ap.status == "ONLINE" for ap in result)
    assert all("last_seen_at" not in ap.model_dump() for ap in result)


async def test_get_aps_offline_filter(tools, live_ctx):
    result = await tools["central_get_aps"](live_ctx, status="OFFLINE")
    if isinstance(result, str):
        assert "No access points found" in result
        return
    assert isinstance(result, list)
    assert all(ap.status == "OFFLINE" for ap in result)
    assert all("uptime_in_millis" not in ap.model_dump() for ap in result)


async def test_get_aps_by_serial_number(tools, live_ctx):
    aps = await tools["central_get_aps"](live_ctx)
    if not aps:
        pytest.skip("No APs available")
    serial = aps[0].serial_number
    result = await tools["central_get_aps"](live_ctx, serial_number=serial)
    assert isinstance(result, list)
    assert len(result) >= 1
    assert all(ap.serial_number == serial for ap in result)


async def test_get_ap_statistics_for_known_ap(tools, live_ctx):
    aps = await tools["central_get_aps"](live_ctx)
    if not aps:
        pytest.skip("No APs available")
    serial = aps[0].serial_number
    result = await tools["central_get_ap_statistics"](live_ctx, serial_number=serial)
    assert isinstance(result, (list, str))


async def test_get_ap_wlans_for_online_ap(tools, live_ctx):
    aps = await tools["central_get_aps"](live_ctx, status="ONLINE")
    if isinstance(aps, str) or not aps:
        pytest.skip("No online APs available")
    serial = aps[0].serial_number
    result = await tools["central_get_ap_wlans"](live_ctx, serial_number=serial)
    assert isinstance(result, (list, str))
    if isinstance(result, list):
        assert all(isinstance(w, WLAN) for w in result)


async def test_get_ap_wlans_wlan_name_filter(tools, live_ctx):
    aps = await tools["central_get_aps"](live_ctx, status="ONLINE")
    if isinstance(aps, str) or not aps:
        pytest.skip("No online APs available")
    serial = aps[0].serial_number
    all_wlans = await tools["central_get_ap_wlans"](live_ctx, serial_number=serial)
    if isinstance(all_wlans, str) or not all_wlans:
        pytest.skip("No WLANs on AP")
    target_name = all_wlans[0].wlan_name
    result = await tools["central_get_ap_wlans"](
        live_ctx, serial_number=serial, wlan_name=target_name
    )
    assert isinstance(result, list)
    assert all(w.wlan_name == target_name for w in result)
    assert all(isinstance(wlan, WLAN) for wlan in result)
