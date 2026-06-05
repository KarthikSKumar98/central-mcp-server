import pytest

import tools.ap_monitoring as mod
from models import AccessPoint, APDetail, TrendSample
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
    aps = await tools["central_get_aps"](live_ctx, status="ONLINE")
    if isinstance(aps, str) or not aps:
        pytest.skip("No online APs available")
    return aps[0].serial_number


# ---------------------------------------------------------------------------
# central_get_aps tests
# ---------------------------------------------------------------------------


async def test_get_aps_no_filter(tools, live_ctx):
    result = await tools["central_get_aps"](live_ctx)
    if isinstance(result, str):
        assert "No access points found" in result
        return
    assert isinstance(result, list)
    assert all(isinstance(ap, AccessPoint) for ap in result)
    assert all(ap.serial_number for ap in result)


async def test_get_aps_online_filter(tools, live_ctx):
    result = await tools["central_get_aps"](live_ctx, status="ONLINE")
    if isinstance(result, str):
        assert "No access points found" in result
        return
    assert isinstance(result, list)
    assert all(ap.status == "ONLINE" for ap in result)


async def test_get_aps_offline_filter(tools, live_ctx):
    result = await tools["central_get_aps"](live_ctx, status="OFFLINE")
    if isinstance(result, str):
        assert "No access points found" in result
        return
    assert isinstance(result, list)
    assert all(ap.status == "OFFLINE" for ap in result)


async def test_get_aps_by_serial_filter(tools, live_ctx):
    aps = await tools["central_get_aps"](live_ctx)
    if isinstance(aps, str) or not aps:
        pytest.skip("No APs available")
    serial = aps[0].serial_number
    result = await tools["central_get_aps"](live_ctx, serial_number=serial)
    assert isinstance(result, list)
    assert len(result) >= 1
    assert all(ap.serial_number == serial for ap in result)


async def test_get_aps_by_model_filter(tools, live_ctx):
    aps = await tools["central_get_aps"](live_ctx)
    if isinstance(aps, str) or not aps:
        pytest.skip("No APs available")
    model = aps[0].model
    if not model:
        pytest.skip("First AP has no model field")
    result = await tools["central_get_aps"](live_ctx, model=model)
    assert isinstance(result, list)
    assert all(ap.model == model for ap in result)


# ---------------------------------------------------------------------------
# central_get_ap_details tests
# ---------------------------------------------------------------------------


async def test_get_ap_details_base(tools, live_ctx, ap_with_details):
    result = await tools["central_get_ap_details"](
        live_ctx, serial_number=ap_with_details
    )
    assert isinstance(result, APDetail)
    assert result.serial_number == ap_with_details
    assert result.uptime_in_millis is not None


async def test_get_ap_details_with_radios(tools, live_ctx, ap_with_details):
    result = await tools["central_get_ap_details"](
        live_ctx, serial_number=ap_with_details, include=["radios"]
    )
    assert isinstance(result, APDetail)
    if result.radios is not None:
        for radio in result.radios:
            assert radio.radio_number is not None or radio.band is not None


async def test_get_ap_details_with_radios_and_ports(tools, live_ctx, ap_with_details):
    result = await tools["central_get_ap_details"](
        live_ctx, serial_number=ap_with_details, include=["radios", "ports"]
    )
    assert isinstance(result, APDetail)
    # radios and ports fields should exist on the model (may be None or empty list)
    assert hasattr(result, "radios")
    assert hasattr(result, "ports")


async def test_get_ap_details_not_found(tools, live_ctx):
    result = await tools["central_get_ap_details"](
        live_ctx, serial_number="__nonexistent_serial_xyz__"
    )
    # Known bug B4: not-found case returns an error string rather than a clean
    # "No AP found..." message, but it must still be a string (not an exception).
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# central_get_ap_trends tests
# ---------------------------------------------------------------------------


async def test_get_ap_trends_cpu(tools, live_ctx, ap_with_details):
    result = await tools["central_get_ap_trends"](
        live_ctx, serial_number=ap_with_details, metric="cpu-utilization"
    )
    assert isinstance(result, (list, str))
    if isinstance(result, list):
        assert all(isinstance(sample, TrendSample) for sample in result)
        assert all(sample.timestamp for sample in result)


async def test_get_ap_trends_throughput(tools, live_ctx, ap_with_details):
    result = await tools["central_get_ap_trends"](
        live_ctx, serial_number=ap_with_details, metric="throughput"
    )
    assert isinstance(result, (list, str))
    if isinstance(result, list):
        assert all(isinstance(sample, TrendSample) for sample in result)
        assert all(sample.timestamp for sample in result)


async def test_get_ap_trends_radio_scope(tools, live_ctx, ap_with_details):
    # Discover a valid radio_number from AP details first
    details = await tools["central_get_ap_details"](
        live_ctx, serial_number=ap_with_details, include=["radios"]
    )
    if not isinstance(details, APDetail) or not details.radios:
        pytest.skip("No radios found for AP")
    radio_number = details.radios[0].radio_number
    if radio_number is None:
        pytest.skip("Radio has no radio_number field")
    result = await tools["central_get_ap_trends"](
        live_ctx,
        serial_number=ap_with_details,
        scope="radio",
        metric="channel-utilization",
        radio_number=int(radio_number),
    )
    assert isinstance(result, (list, str))


async def test_get_ap_trends_port_scope(tools, live_ctx, ap_with_details):
    # Discover a valid port_index from AP details first
    details = await tools["central_get_ap_details"](
        live_ctx, serial_number=ap_with_details, include=["ports"]
    )
    if not isinstance(details, APDetail) or not details.ports:
        pytest.skip("No ports found for AP")
    port_index = details.ports[0].port_index
    if port_index is None:
        pytest.skip("Port has no port_index field")
    result = await tools["central_get_ap_trends"](
        live_ctx,
        serial_number=ap_with_details,
        scope="port",
        metric="throughput",
        port_index=int(port_index),
    )
    assert isinstance(result, (list, str))


async def test_get_ap_trends_radio_scope_missing_radio_number(tools, live_ctx):
    result = await tools["central_get_ap_trends"](
        live_ctx,
        serial_number="DUMMY0000001",
        scope="radio",
        metric="channel-utilization",
        # radio_number intentionally omitted
    )
    assert isinstance(result, str)
    assert "radio_number" in result


async def test_get_ap_trends_port_scope_missing_port_index(tools, live_ctx):
    result = await tools["central_get_ap_trends"](
        live_ctx,
        serial_number="DUMMY0000001",
        scope="port",
        metric="throughput",
        # port_index intentionally omitted
    )
    assert isinstance(result, str)
    assert "port_index" in result


async def test_get_ap_trends_invalid_metric_for_scope(tools, live_ctx):
    result = await tools["central_get_ap_trends"](
        live_ctx,
        serial_number="DUMMY0000001",
        scope="ap",
        metric="channel-quality",  # only valid for radio scope, not ap
    )
    assert isinstance(result, str)
    assert "invalid metric" in result.lower() or "valid metrics" in result.lower()
