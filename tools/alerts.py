import asyncio
from typing import Annotated, Literal

from fastmcp import Context, FastMCP
from pydantic import Field

from constants import ALERT_LIMIT, MAX_PAGE_SIZE
from models import AlertEnvelope
from tools import READ_ONLY
from utils.alerts import clean_alert_data
from utils.common import FilterField, api_context, build_filters
from utils.cursor import (
    INVALID_CURSOR_MESSAGE,
    decode_cursor,
    encode_cursor,
    hash_query,
)
from utils.envelope import build_envelope, raise_central_error

ALERTS_TOOL_NAME = "central_get_alerts"

ALERT_FILTER_FIELDS: dict[str, FilterField] = {
    "status": FilterField("status"),
    "device_type": FilterField("deviceType"),
    "category": FilterField("category"),
    "site_id": FilterField("siteId"),
}


def register(mcp: FastMCP) -> None:
    """Register the alert tool with the MCP server."""

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_alerts(
        ctx: Context,
        site_id: str,
        status: Literal["Active", "Cleared", "Deferred"] | None = "Active",
        device_type: Literal["Access Point", "Gateway", "Switch", "Bridge"]
        | None = None,
        category: Literal[
            "Clients", "System", "LAN", "WLAN", "WAN", "Cluster", "Routing", "Security"
        ]
        | None = None,
        sort: str = "severity desc",
        limit: Annotated[int, Field(ge=1, le=MAX_PAGE_SIZE)] = ALERT_LIMIT,
        cursor: str | None = None,
        response_format: Literal["concise", "detailed"] = "concise",
    ) -> AlertEnvelope:
        """Retrieve a severity-sorted alert page for one site.

        Use after central_get_sites identifies the site; Active alerts are the default.
        Cross-field rule: filters combine, and cursor requires the identical query and original limit.
        Returns AlertEnvelope; response_format selects concise or detailed items. Replay next_cursor as cursor to continue.
        """
        try:
            query_filters = {
                "status": status,
                "device_type": device_type,
                "category": category,
                "site_id": site_id,
                "sort": sort,
            }
            query_hash = hash_query(query_filters)
            page_size = limit
            upstream_next = None
            if cursor is not None:
                decoded_cursor = decode_cursor(
                    cursor,
                    expected_tool=ALERTS_TOOL_NAME,
                    expected_query_hash=query_hash,
                )
                if decoded_cursor.page_size > MAX_PAGE_SIZE:
                    raise ValueError(INVALID_CURSOR_MESSAGE)
                page_size = decoded_cursor.page_size
                upstream_next = decoded_cursor.position.get("upstream_next")
                if not isinstance(upstream_next, str) or not upstream_next:
                    raise ValueError(INVALID_CURSOR_MESSAGE)

            async with api_context(ctx) as conn:
                filter_str = build_filters(
                    ALERT_FILTER_FIELDS,
                    status=status,
                    device_type=device_type,
                    category=category,
                    site_id=site_id,
                )
                query_params: dict[str, object] = {
                    "sort": sort,
                    "limit": page_size,
                }
                if filter_str:
                    query_params["filter"] = filter_str
                if upstream_next is not None:
                    query_params["next"] = upstream_next

                response = await asyncio.to_thread(
                    conn.command,
                    api_method="GET",
                    api_path="network-notifications/v1/alerts",
                    api_params=query_params,
                )
                if response.get("code") != 200:
                    raise RuntimeError(
                        f"alerts API returned {response.get('code')}: {response.get('msg')}"
                    )
                payload = response.get("msg")
                if not isinstance(payload, dict):
                    raise ValueError(
                        "Unexpected alerts response; expected an object payload."
                    )
                raw_items = payload.get("items", [])
                if not isinstance(raw_items, list):
                    raise ValueError(
                        "Unexpected alerts response; expected an items list."
                    )
                items = clean_alert_data(raw_items)

            response_next_value = payload.get("next")
            response_next = (
                str(response_next_value)
                if not isinstance(response_next_value, bool)
                and isinstance(response_next_value, (str, int))
                else None
            )
            if not response_next:
                response_next = None

            next_cursor = None
            if response_next is not None:
                next_cursor = encode_cursor(
                    ALERTS_TOOL_NAME,
                    page_size,
                    {"upstream_next": response_next},
                    query_hash,
                )

            return build_envelope(
                AlertEnvelope,
                items,
                total=payload.get("total", 0),
                next_cursor=next_cursor,
                ceiling=page_size,
                response_format=response_format,
            )
        except Exception as exc:
            raise_central_error(exc, "retrieving alerts")
