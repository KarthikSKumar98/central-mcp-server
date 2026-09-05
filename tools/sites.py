import asyncio
from typing import Annotated, Literal

from fastmcp import Context, FastMCP
from pycentral.new_monitoring import MonitoringSites
from pydantic import Field

from constants import MAX_PAGE_SIZE, SITE_LIMIT
from models import SiteEnvelope, SiteSummary
from tools import READ_ONLY
from utils.common import api_context
from utils.cursor import (
    INVALID_CURSOR_MESSAGE,
    decode_cursor,
    encode_cursor,
    hash_query,
)
from utils.envelope import build_envelope, raise_central_error
from utils.sites import (
    _build_site_name_filter,
    compute_health_score,
    groups_to_map,
    process_site_health_data,
)

DEFAULT_SITE_LIMIT = SITE_LIMIT
SITE_TOOL_NAME = "central_get_sites"
SITE_HEALTH_PATH = "network-monitoring/v1/sites-health"
SITE_DEVICE_HEALTH_PATH = "network-monitoring/v1/sites-device-health"
SITE_CLIENT_HEALTH_PATH = "network-monitoring/v1/sites-client-health"

# View -> supported view-specific parameters. Limit applies to both views.
SITE_VIEW_PARAMS: dict[str, frozenset[str]] = {
    "detail": frozenset({"site_names"}),
    "summary": frozenset(),
}


def _validate_site_params(view: str, site_names: list[str] | None) -> None:
    """Reject detail-only filters that the summary route would ignore."""
    if view == "summary" and site_names is not None:
        raise ValueError("Parameter 'site_names' is supported only when view='detail'.")


def _site_summary(raw: dict) -> SiteSummary:
    """Normalize one raw get_sites item to the lightweight summary model."""
    health_obj = groups_to_map(raw.get("health", {}))
    alerts_obj = groups_to_map(raw.get("alerts", {}))
    return SiteSummary(
        name=raw["siteName"],
        site_id=raw.get("id"),
        health=compute_health_score(health_obj),
        total_devices=raw.get("devices", {}).get("count", 0),
        total_clients=raw.get("clients", {}).get("count", 0),
        critical_alerts=alerts_obj.get("critical", 0),
        total_alerts=alerts_obj.get("total", 0),
    )


def _site_offset(position: dict[str, str | int]) -> int:
    """Extract an offset cursor position for a sites request."""
    upstream_offset = position.get("upstream_offset")
    if (
        isinstance(upstream_offset, bool)
        or not isinstance(upstream_offset, int)
        or upstream_offset < 0
    ):
        raise ValueError(INVALID_CURSOR_MESSAGE)
    return upstream_offset


def _site_page(response: object) -> tuple[list[dict], int]:
    """Validate and unpack a single upstream sites page."""
    if not isinstance(response, dict):
        raise ValueError("Unexpected sites response; expected an object.")
    items = response.get("items", [])
    if not isinstance(items, list):
        raise ValueError("Unexpected sites response; expected an items list.")
    total = response.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ValueError(
            "Unexpected sites response; expected a non-negative integer total."
        )
    return items, total


def _fetch_site_health_page(
    central_conn: object,
    api_path: str,
    *,
    limit: int,
    offset: int,
    site_names: list[str] | None = None,
) -> tuple[list[dict], int]:
    """Fetch one page from an offset-based site-health endpoint."""
    site_filter = _build_site_name_filter(site_names)
    params: dict[str, object] = {}
    if site_filter:
        params["filter"] = site_filter
    params.update({"limit": limit, "offset": offset})

    response = central_conn.command(
        api_method="GET",
        api_path=api_path,
        api_params=params,
    )
    if response["code"] != 200:
        raise Exception(f"API error {response['code']}: {response['msg']}")
    return _site_page(response["msg"])


def _fetch_detail_site_page(
    central_conn: object,
    *,
    site_names: list[str] | None,
    limit: int,
    offset: int,
) -> tuple[list, int, int]:
    """Fetch one master site page and enrich only the sites on that page."""
    master_items, total = _fetch_site_health_page(
        central_conn,
        SITE_HEALTH_PATH,
        limit=limit,
        offset=offset,
        site_names=site_names,
    )
    if not master_items:
        return [], total, 0

    master_site_names = [site["siteName"] for site in master_items]
    enrichment_limit = len(master_site_names)
    device_items, _ = _fetch_site_health_page(
        central_conn,
        SITE_DEVICE_HEALTH_PATH,
        limit=enrichment_limit,
        offset=0,
        site_names=master_site_names,
    )
    client_items, _ = _fetch_site_health_page(
        central_conn,
        SITE_CLIENT_HEALTH_PATH,
        limit=enrichment_limit,
        offset=0,
        site_names=master_site_names,
    )
    sites_data = process_site_health_data(
        master_items,
        device_items,
        client_items,
    )
    items = [
        sites_data[site_name]
        for site_name in master_site_names
        if site_name in sites_data
    ]
    return items, total, len(master_items)


def register(mcp: FastMCP) -> None:
    """Register the folded site tool with the MCP server."""

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_sites(
        ctx: Context,
        view: Literal["summary", "detail"] = "detail",
        site_names: list[str] | None = None,
        limit: Annotated[int | None, Field(ge=1, le=MAX_PAGE_SIZE)] = None,
        cursor: str | None = None,
        response_format: Literal["concise", "detailed"] = "concise",
    ) -> SiteEnvelope:
        """Retrieve site summaries or detailed health records.

        Use view to choose the upstream summary/detail fetch; response_format separately shapes fetched items as concise or detailed.
        Cross-field rule: site_names applies only to view='detail'; cursor requires the identical view and filters.
        Returns SiteEnvelope. Replay next_cursor as cursor with the original limit.
        """
        try:
            _validate_site_params(view, site_names)
            query_filters = {
                "view": view,
                "site_names": site_names,
            }
            query_hash = hash_query(query_filters)
            page_size = limit if limit is not None else DEFAULT_SITE_LIMIT
            offset = 0
            if cursor is not None:
                decoded_cursor = decode_cursor(
                    cursor,
                    expected_tool=SITE_TOOL_NAME,
                    expected_query_hash=query_hash,
                )
                if decoded_cursor.page_size > MAX_PAGE_SIZE:
                    raise ValueError(INVALID_CURSOR_MESSAGE)
                if limit is not None and limit != decoded_cursor.page_size:
                    raise ValueError("limit conflicts with the cursor page_size")
                page_size = decoded_cursor.page_size
                offset = _site_offset(decoded_cursor.position)

            async with api_context(ctx) as conn:
                if view == "summary":
                    response = await asyncio.to_thread(
                        MonitoringSites.get_sites,
                        central_conn=conn,
                        limit=page_size,
                        offset=offset,
                    )
                    raw_sites, total = _site_page(response)
                    items = [_site_summary(site) for site in raw_sites]
                    upstream_count = len(raw_sites)
                else:
                    items, total, upstream_count = await asyncio.to_thread(
                        _fetch_detail_site_page,
                        conn,
                        site_names=site_names,
                        limit=page_size,
                        offset=offset,
                    )

            next_offset = offset + upstream_count
            next_cursor = None
            if next_offset < total:
                next_cursor = encode_cursor(
                    SITE_TOOL_NAME,
                    page_size,
                    {"upstream_offset": next_offset},
                    query_hash,
                )

            return build_envelope(
                SiteEnvelope,
                items,
                total=total,
                total_available=total,
                next_cursor=next_cursor,
                ceiling=page_size,
                response_format=response_format,
            )
        except Exception as exc:
            raise_central_error(exc, "retrieving sites")
