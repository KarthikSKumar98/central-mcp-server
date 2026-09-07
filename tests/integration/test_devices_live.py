import pytest

import tools.devices as mod
from models import Device, DeviceEnvelope
from tests.conftest import FakeMCP

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


async def test_get_devices_no_filter(tools, live_ctx):
    result = await tools["central_get_devices"](live_ctx)
    assert isinstance(result, DeviceEnvelope)
    assert all(isinstance(d, Device) for d in result.items)


async def test_get_devices_by_device_type_ap(tools, live_ctx):
    result = await tools["central_get_devices"](live_ctx, device_type="ap")
    assert isinstance(result, DeviceEnvelope)
    assert all(d.device_type == "ACCESS_POINT" for d in result.items)


async def test_get_devices_by_device_type_switch(tools, live_ctx):
    result = await tools["central_get_devices"](live_ctx, device_type="switch")
    assert isinstance(result, DeviceEnvelope)
    assert all(d.device_type == "SWITCH" for d in result.items)


async def test_get_devices_by_device_type_gateway(tools, live_ctx):
    result = await tools["central_get_devices"](live_ctx, device_type="gateway")
    assert isinstance(result, DeviceEnvelope)
    assert all(d.device_type == "GATEWAY" for d in result.items)


async def test_get_devices_is_provisioned_true(tools, live_ctx):
    result = await tools["central_get_devices"](live_ctx, is_provisioned=True)
    assert isinstance(result, DeviceEnvelope)
    assert all(d.is_provisioned is True for d in result.items)


async def test_get_devices_is_provisioned_false(tools, live_ctx):
    result = await tools["central_get_devices"](live_ctx, is_provisioned=False)
    assert isinstance(result, DeviceEnvelope)
    assert all(d.is_provisioned is False for d in result.items)


async def test_get_devices_site_assigned_true(tools, live_ctx):
    result = await tools["central_get_devices"](live_ctx, site_assigned=True)
    assert isinstance(result, DeviceEnvelope)
    assert all(d.site_id is not None for d in result.items)


async def test_get_devices_site_assigned_false(tools, live_ctx):
    result = await tools["central_get_devices"](live_ctx, site_assigned=False)
    assert isinstance(result, DeviceEnvelope)
    assert all(d.site_id is None for d in result.items)


async def test_find_device_by_serial(tools, live_ctx):
    devices = await tools["central_get_devices"](live_ctx)
    if not devices.items:
        pytest.skip("No devices available")
    serial = devices.items[0].serial_number
    result = await tools["central_get_devices"](live_ctx, serial_number=serial)
    assert isinstance(result, DeviceEnvelope)
    assert len(result.items) == 1
    assert result.items[0].serial_number == serial


async def test_find_device_by_name(tools, live_ctx):
    devices = await tools["central_get_devices"](live_ctx)
    if not devices.items:
        pytest.skip("No devices available")
    # Unnamed devices carry an empty name, which would filter nothing.
    name = next((device.name for device in devices.items if device.name), None)
    if not name:
        pytest.skip("No device with a non-empty name available")
    result = await tools["central_get_devices"](live_ctx, device_name=name)
    assert isinstance(result, DeviceEnvelope)
    assert len(result.items) <= 1


async def test_find_device_not_found(tools, live_ctx):
    result = await tools["central_get_devices"](
        live_ctx, serial_number="ZZZZZZ_BOGUS_SERIAL"
    )
    assert isinstance(result, DeviceEnvelope)
    assert result.items == []
