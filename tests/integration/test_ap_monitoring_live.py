import pytest
from fastmcp.exceptions import ToolError

import tools.devices as mod
from models import APDetail, Device, DeviceEnvelope, DeviceTrendsEnvelope, TrendSample
from tests.conftest import FakeMCP

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


@pytest.fixture(scope="module")
async def ap_with_details(tools, live_ctx):
    """Return the serial number of the first online AP.

    Skips if no online APs are available.
    """
    aps = await tools["central_get_devices"](
        live_ctx, device_type="ap", device_status="ONLINE"
    )
    if not aps.items:
        pytest.skip("No online APs available")
    return aps.items[0].serial_number


# ---------------------------------------------------------------------------
# central_get_devices AP tests
# ---------------------------------------------------------------------------


async def test_get_aps_no_filter(tools, live_ctx):
    result = await tools["central_get_devices"](live_ctx, device_type="ap")
    assert isinstance(result, DeviceEnvelope)
    assert all(isinstance(ap, Device) for ap in result.items)
    assert all(ap.serial_number for ap in result.items)


async def test_get_aps_online_filter(tools, live_ctx):
    result = await tools["central_get_devices"](
        live_ctx, device_type="ap", device_status="ONLINE"
    )
    assert isinstance(result, DeviceEnvelope)
    assert all(ap.status == "ONLINE" for ap in result.items)


async def test_get_aps_offline_filter(tools, live_ctx):
    result = await tools["central_get_devices"](
        live_ctx, device_type="ap", device_status="OFFLINE"
    )
    assert isinstance(result, DeviceEnvelope)
    assert all(ap.status == "OFFLINE" for ap in result.items)


async def test_get_aps_by_serial_filter(tools, live_ctx):
    aps = await tools["central_get_devices"](live_ctx, device_type="ap")
    if not aps.items:
        pytest.skip("No APs available")
    serial = aps.items[0].serial_number
    result = await tools["central_get_devices"](
        live_ctx, device_type="ap", serial_number=serial
    )
    assert isinstance(result, DeviceEnvelope)
    assert result.items
    assert all(ap.serial_number == serial for ap in result.items)


async def test_get_aps_by_model_filter(tools, live_ctx):
    aps = await tools["central_get_devices"](live_ctx, device_type="ap")
    if not aps.items:
        pytest.skip("No APs available")
    model = aps.items[0].model
    if not model:
        pytest.skip("First AP has no model field")
    result = await tools["central_get_devices"](live_ctx, device_type="ap", model=model)
    assert isinstance(result, DeviceEnvelope)
    assert all(ap.model == model for ap in result.items)


# ---------------------------------------------------------------------------
# central_get_device_details AP tests
# ---------------------------------------------------------------------------


async def test_get_ap_details_base(tools, live_ctx, ap_with_details):
    result = await tools["central_get_device_details"](
        live_ctx, serial_number=ap_with_details
    )
    assert isinstance(result, APDetail)
    assert result.serial_number == ap_with_details
    assert result.uptime_in_millis is not None


async def test_get_ap_details_with_radios(tools, live_ctx, ap_with_details):
    result = await tools["central_get_device_details"](
        live_ctx, serial_number=ap_with_details, include=["radios"]
    )
    assert isinstance(result, APDetail)
    if result.radios is not None:
        for radio in result.radios:
            assert radio.radio_number is not None or radio.band is not None


async def test_get_ap_details_with_radios_and_ports(tools, live_ctx, ap_with_details):
    result = await tools["central_get_device_details"](
        live_ctx, serial_number=ap_with_details, include=["radios", "ports"]
    )
    assert isinstance(result, APDetail)
    # radios and ports fields should exist on the model (may be None or empty list)
    assert hasattr(result, "radios")
    assert hasattr(result, "ports")


async def test_get_ap_details_not_found(tools, live_ctx):
    with pytest.raises(ToolError):
        await tools["central_get_device_details"](
            live_ctx, serial_number="__nonexistent_serial_xyz__"
        )


# ---------------------------------------------------------------------------
# central_get_device_trends AP tests
# ---------------------------------------------------------------------------


async def test_get_ap_trends_cpu(tools, live_ctx, ap_with_details):
    result = await tools["central_get_device_trends"](
        live_ctx, serial_number=ap_with_details, metric="cpu-utilization"
    )
    assert isinstance(result, DeviceTrendsEnvelope)
    assert all(isinstance(sample, TrendSample) for sample in result.items)
    assert all(sample.timestamp for sample in result.items)


async def test_get_ap_trends_throughput(tools, live_ctx, ap_with_details):
    result = await tools["central_get_device_trends"](
        live_ctx, serial_number=ap_with_details, metric="throughput"
    )
    assert isinstance(result, DeviceTrendsEnvelope)
    assert all(isinstance(sample, TrendSample) for sample in result.items)
    assert all(sample.timestamp for sample in result.items)


async def test_get_ap_trends_radio_scope(tools, live_ctx, ap_with_details):
    # Discover a valid radio_number from AP details first
    details = await tools["central_get_device_details"](
        live_ctx, serial_number=ap_with_details, include=["radios"]
    )
    if not isinstance(details, APDetail) or not details.radios:
        pytest.skip("No radios found for AP")
    radio_number = details.radios[0].radio_number
    if radio_number is None:
        pytest.skip("Radio has no radio_number field")
    result = await tools["central_get_device_trends"](
        live_ctx,
        serial_number=ap_with_details,
        scope="radio",
        metric="channel-utilization",
        radio_number=int(radio_number),
    )
    assert isinstance(result, DeviceTrendsEnvelope)


async def test_get_ap_trends_port_scope(tools, live_ctx, ap_with_details):
    # Discover a valid port_index from AP details first
    details = await tools["central_get_device_details"](
        live_ctx, serial_number=ap_with_details, include=["ports"]
    )
    if not isinstance(details, APDetail) or not details.ports:
        pytest.skip("No ports found for AP")
    port_index = details.ports[0].port_index
    if port_index is None:
        pytest.skip("Port has no port_index field")
    result = await tools["central_get_device_trends"](
        live_ctx,
        serial_number=ap_with_details,
        scope="port",
        metric="throughput",
        port_index=int(port_index),
    )
    assert isinstance(result, DeviceTrendsEnvelope)


async def test_get_ap_trends_radio_scope_missing_radio_number(
    tools, live_ctx, ap_with_details
):
    with pytest.raises(ToolError, match="radio_number"):
        await tools["central_get_device_trends"](
            live_ctx,
            serial_number=ap_with_details,
            scope="radio",
            metric="channel-utilization",
        )


async def test_get_ap_trends_port_scope_missing_port_index(
    tools, live_ctx, ap_with_details
):
    with pytest.raises(ToolError, match="port_index"):
        await tools["central_get_device_trends"](
            live_ctx,
            serial_number=ap_with_details,
            scope="port",
            metric="throughput",
        )


async def test_get_ap_trends_invalid_metric_for_scope(tools, live_ctx, ap_with_details):
    with pytest.raises(ToolError, match="Invalid metric"):
        await tools["central_get_device_trends"](
            live_ctx,
            serial_number=ap_with_details,
            scope="ap",
            metric="channel-quality",
        )
