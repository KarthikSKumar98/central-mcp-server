import pytest

import tools.ap_monitoring as mod
from models import AccessPoint
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


async def test_get_aps_online_filter(tools, live_ctx):
    result = await tools["central_get_aps"](live_ctx, status="ONLINE")
    assert isinstance(result, list)
    assert all(ap.status == "ONLINE" for ap in result)


async def test_get_aps_offline_filter(tools, live_ctx):
    result = await tools["central_get_aps"](live_ctx, status="OFFLINE")
    if isinstance(result, str):
        assert "No access points found" in result
        return
    assert isinstance(result, list)
    assert all(ap.status == "OFFLINE" for ap in result)


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
