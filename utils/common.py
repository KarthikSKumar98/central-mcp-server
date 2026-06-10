import asyncio
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from urllib.error import URLError
from urllib.request import urlopen

from fastmcp import Context
from pycentral.new_monitoring import MonitoringDevices

logger = logging.getLogger(__name__)

_PACKAGE_NAME = "central-mcp-server"


async def check_for_update() -> None:
    """Check PyPI for a newer version and warn to stderr if one exists.

    Runs a non-blocking background check against PyPI. If a newer version is
    available, prints a notice to stderr with upgrade instructions. Silently
    skips if the package is not installed or the network is unreachable.
    """
    try:
        current = pkg_version(_PACKAGE_NAME)

        def _fetch() -> dict:
            with urlopen(
                f"https://pypi.org/pypi/{_PACKAGE_NAME}/json", timeout=5
            ) as resp:
                return json.loads(resp.read())

        data = await asyncio.to_thread(_fetch)
        latest = data["info"]["version"]
        if latest != current:
            logger.warning(
                "[%s] Update available: %s → %s\n"
                "Check the release notes at https://github.com/KarthikSKumar98/central-mcp-server/releases/\n"
                "Run `uv cache clean %s` then restart to get the latest version.",
                _PACKAGE_NAME,
                current,
                latest,
                _PACKAGE_NAME,
            )
    except (PackageNotFoundError, URLError, KeyError, OSError):
        pass


@dataclass
class FilterField:
    api_field: str
    allowed_values: list[str] | None = None  # None = free text, list = enumerated


def build_odata_filter(pairs: list[tuple["FilterField", str]]) -> str | None:
    """Build an OData v4.0 filter string from (FilterField, value) pairs.

    - Uses 'in (...)' for comma-separated values, 'eq' for single values.
    - Raises ValueError if a value is not in FilterField.allowed_values (when defined).
    - Returns None if pairs is empty.
    """
    if not pairs:
        return None

    parts = []
    for ff, value in pairs:
        if ff.allowed_values is not None:
            submitted = [v.strip() for v in value.split(",")]
            invalid = [v for v in submitted if v not in ff.allowed_values]
            if invalid:
                raise ValueError(
                    f"Invalid value(s) {invalid} for field '{ff.api_field}'. "
                    f"Allowed: {ff.allowed_values}"
                )

        if "," in value:
            values_list = [v.strip() for v in value.split(",")]
            values_str = ", ".join(f"'{v}'" for v in values_list)
            parts.append(f"{ff.api_field} in ({values_str})")
        else:
            parts.append(f"{ff.api_field} eq '{value}'")

    return " and ".join(parts)


def lookup_inventory_device(conn, identifier: str) -> dict | None:
    """Resolve a switch identifier to a single inventory record.

    Stack switches are addressable three ways — by member serial, by conductor
    serial, or by the shared ``stackId``. The inventory API is keyed on
    ``serialNumber``, so this first filters by ``serialNumber`` and, on a miss,
    retries with ``stackId`` (covering the case where a caller passed a stack ID
    directly — which would otherwise never match a serialNumber filter).

    Args:
        conn: Active Central connection.
        identifier: A device serial number or a stack ID.

    Returns:
        The matching inventory dict, or ``None`` if neither field matches.

    """
    for field in ("serialNumber", "stackId"):
        results = MonitoringDevices.get_all_device_inventory(
            central_conn=conn, filter_str=f"{field} eq '{identifier}'"
        )
        if results:
            return results[0]
    return None


def stack_aware_serial(device: dict | None, identifier: str) -> str:
    """Return the identifier the Central APIs accept for ``device``.

    For stack switches the only universally-accepted identifier is the
    ``stackId``: the monitoring API returns 404 for non-conductor member serials,
    and the troubleshooting API returns 404 for *every* member and conductor
    serial — but both accept the stack ID. For non-stack devices (or when the
    record lacks a stack ID) ``identifier`` is returned unchanged.

    Args:
        device: Inventory record from ``lookup_inventory_device`` (or ``None``).
        identifier: The caller-supplied serial or stack ID to fall back to.

    """
    if device and device.get("deployment") == "Stack" and device.get("stackId"):
        return device["stackId"]
    return identifier


@asynccontextmanager
async def api_context(ctx: Context):
    """Acquire the API semaphore and yield the Central connection."""
    async with ctx.lifespan_context["api_semaphore"]:
        yield ctx.lifespan_context["conn"]


def build_filters(fields_map: dict[str, "FilterField"], **kwargs) -> str | None:
    """Build an OData filter string from keyword args, skipping None values."""
    pairs = [(fields_map[k], v) for k, v in kwargs.items() if v is not None]
    return build_odata_filter(pairs)


def paginated_fetch(
    central_conn,
    api_path: str,
    limit: int,
    additional_params: dict = None,
):
    """Fetch all pages from a cursor-based Central API endpoint.

    Args:
        central_conn: Central API connection object
        api_path: API endpoint path
        limit: Number of items per request
        additional_params: Additional query parameters to include

    Returns:
        list: All fetched items across all pages

    """
    total = None
    items = []
    base_params = additional_params.copy() if additional_params else {}
    next_cursor = 1
    while total is None or next_cursor is not None:
        params = {**base_params, "limit": limit, "next": next_cursor}
        response = central_conn.command(
            api_method="GET", api_path=api_path, api_params=params
        )
        if response["code"] != 200:
            raise Exception(f"API error {response['code']}: {response['msg']}")
        if total is None:
            total = response["msg"].get("total", 0)
        items.extend(response["msg"].get("items", []))
        next_cursor = response["msg"].get("next")
    return items


def format_tool_error(operation: str, error: object) -> str:
    """Return a consistent error string for tool failure responses."""
    return f"Error {operation}: {error}"


def format_rfc3339(dt: datetime) -> str:
    """Format a datetime as an RFC 3339 string with millisecond precision."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def rfc3339_to_epoch(value: str) -> int:
    """Convert an RFC 3339 timestamp string to epoch seconds (UTC)."""
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def normalize_sort_direction(sort: str | None) -> str | None:
    """Normalise sort-direction tokens in a sort expression to UPPERCASE.

    The Central switch monitoring API requires direction tokens in UPPERCASE
    (``ASC``/``DESC``).  This helper makes lowercase user input (e.g.
    ``"deviceName asc"``) work transparently by uppercasing only the direction
    token at the end of each comma-separated expression, leaving field names
    untouched.

    Examples::

        normalize_sort_direction("deviceName asc")          → "deviceName ASC"
        normalize_sort_direction("deviceName asc, model desc")
                                                            → "deviceName ASC, model DESC"
        normalize_sort_direction("deviceName")              → "deviceName"
        normalize_sort_direction(None)                      → None
        normalize_sort_direction("")                        → ""

    Args:
        sort: A sort expression string, or ``None``.

    Returns:
        The expression with any ``asc``/``desc`` direction tokens uppercased, or
        the original value when it is ``None`` or empty.

    """
    if not sort:
        return sort

    normalized_parts = []
    for expr in sort.split(","):
        tokens = expr.strip().split()
        if len(tokens) >= 2:
            # Last token is the direction; uppercase it
            tokens[-1] = tokens[-1].upper()
        normalized_parts.append(" ".join(tokens))
    return ", ".join(normalized_parts)


def compute_time_window(time_range: str) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)

    if time_range == "last_1h":
        start = now - timedelta(hours=1)

    elif time_range == "last_6h":
        start = now - timedelta(hours=6)

    elif time_range == "last_24h":
        start = now - timedelta(hours=24)

    elif time_range == "last_7d":
        start = now - timedelta(days=7)

    elif time_range == "last_30d":
        start = now - timedelta(days=30)

    elif time_range == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    elif time_range == "yesterday":
        yesterday = now - timedelta(days=1)
        start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
        now = yesterday.replace(hour=23, minute=59, second=59, microsecond=999999)

    else:
        raise ValueError("Invalid time_range")

    return start, now
