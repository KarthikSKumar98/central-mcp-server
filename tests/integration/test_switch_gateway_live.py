"""Live smoke tests for switch, gateway, and cluster monitoring tools.

Mirrors the structure of test_ap_monitoring_live.py: module-scoped FakeMCP
registration, dynamic entity discovery (list first, pick first result) with
known dev-account entities as fallbacks, and tolerant assertions that accept
either a typed model/list result or a string message.

Covered tools (8):
- central_get_switches, central_get_switch_details, central_get_switch_trends
- central_get_gateways, central_get_gateway_details, central_get_gateway_trends,
  central_get_gateway_cluster, central_get_cluster_capacity_trends

Known live quirks tolerated:
- vsx include 404s on non-VSX platforms (surfaces as {"error": ...}).
- wan/vpn-availability return -1 without configured probes.
- tunnel/uplink scopes may legitimately have no data on some gateways.
"""

import pytest

import tools.gateway_monitoring as gw_mod
import tools.switch_monitoring as sw_mod
from models import (
    Gateway,
    GatewayCluster,
    GatewayDetail,
    Switch,
    SwitchDetail,
    TrendSample,
)
from tests.conftest import FakeMCP

pytestmark = pytest.mark.integration

# Known dev-account entities (fallbacks when discovery yields nothing).
FALLBACK_SWITCHES = ["FCW2026D0KV", "SG34L5002Y", "SG34L5006M", "SG16KRR027"]
FALLBACK_GATEWAYS = ["DL0006948", "DL0006931", "TWSTKYH00D"]
FALLBACK_CLUSTERS = ["auto_group_168", "CP-LHR-MBGW-CLUSTER"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def switch_tools():
    fake = FakeMCP()
    sw_mod.register(fake)
    return fake._tools


@pytest.fixture(scope="module")
def gateway_tools():
    fake = FakeMCP()
    gw_mod.register(fake)
    return fake._tools


@pytest.fixture(scope="module")
async def a_switch_serial(switch_tools, live_ctx):
    """Serial of the first discoverable switch (online preferred), else a fallback."""
    switches = await switch_tools["central_get_switches"](live_ctx, status="Online")
    if isinstance(switches, list) and switches:
        return switches[0].serial_number
    switches = await switch_tools["central_get_switches"](live_ctx)
    if isinstance(switches, list) and switches:
        return switches[0].serial_number
    return FALLBACK_SWITCHES[0]


@pytest.fixture(scope="module")
async def a_gateway_serial(gateway_tools, live_ctx):
    """Serial of the first discoverable gateway (online preferred), else a fallback."""
    gateways = await gateway_tools["central_get_gateways"](live_ctx, status="Online")
    if isinstance(gateways, list) and gateways:
        return gateways[0].serial_number
    gateways = await gateway_tools["central_get_gateways"](live_ctx)
    if isinstance(gateways, list) and gateways:
        return gateways[0].serial_number
    return FALLBACK_GATEWAYS[0]


@pytest.fixture(scope="module")
async def a_cluster_name(gateway_tools, live_ctx):
    """Name of the first discoverable cluster, else a fallback.

    Discovers via the cluster_name embedded on a gateway list item.
    """
    gateways = await gateway_tools["central_get_gateways"](live_ctx)
    if isinstance(gateways, list):
        for gw in gateways:
            if gw.cluster_name:
                return gw.cluster_name
    return FALLBACK_CLUSTERS[0]


# ===========================================================================
# central_get_switches
# ===========================================================================


async def test_get_switches_no_filter(switch_tools, live_ctx):
    result = await switch_tools["central_get_switches"](live_ctx)
    if isinstance(result, str):
        assert "No switches found" in result
        return
    assert isinstance(result, list)
    assert all(isinstance(sw, Switch) for sw in result)
    assert all(sw.serial_number for sw in result)


async def test_get_switches_online_filter(switch_tools, live_ctx):
    result = await switch_tools["central_get_switches"](live_ctx, status="Online")
    if isinstance(result, str):
        assert "No switches found" in result
        return
    assert isinstance(result, list)
    assert all(sw.status == "Online" for sw in result)


async def test_get_switches_by_model_filter(switch_tools, live_ctx):
    switches = await switch_tools["central_get_switches"](live_ctx)
    if isinstance(switches, str) or not switches:
        pytest.skip("No switches available")
    model = switches[0].model
    if not model:
        pytest.skip("First switch has no model field")
    result = await switch_tools["central_get_switches"](live_ctx, model=model)
    assert isinstance(result, list)
    assert all(sw.model == model for sw in result)


# ===========================================================================
# central_get_switch_details
# ===========================================================================


async def test_get_switch_details_base(switch_tools, live_ctx, a_switch_serial):
    result = await switch_tools["central_get_switch_details"](
        live_ctx, serial_number=a_switch_serial
    )
    # Tolerate not-found string for fallback serials no longer in the account.
    if isinstance(result, str):
        assert a_switch_serial in result or "No switch found" in result
        return
    assert isinstance(result, SwitchDetail)
    assert result.serial_number == a_switch_serial


async def test_get_switch_details_with_interfaces_and_hardware(
    switch_tools, live_ctx, a_switch_serial
):
    result = await switch_tools["central_get_switch_details"](
        live_ctx,
        serial_number=a_switch_serial,
        include=["interfaces", "hardware"],
    )
    if isinstance(result, str):
        pytest.skip(f"switch details unavailable: {result}")
    assert isinstance(result, SwitchDetail)
    serialized = result.model_dump()
    # include keys are additive; they should be present (possibly empty/error).
    assert "interfaces" in serialized or "hardware" in serialized


async def test_get_switch_details_with_vsx_tolerates_error(
    switch_tools, live_ctx, a_switch_serial
):
    """Vsx include 404s on non-VSX platforms — must surface as {error: ...}, not raise."""
    result = await switch_tools["central_get_switch_details"](
        live_ctx, serial_number=a_switch_serial, include=["vsx"]
    )
    if isinstance(result, str):
        pytest.skip(f"switch details unavailable: {result}")
    assert isinstance(result, SwitchDetail)
    serialized = result.model_dump()
    if "vsx" in serialized and isinstance(serialized["vsx"], dict):
        # Either real VSX data or an isolated error dict — both acceptable.
        assert "error" in serialized["vsx"] or serialized["vsx"]


async def test_get_switch_details_not_found(switch_tools, live_ctx):
    result = await switch_tools["central_get_switch_details"](
        live_ctx, serial_number="__nonexistent_switch_xyz__"
    )
    assert isinstance(result, str)


# ===========================================================================
# central_get_switch_trends
# ===========================================================================


async def test_get_switch_trends_hardware(switch_tools, live_ctx, a_switch_serial):
    result = await switch_tools["central_get_switch_trends"](
        live_ctx, serial_number=a_switch_serial, scope="hardware"
    )
    assert isinstance(result, (list, str))
    if isinstance(result, list):
        assert all(isinstance(s, TrendSample) for s in result)
        assert all(s.timestamp for s in result)


async def test_get_switch_trends_interface(switch_tools, live_ctx, a_switch_serial):
    result = await switch_tools["central_get_switch_trends"](
        live_ctx, serial_number=a_switch_serial, scope="interface"
    )
    # interface scope may legitimately have no data on some switches.
    assert isinstance(result, (list, str))
    if isinstance(result, list):
        assert all(isinstance(s, TrendSample) for s in result)


# ===========================================================================
# central_get_gateways
# ===========================================================================


async def test_get_gateways_no_filter(gateway_tools, live_ctx):
    result = await gateway_tools["central_get_gateways"](live_ctx)
    if isinstance(result, str):
        assert "No gateways found" in result
        return
    assert isinstance(result, list)
    assert all(isinstance(gw, Gateway) for gw in result)
    assert all(gw.serial_number for gw in result)


async def test_get_gateways_online_filter(gateway_tools, live_ctx):
    result = await gateway_tools["central_get_gateways"](live_ctx, status="Online")
    if isinstance(result, str):
        assert "No gateways found" in result
        return
    assert isinstance(result, list)
    assert all(gw.status == "Online" for gw in result)


async def test_get_gateways_by_serial_filter(gateway_tools, live_ctx):
    gateways = await gateway_tools["central_get_gateways"](live_ctx)
    if isinstance(gateways, str) or not gateways:
        pytest.skip("No gateways available")
    serial = gateways[0].serial_number
    result = await gateway_tools["central_get_gateways"](
        live_ctx, serial_number=serial
    )
    assert isinstance(result, list)
    assert all(gw.serial_number == serial for gw in result)


# ===========================================================================
# central_get_gateway_details
# ===========================================================================


async def test_get_gateway_details_base(gateway_tools, live_ctx, a_gateway_serial):
    result = await gateway_tools["central_get_gateway_details"](
        live_ctx, serial_number=a_gateway_serial
    )
    if isinstance(result, str):
        assert a_gateway_serial in result or "No gateway found" in result
        return
    assert isinstance(result, GatewayDetail)
    assert result.serial_number == a_gateway_serial


async def test_get_gateway_details_with_includes(
    gateway_tools, live_ctx, a_gateway_serial
):
    result = await gateway_tools["central_get_gateway_details"](
        live_ctx,
        serial_number=a_gateway_serial,
        include=["ports", "tunnels", "uplinks", "vlans"],
    )
    if isinstance(result, str):
        pytest.skip(f"gateway details unavailable: {result}")
    assert isinstance(result, GatewayDetail)
    # All include fields exist on the model (each may be None / empty list).
    for attr in ("ports", "tunnels", "uplinks", "vlans"):
        assert hasattr(result, attr)


async def test_get_gateway_details_not_found(gateway_tools, live_ctx):
    result = await gateway_tools["central_get_gateway_details"](
        live_ctx, serial_number="__nonexistent_gateway_xyz__"
    )
    assert isinstance(result, str)


# ===========================================================================
# central_get_gateway_trends
# ===========================================================================


async def test_get_gateway_trends_cpu(gateway_tools, live_ctx, a_gateway_serial):
    result = await gateway_tools["central_get_gateway_trends"](
        live_ctx, serial_number=a_gateway_serial, metric="cpu-utilization"
    )
    assert isinstance(result, (list, str))
    if isinstance(result, list):
        assert all(isinstance(s, TrendSample) for s in result)
        assert all(s.timestamp for s in result)


async def test_get_gateway_trends_wan_availability_tolerates_minus_one(
    gateway_tools, live_ctx, a_gateway_serial
):
    """wan-availability returns -1 without probes — pass-through, no error."""
    result = await gateway_tools["central_get_gateway_trends"](
        live_ctx, serial_number=a_gateway_serial, metric="wan-availability"
    )
    assert isinstance(result, (list, str))


async def test_get_gateway_trends_temperature(
    gateway_tools, live_ctx, a_gateway_serial
):
    result = await gateway_tools["central_get_gateway_trends"](
        live_ctx, serial_number=a_gateway_serial, metric="hardware-temperature"
    )
    assert isinstance(result, (list, str))
    if isinstance(result, list):
        assert all(isinstance(s, TrendSample) for s in result)


async def test_get_gateway_trends_port_scope(
    gateway_tools, live_ctx, a_gateway_serial
):
    """Discover a port_number from details, then query port-scope trends."""
    details = await gateway_tools["central_get_gateway_details"](
        live_ctx, serial_number=a_gateway_serial, include=["ports"]
    )
    if not isinstance(details, GatewayDetail) or not details.ports:
        pytest.skip("No ports found for gateway")
    port_number = details.ports[0].port_number
    if port_number is None:
        pytest.skip("Port has no port_number field")
    result = await gateway_tools["central_get_gateway_trends"](
        live_ctx,
        serial_number=a_gateway_serial,
        metric="throughput",
        scope="port",
        port_number=str(port_number),
    )
    # tunnel/uplink/port scopes may have no data — tolerate list or string.
    assert isinstance(result, (list, str))


# ===========================================================================
# central_get_gateway_cluster
# ===========================================================================


async def test_get_gateway_cluster(gateway_tools, live_ctx, a_cluster_name):
    result = await gateway_tools["central_get_gateway_cluster"](
        live_ctx, cluster_name=a_cluster_name
    )
    if isinstance(result, str):
        assert a_cluster_name in result or "No cluster found" in result
        return
    assert isinstance(result, GatewayCluster)
    assert result.cluster_name == a_cluster_name
    assert isinstance(result.members, list)
    if result.members:
        assert result.members[0].serial_number


async def test_get_gateway_cluster_with_includes(
    gateway_tools, live_ctx, a_cluster_name
):
    result = await gateway_tools["central_get_gateway_cluster"](
        live_ctx,
        cluster_name=a_cluster_name,
        include=["tunnels", "vlan_mismatch", "connectivity"],
    )
    if isinstance(result, str):
        pytest.skip(f"cluster unavailable: {result}")
    assert isinstance(result, GatewayCluster)
    for attr in ("tunnels", "vlan_mismatch", "connectivity"):
        assert hasattr(result, attr)


async def test_get_gateway_cluster_not_found(gateway_tools, live_ctx):
    result = await gateway_tools["central_get_gateway_cluster"](
        live_ctx, cluster_name="__nonexistent_cluster_xyz__"
    )
    assert isinstance(result, str)


# ===========================================================================
# central_get_cluster_capacity_trends
# ===========================================================================


async def test_get_cluster_capacity_trends(gateway_tools, live_ctx, a_cluster_name):
    result = await gateway_tools["central_get_cluster_capacity_trends"](
        live_ctx, cluster_name=a_cluster_name
    )
    assert isinstance(result, (list, str))
    if isinstance(result, list):
        for sample in result:
            assert "capacity_type" in sample
            assert "timestamp" in sample


async def test_get_cluster_capacity_trends_not_found(gateway_tools, live_ctx):
    result = await gateway_tools["central_get_cluster_capacity_trends"](
        live_ctx, cluster_name="__nonexistent_cluster_xyz__"
    )
    assert isinstance(result, (list, str))
