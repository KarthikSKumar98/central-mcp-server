import pytest
from tests.conftest import FakeMCP
from models import Device
import tools.devices as mod

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


async def test_get_devices_no_filter(tools, live_ctx):
    result = await tools["central_get_devices"](live_ctx)
    assert isinstance(result, list)
    assert all(isinstance(d, Device) for d in result)


async def test_get_devices_by_device_type_ap(tools, live_ctx):
    result = await tools["central_get_devices"](live_ctx, device_type="ACCESS_POINT")
    assert isinstance(result, list)
    assert all(d.device_type == "ACCESS_POINT" for d in result)


async def test_get_devices_by_device_type_switch(tools, live_ctx):
    result = await tools["central_get_devices"](live_ctx, device_type="SWITCH")
    assert isinstance(result, list)
    assert all(d.device_type == "SWITCH" for d in result)


async def test_get_devices_by_device_type_gateway(tools, live_ctx):
    result = await tools["central_get_devices"](live_ctx, device_type="GATEWAY")
    assert isinstance(result, list)
    assert all(d.device_type == "GATEWAY" for d in result)


async def test_get_devices_is_provisioned_true(tools, live_ctx):
    result = await tools["central_get_devices"](live_ctx, is_provisioned=True)
    assert isinstance(result, list)
    assert all(d.is_provisioned is True for d in result)


async def test_get_devices_is_provisioned_false(tools, live_ctx):
    result = await tools["central_get_devices"](live_ctx, is_provisioned=False)
    assert isinstance(result, list)
    assert all(d.is_provisioned is False for d in result)


async def test_get_devices_site_assigned_true(tools, live_ctx):
    result = await tools["central_get_devices"](live_ctx, site_assigned=True)
    assert isinstance(result, list)
    assert all(d.site_id is not None for d in result)


async def test_get_devices_site_assigned_false(tools, live_ctx):
    result = await tools["central_get_devices"](live_ctx, site_assigned=False)
    assert isinstance(result, list)
    assert all(d.site_id is None for d in result)


async def test_find_device_by_serial(tools, live_ctx):
    devices = await tools["central_get_devices"](live_ctx)
    if not devices:
        pytest.skip("No devices available")
    serial = devices[0].serial_number
    result = await tools["central_find_device"](live_ctx, serial_number=serial)
    assert isinstance(result, Device)
    assert result.serial_number == serial


async def test_find_device_by_name(tools, live_ctx):
    devices = await tools["central_get_devices"](live_ctx)
    if not devices:
        pytest.skip("No devices available")
    name = devices[0].name
    result = await tools["central_find_device"](live_ctx, device_name=name)
    # May return a Device or an error string if name is not unique
    assert isinstance(result, (Device, str))


async def test_find_device_not_found(tools, live_ctx):
    result = await tools["central_find_device"](
        live_ctx, serial_number="ZZZZZZ_BOGUS_SERIAL"
    )
    assert isinstance(result, str)
