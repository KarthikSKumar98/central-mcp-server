import asyncio
from typing import Annotated, Literal
from urllib.parse import quote

from fastmcp import Context, FastMCP
from pycentral.new_monitoring.wlans import WLAN
from pydantic import Field

from constants import MAX_PAGE_SIZE, TIME_RANGE, WLAN_LIMIT
from models import WlanEnvelope
from tools import READ_ONLY
from utils.common import api_context, normalize_sort_direction
from utils.cursor import (
    INVALID_CURSOR_MESSAGE,
    decode_cursor,
    decode_next_page,
    encode_cursor,
    hash_query,
)
from utils.envelope import build_envelope, raise_central_error
from utils.events import _resolve_time_window
from utils.wlans import clean_wlan_data, clean_wlan_stats_data, get_all_wlans

DEFAULT_WLAN_LIMIT = WLAN_LIMIT
WLAN_TOOL_NAME = "central_get_wlans"
WLAN_INCLUDE_PARAMS: dict[str, frozenset[str]] = {
    "throughput": frozenset({"wlan_name", "time_range", "start_time", "end_time"})
}


def _validate_wlan_params(
    include: list[str] | None,
    wlan_name: str | None,
    time_range: str | None,
    start_time: str | None,
    end_time: str | None,
) -> list[str]:
    """Validate include values and throughput-only parameters before API access."""
    if include is None:
        includes: list[str] = []
    elif not isinstance(include, list):
        raise ValueError("Parameter 'include' must be a list of include values.")
    else:
        includes = include

    for value in includes:
        if value not in WLAN_INCLUDE_PARAMS:
            valid = ", ".join(WLAN_INCLUDE_PARAMS)
            raise ValueError(
                f"Invalid include value '{value}'. Valid include values: {valid}."
            )

    wants_throughput = "throughput" in includes
    if wants_throughput and not wlan_name:
        raise ValueError("include='throughput' requires exact 'wlan_name'.")
    if not wants_throughput and (
        time_range is not None or start_time is not None or end_time is not None
    ):
        raise ValueError(
            "time_range, start_time, and end_time require include='throughput'."
        )
    return includes


def register(mcp: FastMCP) -> None:
    """Register the folded WLAN tool with the MCP server."""

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_wlans(
        ctx: Context,
        wlan_name: str | None = None,
        site_id: str | None = None,
        serial_number: str | None = None,
        sort: str | None = None,
        include: list[Literal["throughput"]] | None = None,
        time_range: TIME_RANGE | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        limit: Annotated[int | None, Field(ge=1, le=MAX_PAGE_SIZE)] = None,
        cursor: str | None = None,
        response_format: Literal["concise", "detailed"] = "concise",
    ) -> WlanEnvelope:
        """Retrieve WLANs and optional throughput for one exact SSID.

        Use for WLAN browsing or exact-name detail.
        Cross-field rule: include='throughput' requires wlan_name and enables time-window parameters; exact mode ignores limit and cursor.
        Returns WlanEnvelope; response_format selects concise or detailed items. Replay next_cursor as cursor with identical list filters and the original limit.
        """
        try:
            includes = _validate_wlan_params(
                include,
                wlan_name,
                time_range,
                start_time,
                end_time,
            )
            window = (
                _resolve_time_window(time_range or "last_1h", start_time, end_time)
                if "throughput" in includes
                else None
            )
            normalized_sort = normalize_sort_direction(sort)

            if wlan_name is None:
                list_params = {
                    "wlan_name": wlan_name,
                    "site_id": site_id,
                    "serial_number": serial_number,
                    "sort": sort,
                    "include": include,
                    "time_range": time_range,
                    "start_time": start_time,
                    "end_time": end_time,
                }
                query_hash = hash_query(list_params)
                page_size = limit if limit is not None else DEFAULT_WLAN_LIMIT
                next_page = 1
                if cursor is not None:
                    decoded_cursor = decode_cursor(
                        cursor,
                        expected_tool=WLAN_TOOL_NAME,
                        expected_query_hash=query_hash,
                    )
                    if decoded_cursor.page_size > MAX_PAGE_SIZE:
                        raise ValueError(INVALID_CURSOR_MESSAGE)
                    if limit is not None and limit != decoded_cursor.page_size:
                        raise ValueError("limit conflicts with the cursor page_size")
                    page_size = decoded_cursor.page_size
                    next_page = decode_next_page(decoded_cursor.position)

            async with api_context(ctx) as conn:
                if serial_number:
                    if wlan_name:
                        raw_items = await asyncio.to_thread(
                            get_all_wlans,
                            central_conn=conn,
                            site_id=site_id,
                            serial_number=serial_number,
                            sort=normalized_sort,
                        )
                        raw_items = [
                            item
                            for item in raw_items
                            if item.get("wlanName") == wlan_name
                            or item.get("wlan_name") == wlan_name
                        ]
                    else:
                        response = await asyncio.to_thread(
                            WLAN.get_wlans,
                            central_conn=conn,
                            site_id=site_id,
                            serial_number=serial_number,
                            sort=normalized_sort,
                            limit=page_size,
                            next_page=next_page,
                        )
                elif wlan_name:
                    api_params = {"site_id": site_id} if site_id else None
                    response = await asyncio.to_thread(
                        conn.command,
                        api_method="GET",
                        api_path=(
                            f"network-monitoring/v1/wlans/{quote(wlan_name, safe='')}"
                        ),
                        api_params=api_params,
                    )
                    if response["code"] == 404:
                        raw_items = []
                    elif response["code"] != 200:
                        raise RuntimeError(
                            f"API returned {response['code']}: {response['msg']}"
                        )
                    else:
                        payload = response.get("msg")
                        raw_items = (
                            [payload] if isinstance(payload, dict) else payload or []
                        )
                else:
                    response = await asyncio.to_thread(
                        WLAN.get_wlans,
                        central_conn=conn,
                        site_id=site_id,
                        serial_number=serial_number,
                        sort=normalized_sort,
                        limit=page_size,
                        next_page=next_page,
                    )

                if wlan_name is None:
                    if not isinstance(response, dict):
                        raise ValueError(
                            "Unexpected WLANs response; expected an object."
                        )
                    raw_items = response.get("items", [])
                    if not isinstance(raw_items, list):
                        raise ValueError(
                            "Unexpected WLANs response; expected an items list."
                        )
                    total = response.get("total")
                    upstream_next = response.get("next")
                    next_cursor = None
                    if upstream_next not in (None, ""):
                        next_cursor = encode_cursor(
                            WLAN_TOOL_NAME,
                            page_size,
                            {"upstream_next": str(upstream_next)},
                            query_hash,
                        )

                    items = clean_wlan_data(raw_items)
                    return build_envelope(
                        WlanEnvelope,
                        items,
                        total=total,
                        total_available=total,
                        next_cursor=next_cursor,
                        ceiling=page_size,
                        response_format=response_format,
                    )

                items = clean_wlan_data(raw_items)
                if items and "throughput" in includes:
                    assert wlan_name is not None and window is not None
                    start_at, end_at = window
                    response = await asyncio.to_thread(
                        conn.command,
                        api_method="GET",
                        api_path=(
                            "network-monitoring/v1/wlans/"
                            f"{quote(wlan_name, safe='')}/throughput-trends"
                        ),
                        api_params={
                            "filter": (
                                f"timestamp gt {start_at} and timestamp lt {end_at}"
                            )
                        },
                    )
                    if response["code"] != 200:
                        raise RuntimeError(
                            f"API returned {response['code']}: {response['msg']}"
                        )
                    samples = clean_wlan_stats_data(response.get("msg"))
                    for item in items:
                        item.throughput = samples

            return build_envelope(
                WlanEnvelope,
                items,
                total=len(items),
                ceiling=len(items),
                response_format=response_format,
            )
        except Exception as exc:
            raise_central_error(exc, "retrieving WLANs")
