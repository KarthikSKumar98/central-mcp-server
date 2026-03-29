from unittest.mock import patch

import pytest

import tools.devices as mod
from models import Device
from tests.conftest import FakeMCP, make_ctx
from utils.devices import clean_device_data

RAW_DEVICE = {
    "serialNumber": "SN123",
    "macAddress": "aa:bb:cc:dd:ee:ff",
    "deviceType": "SWITCH",
    "model": "CX-6300",
    "partNumber": "PN1",
    "deviceName": "switch-01",
    "deviceFunction": "SWITCH",
    "status": "Up",
    "isProvisioned": "Yes",
    "role": None,
    "deployment": None,
    "tier": None,
    "firmwareVersion": "10.12",
    "siteId": "site-1",
    "siteName": "HQ",
    "deviceGroupName": "Switches",
    "scopeId": None,
    "ipv4": "10.0.0.1",
    "stackId": None,
}


RAW_DEVICE_2 = {**RAW_DEVICE, "serialNumber": "SN456", "deviceName": "switch-02"}


@pytest.fixture
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


@pytest.mark.asyncio
async def test_get_devices_no_filters(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_all_device_inventory",
        return_value=[RAW_DEVICE, RAW_DEVICE_2],
    ) as mock_api:
        result = await tools["central_get_devices"](ctx)
    mock_api.assert_called_once()
    call_kwargs = mock_api.call_args.kwargs
    assert call_kwargs["filter_str"] is None
    assert len(result) == 2


@pytest.mark.asyncio
async def test_get_devices_device_type_single(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_all_device_inventory", return_value=[]
    ) as mock_api:
        await tools["central_get_devices"](ctx, device_type="SWITCH")
    assert mock_api.call_args.kwargs["filter_str"] == "deviceType eq 'SWITCH'"


@pytest.mark.asyncio
async def test_get_devices_device_type_multiple(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_all_device_inventory", return_value=[]
    ) as mock_api:
        await tools["central_get_devices"](ctx, device_type="ACCESS_POINT,SWITCH")
    assert (
        mock_api.call_args.kwargs["filter_str"]
        == "deviceType in ('ACCESS_POINT', 'SWITCH')"
    )


@pytest.mark.asyncio
async def test_get_devices_invalid_device_type_raises(tools):
    ctx = make_ctx()
    with pytest.raises(ValueError):
        await tools["central_get_devices"](ctx, device_type="INVALID")


@pytest.mark.asyncio
async def test_get_devices_is_provisioned_true(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_all_device_inventory", return_value=[]
    ) as mock_api:
        await tools["central_get_devices"](ctx, is_provisioned=True)
    assert mock_api.call_args.kwargs["filter_str"] == "isProvisioned eq 'Yes'"


@pytest.mark.asyncio
async def test_get_devices_is_provisioned_false(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_all_device_inventory", return_value=[]
    ) as mock_api:
        await tools["central_get_devices"](ctx, is_provisioned=False)
    assert mock_api.call_args.kwargs["filter_str"] == "isProvisioned eq 'No'"


@pytest.mark.asyncio
async def test_get_devices_multiple_filters_combined(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_all_device_inventory", return_value=[]
    ) as mock_api:
        await tools["central_get_devices"](
            ctx, device_type="SWITCH", is_provisioned=True
        )
    filter_str = mock_api.call_args.kwargs["filter_str"]
    assert "deviceType eq 'SWITCH'" in filter_str
    assert "isProvisioned eq 'Yes'" in filter_str
    assert " and " in filter_str


@pytest.mark.asyncio
async def test_get_devices_result_cleaned(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_all_device_inventory",
        return_value=[RAW_DEVICE, RAW_DEVICE_2],
    ):
        result = await tools["central_get_devices"](ctx)
    assert result[0].serial_number == "SN123"
    assert result[0].is_provisioned is True


@pytest.mark.asyncio
async def test_find_device_serial_only(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_device_inventory",
        return_value={"items": [RAW_DEVICE]},
    ) as mock_api:
        result = await tools["central_find_device"](ctx, serial_number="SN123")
    assert mock_api.call_args.kwargs["filter_str"] == "serialNumber eq 'SN123'"
    assert result.serial_number == "SN123"


@pytest.mark.asyncio
async def test_find_device_name_only(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_device_inventory",
        return_value={"items": [RAW_DEVICE]},
    ) as mock_api:
        result = await tools["central_find_device"](ctx, device_name="switch-01")
    assert mock_api.call_args.kwargs["filter_str"] == "deviceName eq 'switch-01'"
    assert result.serial_number == "SN123"


@pytest.mark.asyncio
async def test_find_device_both_args_returns_error(tools):
    ctx = make_ctx()
    result = await tools["central_find_device"](
        ctx, device_name="switch-01", serial_number="SN123"
    )
    assert "only one" in result.lower()


@pytest.mark.asyncio
async def test_find_device_no_results(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_device_inventory",
        return_value={"items": []},
    ):
        result = await tools["central_find_device"](ctx, serial_number="MISSING")
    assert "No device found" in result


@pytest.mark.asyncio
async def test_find_device_multiple_results(tools):
    ctx = make_ctx()
    with patch(
        "tools.devices.MonitoringDevices.get_device_inventory",
        return_value={"items": [RAW_DEVICE, RAW_DEVICE]},
    ):
        result = await tools["central_find_device"](ctx, device_name="switch-01")
    assert "Multiple devices found" in result


# ---------------------------------------------------------------------------
# clean_device_data
# ---------------------------------------------------------------------------

_RAW_DEVICE = {
    "serialNumber": "SN123",
    "macAddress": "aa:bb:cc:dd:ee:ff",
    "deviceType": "ACCESS_POINT",
    "model": "AP-635",
    "partNumber": "JZ123A",
    "deviceName": "MyAP",
    "deviceFunction": None,
    "status": "ONLINE",
    "isProvisioned": "Yes",
    "role": None,
    "deployment": None,
    "tier": "ADVANCED_AP",
    "firmwareVersion": "10.6.0",
    "siteId": "site-1",
    "siteName": "HQ",
    "deviceGroupName": "Group1",
    "scopeId": "scope-1",
    "ipv4": "192.168.1.1",
    "stackId": None,
}


def test_clean_device_data_returns_device_models():
    result = clean_device_data([_RAW_DEVICE])
    assert len(result) == 1
    assert isinstance(result[0], Device)


def test_clean_device_data_field_mapping():
    d = clean_device_data([_RAW_DEVICE])[0]
    assert d.serial_number == "SN123"
    assert d.mac_address == "aa:bb:cc:dd:ee:ff"
    assert d.device_type == "ACCESS_POINT"
    assert d.name == "MyAP"
    assert d.firmware_version == "10.6.0"
    assert d.site_id == "site-1"
    assert d.site_name == "HQ"


def test_clean_device_data_is_provisioned_yes():
    d = clean_device_data([_RAW_DEVICE])[0]
    assert d.is_provisioned is True


def test_clean_device_data_is_provisioned_no():
    raw = {**_RAW_DEVICE, "isProvisioned": "No"}
    d = clean_device_data([raw])[0]
    assert d.is_provisioned is False


def test_clean_device_data_no_site():
    raw = {**_RAW_DEVICE, "siteId": None, "siteName": None}
    d = clean_device_data([raw])[0]
    assert d.site_id is None
    assert d.site_name is None
