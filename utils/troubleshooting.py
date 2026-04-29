import asyncio
from typing import Any

from pycentral.new_monitoring import MonitoringDevices
from pycentral.troubleshooting import Troubleshooting

from models import TroubleshootingResult

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
    ("https", "cx"): ("initiate_https_cx_test", "get_https_test_result"),
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
    field is inspected: if it contains 'CX' (case-insensitive) the device is
    treated as CX; otherwise AOS-S is assumed.

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
        if "CX" in model.upper():
            return "cx"
        return "aos-s"
    raise ValueError(
        f"Unrecognised deviceType '{device_type}' for serial "
        f"'{device.get('serialNumber')}'. Expected ACCESS_POINT, SWITCH, or GATEWAY."
    )


def lookup_device_by_serial(conn: Any, serial_number: str) -> dict[str, Any]:
    """Fetch a single device record by serial number from the inventory API.

    Args:
        conn: Active Central connection from the lifespan context.
        serial_number: Device serial number to look up.

    Raises:
        ValueError: If the serial is not found in the inventory.

    """
    results = MonitoringDevices.get_all_device_inventory(
        central_conn=conn,
        filter_str=f"serialNumber eq '{serial_number}'",
    )
    if not results:
        raise ValueError(
            f"Device with serial '{serial_number}' not found in the Central inventory. "
            "Verify the serial number and that the device is provisioned in Central."
        )
    return results[0]


async def resolve_family_from_serial(conn: Any, serial_number: str) -> str:
    """Return the pycentral device-family string for a given serial number.

    Args:
        conn: Active Central connection from the lifespan context.
        serial_number: Device serial number to look up.

    """
    device = await asyncio.to_thread(lookup_device_by_serial, conn, serial_number)
    return resolve_device_family(device)


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
            task_id=None,
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
            return _build_result(last_response, device_family, serial_number, task_id)

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

    return _build_result(last_response, device_family, serial_number, task_id)


def _build_result(
    response: dict[str, Any],
    device_family: str,
    serial_number: str,
    task_id: str,
) -> TroubleshootingResult:
    status = (response.get("status") or "UNKNOWN").upper()
    output = response.get("result") or response.get("output") or response.get("data")
    error = response.get("error") or response.get("errorMessage")
    if not output and status != "FAILED":
        # Some tests embed output at the top level — pass the whole response as output
        output = {
            k: v
            for k, v in response.items()
            if k not in ("status", "error", "errorMessage")
        }
        if not output:
            output = None
    return TroubleshootingResult(
        task_id=task_id,
        status=status,
        device_type=device_family,
        serial_number=serial_number,
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
