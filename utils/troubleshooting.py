import asyncio
import re
from typing import Any

from pycentral.new_monitoring.gateways import MonitoringGateways
from pycentral.new_monitoring.switches import MonitoringSwitches
from pycentral.troubleshooting import Troubleshooting

from models import TroubleshootingResult
from utils.common import lookup_inventory_device, stack_aware_serial

SWITCH_OS_MAPPING = {"cx": [6, 8, 9, 1, 4], "aos-s": [2, 3, 5]}

# Maps (test_type, device_family) -> (initiate_method_name, get_result_method_name).
# String names are used so that test patches on Troubleshooting attributes are picked up
# at call time via getattr, rather than being bypassed by pre-stored function references.
NETWORK_TEST_DISPATCH: dict[tuple[str, str], tuple[str, str]] = {
    # ping
    ("ping", "aps"): ("initiate_ping_aps_test", "get_ping_test_result"),
    ("ping", "cx"): ("initiate_ping_cx_test", "get_ping_test_result"),
    ("ping", "aos-s"): ("initiate_ping_aoss_test", "get_ping_test_result"),
    ("ping", "gateways"): ("initiate_ping_gateways_test", "get_ping_test_result"),
    # traceroute
    ("traceroute", "aps"): (
        "initiate_traceroute_aps_test",
        "get_traceroute_test_result",
    ),
    ("traceroute", "cx"): ("initiate_traceroute_cx_test", "get_traceroute_test_result"),
    ("traceroute", "aos-s"): (
        "initiate_traceroute_aoss_test",
        "get_traceroute_test_result",
    ),
    ("traceroute", "gateways"): (
        "initiate_traceroute_gateways_test",
        "get_traceroute_test_result",
    ),
    # http — single initiate method that takes device_type as a param
    ("http", "aps"): ("initiate_http_test", "get_http_test_result"),
    ("http", "cx"): ("initiate_http_test", "get_http_test_result"),
    ("http", "gateways"): ("initiate_http_test", "get_http_test_result"),
    # https
    ("https", "aps"): ("initiate_https_aps_test", "get_https_test_result"),
    # CX HTTPS posts to /http with protocol=HTTPS; result must be polled from /http/async-operations/
    ("https", "cx"): ("initiate_https_cx_test", "get_http_test_result"),
    ("https", "gateways"): ("initiate_https_gateways_test", "get_https_test_result"),
    # tcp — aps only per Central support matrix
    ("tcp", "aps"): ("initiate_tcp_test", "get_tcp_test_result"),
    # nslookup — aps only per Central support matrix
    ("nslookup", "aps"): ("initiate_nslookup_test", "get_nslookup_test_result"),
}

# Human-readable device families that support each test, used in error messages.
_SUPPORTED_FAMILIES: dict[str, list[str]] = {}
for _key in NETWORK_TEST_DISPATCH:
    _test, _fam = _key
    _SUPPORTED_FAMILIES.setdefault(_test, []).append(_fam)


def resolve_device_family(device: dict[str, Any]) -> str:
    """Map a raw inventory device record to a pycentral device-family string.

    Returns one of 'aps', 'cx', 'aos-s', or 'gateways'.  For switches the model
    field is inspected by its leading digit: CX models start with 1, 4, 6, 8, or 9;
    AOS-S models start with 2, 3, or 5.  The Central inventory API returns bare
    model numbers (e.g. "6300M", "2930F") without a vendor-prefix.

    Args:
        device: Raw dict from MonitoringDevices.get_all_device_inventory.

    Raises:
        ValueError: If deviceType is missing or unrecognised.

    """
    device_type = (device.get("deviceType") or "").upper()
    if device_type == "ACCESS_POINT":
        return "aps"
    if device_type == "GATEWAY":
        return "gateways"
    if device_type == "SWITCH":
        model = device.get("model") or ""
        # Strip any leading alphabetic vendor prefix (e.g. "CX-" in "CX-6300F",
        # "AS-" in "AS-2930M") so that bare digit comparison works regardless of
        # whether the monitoring or inventory API returned the model string.
        bare = re.sub(r"^[A-Za-z]+-?", "", model)
        try:
            leading_digit = int(bare[0]) if bare else None
        except (ValueError, IndexError):
            leading_digit = None
        if leading_digit is not None:
            if leading_digit in SWITCH_OS_MAPPING["cx"]:
                return "cx"
            if leading_digit in SWITCH_OS_MAPPING["aos-s"]:
                return "aos-s"
    raise ValueError(
        f"Unrecognised deviceType '{device_type}' for serial "
        f"'{device.get('serialNumber')}'. Expected ACCESS_POINT, SWITCH, or GATEWAY."
    )


def lookup_device_by_serial(conn: Any, serial_number: str) -> dict[str, Any]:
    """Fetch a single device record by serial number (or stackId) from the inventory API.

    Delegates to ``lookup_inventory_device`` which first tries ``serialNumber`` and
    falls back to ``stackId``, covering the case where a stack ID is passed directly.

    Args:
        conn: Active Central connection from the lifespan context.
        serial_number: Device serial number or stack ID to look up.

    Raises:
        ValueError: If the identifier is not found in the inventory.

    """
    device = lookup_inventory_device(conn, serial_number)
    if device is None:
        raise ValueError(
            f"Device with serial '{serial_number}' not found in the Central inventory. "
            "Verify the serial number and that the device is provisioned in Central."
        )
    return device


async def resolve_family_from_serial(conn: Any, serial_number: str) -> tuple[str, str]:
    """Return ``(family, effective_serial)`` for a given serial number or stack ID.

    For stack switches the Central Troubleshooting and monitoring APIs only accept the
    ``stackId`` — not any member or conductor serial.  ``effective_serial`` is the
    ``stackId`` when the device is a stack member/conductor, otherwise it equals
    ``serial_number`` unchanged.

    Args:
        conn: Active Central connection from the lifespan context.
        serial_number: Device serial number or stack ID to look up.

    Returns:
        Tuple of (pycentral device-family string, effective serial for API calls).

    Raises:
        ValueError: If the device is not found or is currently offline.

    """
    device = await asyncio.to_thread(lookup_device_by_serial, conn, serial_number)
    if device.get("status") != "ONLINE":
        raise ValueError(
            f"Device with serial '{serial_number}' is currently offline. "
            "Troubleshooting tests require the device to be online."
        )
    family = resolve_device_family(device)
    effective_serial = stack_aware_serial(device, serial_number)
    return family, effective_serial


def _extract_task_id(response: Any) -> str | None:
    """Pull task_id out of whatever pycentral returns from an initiate call."""
    if isinstance(response, dict):
        location = response.get("location", "")
        if location:
            return location.split("/")[-1]
        return response.get("task_id") or response.get("taskId")
    return None


async def run_async_test(
    conn: Any,
    initiate_name: str,
    get_result_name: str,
    device_family: str,
    serial_number: str,
    max_attempts: int,
    poll_interval: int,
    **initiate_kwargs: Any,
) -> TroubleshootingResult:
    """Run an async Central troubleshooting task with custom polling.

    Resolves pycentral methods by name at call time so test patches are effective.
    Polls get_result_name up to max_attempts times.  If the task is still
    INITIATED or RUNNING after all attempts, one extra sleep + fetch is performed
    before returning.

    Args:
        conn: Active Central connection.
        initiate_name: Name of the pycentral Troubleshooting initiate method.
        get_result_name: Name of the pycentral Troubleshooting get-result method.
        device_family: Resolved device family string (e.g. 'aps').
        serial_number: Device serial number.
        max_attempts: Maximum polling iterations.
        poll_interval: Seconds between polls.
        **initiate_kwargs: Extra keyword arguments forwarded to the initiate method.

    """
    initiate_fn = getattr(Troubleshooting, initiate_name)
    get_result_fn = getattr(Troubleshooting, get_result_name)

    initiate_response = await asyncio.to_thread(
        initiate_fn,
        central_conn=conn,
        serial_number=serial_number,
        **initiate_kwargs,
    )
    task_id = _extract_task_id(initiate_response)

    if not task_id:
        return TroubleshootingResult(
            status="FAILED",
            device_type=device_family,
            serial_number=serial_number,
            output=None,
            error=f"Task did not start — no task_id in response: {initiate_response}",
        )

    # Poll up to max_attempts times
    last_response: dict[str, Any] = {}
    for _ in range(max_attempts):
        await asyncio.sleep(poll_interval)
        last_response = await asyncio.to_thread(
            get_result_fn,
            central_conn=conn,
            task_id=task_id,
            device_type=device_family,
            serial_number=serial_number,
        )
        status = (last_response.get("status") or "").upper()
        if status in ("COMPLETED", "FAILED"):
            return _build_result(last_response, device_family, serial_number)

    # Extra wait if task is still running after all attempts
    status = (last_response.get("status") or "").upper()
    if status not in ("COMPLETED", "FAILED"):
        await asyncio.sleep(poll_interval)
        last_response = await asyncio.to_thread(
            get_result_fn,
            central_conn=conn,
            task_id=task_id,
            device_type=device_family,
            serial_number=serial_number,
        )

    return _build_result(last_response, device_family, serial_number)


def _build_result(
    response: dict[str, Any],
    device_family: str,
    serial_number: str,
) -> TroubleshootingResult:
    status = (response.get("status") or "UNKNOWN").upper()
    raw_output = response.get("rawOutput") or response.get("raw_output")
    output = response.get("result") or response.get("output") or response.get("data")
    error = response.get("error") or response.get("errorMessage")
    if not output and status != "FAILED":
        # Some tests embed output at the top level — pass the whole response as output
        output = {
            k: v
            for k, v in response.items()
            if k not in ("status", "error", "errorMessage", "rawOutput", "raw_output")
        }
        if not output:
            output = None
    return TroubleshootingResult(
        status=status,
        device_type=device_family,
        serial_number=serial_number,
        raw_output=str(raw_output) if raw_output else None,
        output=output,
        error=str(error) if error else None,
    )


def get_supported_families(test_type: str) -> list[str]:
    """Return the device families that support the given test_type."""
    return _SUPPORTED_FAMILIES.get(test_type, [])


def validate_show_commands_against_catalog(
    requested: list[str],
    catalog: Any,
) -> list[str]:
    """Return unmatched commands given a catalog response from list_show_commands.

    The catalog may be a list of strings, a list of dicts with a 'command' key,
    or a nested structure.  Matching is case-insensitive and whitespace-normalised.

    Args:
        requested: Commands the user wants to run.
        catalog: Raw response from Troubleshooting.list_show_commands.

    Returns:
        List of requested commands that did not match any catalog entry.
        Empty list means all commands are supported.

    """
    supported: set[str] = set()

    def _collect(obj: Any) -> None:
        if isinstance(obj, str):
            supported.add(" ".join(obj.lower().split()))
        elif isinstance(obj, dict):
            for v in obj.values():
                _collect(v)
        elif isinstance(obj, list):
            for item in obj:
                _collect(item)

    _collect(catalog)

    unmatched = []
    for cmd in requested:
        normalised = " ".join(cmd.lower().split())
        if normalised not in supported:
            unmatched.append(cmd)
    return unmatched


async def fetch_device_interfaces(
    conn: Any, family: str, serial_number: str
) -> list[dict]:
    """Fetch interface/port list for a switch (CX/AOS-S) or gateway.

    Returns a normalised list of dicts. Each dict has at minimum a 'name' key.
    Switch interfaces come from network-monitoring/v1/switches/{serial}/interfaces.
    Gateway ports come from network-monitoring/v1alpha1/gateways/{serial}/ports.

    Raises:
        ValueError: If family is not cx, aos-s, or gateways.
        Exception: Propagated from pycentral on API errors.

    """
    if family in ("cx", "aos-s"):
        response = await asyncio.to_thread(
            MonitoringSwitches.get_switch_interfaces,
            central_conn=conn,
            serial_number=serial_number,
        )
    elif family == "gateways":
        response = await asyncio.to_thread(
            MonitoringGateways.get_all_gateway_ports,
            central_conn=conn,
            serial_number=serial_number,
        )
    else:
        raise ValueError(f"fetch_device_interfaces: unsupported family '{family}'")

    if isinstance(response, list):
        return response
    if isinstance(response, dict):
        for key in ("items", "data", "ports", "interfaces", "result"):
            if key in response and isinstance(response[key], list):
                return response[key]
    return []


def format_port_speed(value) -> str:
    """Convert raw Mbps speed value to human-readable string (e.g. 2500 → '2.5G').

    Non-numeric strings (e.g. 'Auto') are returned as-is. None returns 'unknown'.
    """
    if value is None:
        return "unknown"
    try:
        mbps = int(value)
    except (TypeError, ValueError):
        return str(value)
    if mbps >= 1000:
        g = mbps / 1000
        return f"{g:g}G"
    return f"{mbps}M"


def _normalize_port_name(name: str) -> str:
    """Normalize a port name for fuzzy matching.

    Strips whitespace, lowercases, and removes a leading interface-type prefix
    (letters before the first digit, e.g. 'ge', 'tenge', 'xgige').

    Examples:
        "GE 0/0/0"  -> "0/0/0"
        "ge0/0/0"   -> "0/0/0"
        "0/0/0"     -> "0/0/0"
        "1/1/1"     -> "1/1/1"  (no prefix to strip)

    """
    s = "".join(name.split()).lower()
    i = 0
    while i < len(s) and s[i].isalpha():
        i += 1
    return s[i:] or s  # if all letters, fall back to original


def select_interfaces_for_ports(
    interfaces: list[dict], ports: list[str]
) -> tuple[list[dict], list[str]]:
    """Return (matched_interface_dicts, unknown_port_names).

    Matches by the 'name' field of each interface dict. Case-insensitive and
    whitespace-tolerant. For gateway interfaces whose names include an
    interface-type prefix (e.g. "GE 0/0/0"), also registers a normalized key
    (stripping the prefix) so users may pass "0/0/0", "GE0/0/0", or
    "GE 0/0/0" interchangeably.

    Args:
        interfaces: Interface list from fetch_device_interfaces.
        ports: Port names the user wants to bounce.

    Returns:
        Tuple of (list of matched dicts, list of port names not found).

    """
    iface_by_name: dict[str, dict] = {}
    for iface in interfaces:
        raw = str(iface.get("name", ""))
        # Always register the raw (lowercased) form.
        iface_by_name[raw.lower()] = iface
        # Also register the normalized form (prefix stripped) so that gateway
        # port names like "GE 0/0/0" match user input "0/0/0" or "ge0/0/0".
        iface_by_name.setdefault(_normalize_port_name(raw), iface)

    matched: list[dict] = []
    unknown: list[str] = []
    for port in ports:
        iface = iface_by_name.get(port.lower()) or iface_by_name.get(
            _normalize_port_name(port)
        )
        if iface is not None:
            matched.append(iface)
        else:
            unknown.append(port)
    return matched, unknown
