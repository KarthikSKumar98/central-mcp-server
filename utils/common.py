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


@asynccontextmanager
async def api_context(ctx: Context):
    """Acquire the API semaphore and yield the Central connection."""
    async with ctx.lifespan_context["api_semaphore"]:
        yield ctx.lifespan_context["conn"]


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


def format_tool_error(operation: str, error: Exception) -> str:
    """Return a consistent error string for tool failure responses."""
    return f"Error {operation}: {error}"


def format_rfc3339(dt: datetime) -> str:
    """Format a datetime as an RFC 3339 string with millisecond precision."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


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
