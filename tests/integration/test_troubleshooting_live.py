"""Live integration tests for central_run_network_test and central_run_show_commands.

These tests require valid Central credentials (.env or MCP env block).  They are skipped
automatically when credentials are absent (via the live_ctx fixture).

Discovery logic
---------------
The ``serial_by_family`` module-scoped fixture calls central_get_devices for each
Central device type, then uses ``resolve_family_from_serial`` (the same code the
tools use at runtime) to bucket each serial into its pycentral family string
(``aps``, ``cx``, ``aos-s``, ``gateways``).  Only the first match per family is
kept.  This avoids trusting the Central ``device_type`` field for CX-vs-AOS-S
disambiguation.
"""

import asyncio

import pytest
import pytest_asyncio
from fastmcp.exceptions import ToolError
from pycentral.troubleshooting import Troubleshooting

import tools.devices as devices_mod
import tools.troubleshooting as troubleshooting_mod
from constants import TROUBLESHOOTING_POLL_INTERVAL, TROUBLESHOOTING_POLL_MAX_ATTEMPTS
from models import CentralError, TroubleshootingResult
from tests.conftest import FakeMCP
from utils.troubleshooting import NETWORK_TEST_DISPATCH, resolve_family_from_serial

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tools():
    """Register troubleshooting tools and return the tool dict."""
    fake = FakeMCP()
    troubleshooting_mod.register(fake)
    return fake._tools


@pytest_asyncio.fixture(scope="module")
async def serial_by_family(live_ctx):
    """Discover one serial number per device family from the live Central account.

    Returns a dict like ``{"aps": "SNxxx", "cx": "SNyyy", "gateways": "SNzzz"}``.
    Families with no devices present in Central are simply absent from the dict.
    """
    conn = live_ctx.lifespan_context["conn"]

    # Register devices tools so we can call central_get_devices
    fake = FakeMCP()
    devices_mod.register(fake)
    device_tools = fake._tools

    discovered: dict[str, str] = {}

    for central_type in ("ap", "switch", "gateway"):
        devices = await device_tools["central_get_devices"](
            live_ctx, device_type=central_type
        )
        for device in devices.items:
            sn = device.serial_number
            try:
                # Returns (family, effective_serial); effective_serial is the
                # stackId for stack members, which is what the tools must call.
                family, effective_serial = await resolve_family_from_serial(conn, sn)
            except (ValueError, Exception):
                continue
            if family not in discovered:
                discovered[family] = effective_serial
            # Early-out once we have at least one of each possible family from this type
            if central_type == "ap" and "aps" in discovered:
                break
            if central_type == "gateway" and "gateways" in discovered:
                break
            if (
                central_type == "switch"
                and "cx" in discovered
                and "aos-s" in discovered
            ):
                break

    print(f"\nDiscovered serials by family: {discovered}")
    return discovered


# ---------------------------------------------------------------------------
# Parametrized network test matrix
# ---------------------------------------------------------------------------

# Build parametrize list: one entry per (test_type, family) pair in NETWORK_TEST_DISPATCH.
_NETWORK_TEST_PARAMS = sorted(NETWORK_TEST_DISPATCH.keys())  # sorted for determinism


def _network_test_kwargs(test_type: str) -> dict:
    """Return destination and optional kwargs for a given test_type."""
    if test_type in ("ping", "traceroute"):
        return {"destination": "8.8.8.8", "max_attempts": 12, "poll_interval": 5}
    if test_type in ("http", "https"):
        return {
            "destination": "https://www.google.com",
            "max_attempts": 12,
            "poll_interval": TROUBLESHOOTING_POLL_INTERVAL,
        }
    if test_type == "tcp":
        return {
            "destination": "dns.google",
            "port": 443,
            "max_attempts": 12,
            "poll_interval": TROUBLESHOOTING_POLL_INTERVAL,
        }
    if test_type == "nslookup":
        return {
            "destination": "google.com",
            "max_attempts": 12,
            "poll_interval": TROUBLESHOOTING_POLL_INTERVAL,
        }
    # Fallback
    return {
        "destination": "8.8.8.8",
        "max_attempts": 12,
        "poll_interval": TROUBLESHOOTING_POLL_INTERVAL,
    }


@pytest.mark.parametrize("test_type,family", _NETWORK_TEST_PARAMS)
async def test_network_test_matrix(
    tools, live_ctx, serial_by_family, test_type, family
):
    """Run central_run_network_test for every (test_type, family) in NETWORK_TEST_DISPATCH."""
    if family not in serial_by_family:
        pytest.skip(f"No {family} device available in this Central account")

    sn = serial_by_family[family]
    kwargs = _network_test_kwargs(test_type)

    result = await tools["central_run_network_test"](
        live_ctx, test_type=test_type, serial_number=sn, **kwargs
    )

    assert isinstance(result, TroubleshootingResult), (
        f"Expected TroubleshootingResult for ({test_type}, {family}), got: {result!r}"
    )
    assert result.serial_number == sn
    assert result.device_type == family
    assert result.status in {"COMPLETED", "FAILED", "RUNNING"}, (
        f"Unexpected status '{result.status}' for ({test_type}, {family})"
    )

    if test_type in ("ping", "traceroute"):
        # raw_output is surfaced through the output field; it may be None or a str/dict
        assert result.output is None or isinstance(result.output, (str, dict))


# ---------------------------------------------------------------------------
# Show commands tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "family",
    # Parametrize over all possible families; actual skip happens inside if not present
    ["aps", "cx", "aos-s", "gateways"],
)
async def test_run_show_commands(tools, live_ctx, serial_by_family, family):
    """Run central_run_show_commands for each available device family."""
    if family not in serial_by_family:
        pytest.skip(f"No {family} device available in this Central account")

    conn = live_ctx.lifespan_context["conn"]
    sn = serial_by_family[family]

    # Fetch the supported show-command catalog for this device
    try:
        catalog = await asyncio.to_thread(
            Troubleshooting.list_show_commands,
            central_conn=conn,
            device_type=family,
            serial_number=sn,
        )
    except Exception as exc:
        pytest.skip(f"Could not fetch show command catalog for {family}: {exc}")

    # Extract the first command string from the catalog
    first_command: str | None = None

    def _find_first_command(obj):
        if isinstance(obj, str) and obj.lower().startswith("show"):
            return obj
        if isinstance(obj, dict):
            # Try 'command' key first, then recurse into values
            if "command" in obj:
                candidate = obj["command"]
                if isinstance(candidate, str) and candidate.lower().startswith("show"):
                    return candidate
            for v in obj.values():
                result = _find_first_command(v)
                if result:
                    return result
        if isinstance(obj, list):
            for item in obj:
                result = _find_first_command(item)
                if result:
                    return result
        return None

    first_command = _find_first_command(catalog)
    if not first_command:
        pytest.skip(
            f"No 'show ...' commands found in catalog for {family}: {catalog!r}"
        )

    result = await tools["central_run_show_commands"](
        live_ctx,
        serial_number=sn,
        commands=[first_command],
        max_attempts=12,
        poll_interval=5,
    )

    assert isinstance(result, TroubleshootingResult), (
        f"Expected TroubleshootingResult for show commands on {family}, got: {result!r}"
    )
    assert result.serial_number == sn
    assert result.device_type == family
    assert result.status in {"COMPLETED", "FAILED", "RUNNING"}


async def test_run_show_commands_rejects_unsupported(tools, live_ctx, serial_by_family):
    """Calling a non-existent show command raises a structured tool error."""
    if not serial_by_family:
        pytest.skip("No devices available in this Central account")

    # Use the first available serial regardless of family
    sn = next(iter(serial_by_family.values()))

    with pytest.raises(ToolError) as exc_info:
        await tools["central_run_show_commands"](
            live_ctx,
            serial_number=sn,
            commands=["show this-command-does-not-exist-xyz"],
        )

    error = CentralError.model_validate_json(str(exc_info.value))
    assert "Unsupported commands" in error.message


# ---------------------------------------------------------------------------
# Negative-path tests
# ---------------------------------------------------------------------------


async def test_network_test_invalid_family_combo(tools, live_ctx, serial_by_family):
    """Tcp is aps-only; calling it on a CX switch must raise an informative error."""
    if "cx" not in serial_by_family:
        pytest.skip("No CX switch available in this Central account")

    cx_sn = serial_by_family["cx"]
    with pytest.raises(ToolError) as exc_info:
        await tools["central_run_network_test"](
            live_ctx,
            test_type="tcp",
            serial_number=cx_sn,
            destination="dns.google",
            port=443,
        )

    error = CentralError.model_validate_json(str(exc_info.value))
    assert "does not support tcp" in error.message


async def test_network_test_tcp_missing_port(tools, live_ctx, serial_by_family):
    """Tcp test without port must fail before hitting the network."""
    if "aps" not in serial_by_family:
        pytest.skip("No AP available in this Central account")

    ap_sn = serial_by_family["aps"]
    with pytest.raises(ToolError) as exc_info:
        await tools["central_run_network_test"](
            live_ctx,
            test_type="tcp",
            serial_number=ap_sn,
            destination="dns.google",
            # port intentionally omitted
        )

    error = CentralError.model_validate_json(str(exc_info.value))
    assert "port is required" in error.message
