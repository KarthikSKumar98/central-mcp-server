"""Live smoke tests for switch, gateway, and cluster monitoring tools.

Mirrors the structure of test_ap_monitoring_live.py: module-scoped FakeMCP
registration, dynamic entity discovery (list first, pick first result) with
known dev-account entities as fallbacks, and typed envelope/detail assertions.

Covered tools (4):
- central_get_devices, central_get_device_details, central_get_device_trends
- gateway-only central_get_gateway_cluster (including capacity)

Known live quirks tolerated:
- vsx include 404s on non-VSX platforms (surfaces as {"error": ...}).
- wan/vpn-availability return -1 without configured probes.
- tunnel/uplink scopes may legitimately have no data on some gateways.
"""

import pytest
from fastmcp.exceptions import ToolError

import tools.devices as devices_mod
import tools.gateway_monitoring as gw_mod
from models import (
    Device,
    DeviceEnvelope,
    DeviceTrendsEnvelope,
    GatewayCluster,
    GatewayClusterEnvelope,
    GatewayDetail,
    SwitchDetail,
    TrendSample,
)
from tests.conftest import FakeMCP
from utils.common import lookup_inventory_device

pytestmark = pytest.mark.integration

# Known dev-account entities (fallbacks when discovery yields nothing).
FALLBACK_SWITCHES = ["SG16KRR027", "SG34L5002Y", "SG34L5006M", "FCW2026D0KV"]
FALLBACK_GATEWAYS = ["DL0006948", "DL0006931", "TWSTKYH00D"]
FALLBACK_CLUSTERS = ["auto_group_168", "CP-LHR-MBGW-CLUSTER"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def switch_tools():
    fake = FakeMCP()
    devices_mod.register(fake)
    return fake._tools


@pytest.fixture(scope="module")
def gateway_tools():
    fake = FakeMCP()
    devices_mod.register(fake)
    gw_mod.register(fake)
    return fake._tools


@pytest.fixture(scope="module")
async def a_switch_serial(switch_tools, live_ctx):
    """Serial of the first discoverable switch that also resolves in inventory.

    Monitoring lists third-party/unmanaged switches that the inventory API
    omits; details/trends need the inventory record, so skip those.
    """
    conn = live_ctx.lifespan_context["conn"]
    online = await switch_tools["central_get_devices"](
        live_ctx, device_type="switch", device_status="ONLINE"
    )
    everything = await switch_tools["central_get_devices"](live_ctx, device_type="switch")
    for switch in [*online.items, *everything.items]:
        if lookup_inventory_device(conn, switch.serial_number) is not None:
            return switch.serial_number
    return FALLBACK_SWITCHES[0]


@pytest.fixture(scope="module")
async def a_gateway_serial(gateway_tools, live_ctx):
    """Serial of the first discoverable gateway (online preferred), else a fallback."""
    gateways = await gateway_tools["central_get_devices"](
        live_ctx, device_type="gateway", device_status="ONLINE"
    )
    if gateways.items:
        return gateways.items[0].serial_number
    gateways = await gateway_tools["central_get_devices"](
        live_ctx, device_type="gateway"
    )
    if gateways.items:
        return gateways.items[0].serial_number
    return FALLBACK_GATEWAYS[0]


@pytest.fixture(scope="module")
async def a_cluster_name(gateway_tools, live_ctx):
    """Name of the first discoverable cluster, else a fallback.

    Discovers via the cluster_name embedded on a gateway detail item.
    """
    gateways = await gateway_tools["central_get_devices"](
        live_ctx, device_type="gateway"
    )
    for gateway in gateways.items:
        try:
            details = await gateway_tools["central_get_device_details"](
                live_ctx, serial_number=gateway.serial_number
            )
        except ToolError:
            continue
        if details.cluster_name:
            return details.cluster_name
    return FALLBACK_CLUSTERS[0]


# ===========================================================================
# central_get_devices (switch)
# ===========================================================================


async def test_get_switches_no_filter(switch_tools, live_ctx):
    result = await switch_tools["central_get_devices"](live_ctx, device_type="switch")
    assert isinstance(result, DeviceEnvelope)
    assert all(isinstance(sw, Device) for sw in result.items)
    assert all(sw.serial_number for sw in result.items)


async def test_get_switches_online_filter(switch_tools, live_ctx):
    result = await switch_tools["central_get_devices"](
        live_ctx, device_type="switch", device_status="ONLINE"
    )
    assert isinstance(result, DeviceEnvelope)
    assert all(sw.status == "ONLINE" for sw in result.items)


async def test_get_switches_by_model_filter(switch_tools, live_ctx):
    switches = await switch_tools["central_get_devices"](live_ctx, device_type="switch")
    if not switches.items:
        pytest.skip("No switches available")
    model = switches.items[0].model
    if not model:
        pytest.skip("First switch has no model field")
    result = await switch_tools["central_get_devices"](
        live_ctx, device_type="switch", model=model
    )
    assert isinstance(result, DeviceEnvelope)
    assert all(sw.model == model for sw in result.items)


# ===========================================================================
# central_get_device_details (switch)
# ===========================================================================


async def test_get_switch_details_base(switch_tools, live_ctx, a_switch_serial):
    result = await switch_tools["central_get_device_details"](
        live_ctx, serial_number=a_switch_serial
    )
    assert isinstance(result, SwitchDetail)
    assert result.serial_number


async def test_get_switch_details_with_interfaces_and_hardware(
    switch_tools, live_ctx, a_switch_serial
):
    result = await switch_tools["central_get_device_details"](
        live_ctx,
        serial_number=a_switch_serial,
        include=["interfaces", "hardware"],
    )
    assert isinstance(result, SwitchDetail)
    serialized = result.model_dump()
    # include keys are additive; they should be present (possibly empty/error).
    assert "interfaces" in serialized or "hardware" in serialized


async def test_get_switch_details_with_vsx_tolerates_error(
    switch_tools, live_ctx, a_switch_serial
):
    """Vsx include 404s on non-VSX platforms — must surface as {error: ...}, not raise."""
    result = await switch_tools["central_get_device_details"](
        live_ctx, serial_number=a_switch_serial, include=["vsx"]
    )
    assert isinstance(result, SwitchDetail)
    serialized = result.model_dump()
    if "vsx" in serialized and isinstance(serialized["vsx"], dict):
        # Either real VSX data or an isolated error dict — both acceptable.
        assert "error" in serialized["vsx"] or serialized["vsx"]


async def test_get_switch_details_not_found(switch_tools, live_ctx):
    with pytest.raises(ToolError):
        await switch_tools["central_get_device_details"](
            live_ctx, serial_number="__nonexistent_switch_xyz__"
        )


# ===========================================================================
# central_get_device_trends (switch)
# ===========================================================================


async def test_get_switch_trends_hardware(switch_tools, live_ctx, a_switch_serial):
    result = await switch_tools["central_get_device_trends"](
        live_ctx, serial_number=a_switch_serial, scope="hardware"
    )
    assert isinstance(result, DeviceTrendsEnvelope)
    assert all(isinstance(s, TrendSample) for s in result.items)
    assert all(s.timestamp for s in result.items)


async def test_get_switch_trends_interface(switch_tools, live_ctx, a_switch_serial):
    result = await switch_tools["central_get_device_trends"](
        live_ctx, serial_number=a_switch_serial, scope="interface"
    )
    # interface scope may legitimately have no data on some switches.
    assert isinstance(result, DeviceTrendsEnvelope)
    assert all(isinstance(s, TrendSample) for s in result.items)


# ===========================================================================
# central_get_devices (gateway)
# ===========================================================================


async def test_get_gateways_no_filter(gateway_tools, live_ctx):
    result = await gateway_tools["central_get_devices"](live_ctx, device_type="gateway")
    assert isinstance(result, DeviceEnvelope)
    assert all(isinstance(gw, Device) for gw in result.items)
    assert all(gw.serial_number for gw in result.items)


async def test_get_gateways_online_filter(gateway_tools, live_ctx):
    result = await gateway_tools["central_get_devices"](
        live_ctx, device_type="gateway", device_status="ONLINE"
    )
    assert isinstance(result, DeviceEnvelope)
    assert all(gw.status == "ONLINE" for gw in result.items)


async def test_get_gateways_by_serial_filter(gateway_tools, live_ctx):
    gateways = await gateway_tools["central_get_devices"](
        live_ctx, device_type="gateway"
    )
    if not gateways.items:
        pytest.skip("No gateways available")
    serial = gateways.items[0].serial_number
    result = await gateway_tools["central_get_devices"](
        live_ctx, device_type="gateway", serial_number=serial
    )
    assert isinstance(result, DeviceEnvelope)
    assert all(gw.serial_number == serial for gw in result.items)


# ===========================================================================
# central_get_device_details (gateway)
# ===========================================================================


async def test_get_gateway_details_base(gateway_tools, live_ctx, a_gateway_serial):
    result = await gateway_tools["central_get_device_details"](
        live_ctx, serial_number=a_gateway_serial
    )
    assert isinstance(result, GatewayDetail)
    assert result.serial_number == a_gateway_serial


async def test_get_gateway_details_with_includes(
    gateway_tools, live_ctx, a_gateway_serial
):
    result = await gateway_tools["central_get_device_details"](
        live_ctx,
        serial_number=a_gateway_serial,
        include=["ports", "tunnels", "uplinks", "vlans"],
    )
    assert isinstance(result, GatewayDetail)
    # All include fields exist on the model (each may be None / empty list).
    for attr in ("ports", "tunnels", "uplinks", "vlans"):
        assert hasattr(result, attr)


async def test_get_gateway_details_not_found(gateway_tools, live_ctx):
    with pytest.raises(ToolError):
        await gateway_tools["central_get_device_details"](
            live_ctx, serial_number="__nonexistent_gateway_xyz__"
        )


# ===========================================================================
# central_get_device_trends (gateway)
# ===========================================================================


async def test_get_gateway_trends_cpu(gateway_tools, live_ctx, a_gateway_serial):
    result = await gateway_tools["central_get_device_trends"](
        live_ctx, serial_number=a_gateway_serial, metric="cpu-utilization"
    )
    assert isinstance(result, DeviceTrendsEnvelope)
    assert all(isinstance(s, TrendSample) for s in result.items)
    assert all(s.timestamp for s in result.items)


async def test_get_gateway_trends_wan_availability_tolerates_minus_one(
    gateway_tools, live_ctx, a_gateway_serial
):
    """wan-availability returns -1 without probes — pass-through, no error."""
    result = await gateway_tools["central_get_device_trends"](
        live_ctx, serial_number=a_gateway_serial, metric="wan-availability"
    )
    assert isinstance(result, DeviceTrendsEnvelope)


async def test_get_gateway_trends_temperature(
    gateway_tools, live_ctx, a_gateway_serial
):
    result = await gateway_tools["central_get_device_trends"](
        live_ctx, serial_number=a_gateway_serial, metric="hardware-temperature"
    )
    assert isinstance(result, DeviceTrendsEnvelope)
    assert all(isinstance(s, TrendSample) for s in result.items)


async def test_get_gateway_trends_port_scope(gateway_tools, live_ctx, a_gateway_serial):
    """Discover a port_number from details, then query port-scope trends."""
    details = await gateway_tools["central_get_device_details"](
        live_ctx, serial_number=a_gateway_serial, include=["ports"]
    )
    if not isinstance(details, GatewayDetail) or not details.ports:
        pytest.skip("No ports found for gateway")
    port_number = details.ports[0].port_number
    if port_number is None:
        pytest.skip("Port has no port_number field")
    result = await gateway_tools["central_get_device_trends"](
        live_ctx,
        serial_number=a_gateway_serial,
        metric="throughput",
        scope="port",
        port_number=str(port_number),
    )
    # Port scope may legitimately return an empty typed envelope.
    assert isinstance(result, DeviceTrendsEnvelope)


# ===========================================================================
# central_get_gateway_cluster
# ===========================================================================


async def test_get_gateway_cluster(gateway_tools, live_ctx, a_cluster_name):
    result = await gateway_tools["central_get_gateway_cluster"](
        live_ctx, cluster_name=a_cluster_name
    )
    assert isinstance(result, GatewayClusterEnvelope)
    if not result.items:
        pytest.skip("Cluster unavailable")
    cluster = result.items[0]
    assert isinstance(cluster, GatewayCluster)
    assert cluster.cluster_name == a_cluster_name
    assert isinstance(cluster.members, list)
    assert cluster.members[0].serial_number


async def test_get_gateway_cluster_with_includes(
    gateway_tools, live_ctx, a_cluster_name
):
    result = await gateway_tools["central_get_gateway_cluster"](
        live_ctx,
        cluster_name=a_cluster_name,
        include=["tunnels", "vlan_mismatch", "connectivity"],
    )
    if not result.items:
        pytest.skip("Cluster unavailable")
    cluster = result.items[0]
    for attr in ("tunnels", "vlan_mismatch", "connectivity"):
        assert hasattr(cluster, attr)


async def test_get_gateway_cluster_not_found(gateway_tools, live_ctx):
    result = await gateway_tools["central_get_gateway_cluster"](
        live_ctx, cluster_name="__nonexistent_cluster_xyz__"
    )
    assert isinstance(result, GatewayClusterEnvelope)
    assert result.items == []


# ===========================================================================
# central_get_gateway_cluster include=capacity
# ===========================================================================


async def test_get_cluster_capacity_trends(gateway_tools, live_ctx, a_cluster_name):
    result = await gateway_tools["central_get_gateway_cluster"](
        live_ctx,
        cluster_name=a_cluster_name,
        include=["capacity"],
    )
    assert isinstance(result, GatewayClusterEnvelope)
    if not result.items:
        pytest.skip("Cluster unavailable")
    capacity = result.items[0].capacity
    assert capacity is not None
    for sample in capacity:
        assert sample.capacity_type
        assert sample.timestamp


async def test_get_cluster_capacity_trends_not_found(gateway_tools, live_ctx):
    result = await gateway_tools["central_get_gateway_cluster"](
        live_ctx,
        cluster_name="__nonexistent_cluster_xyz__",
        include=["capacity"],
    )
    assert isinstance(result, GatewayClusterEnvelope)
    assert result.items == []
