import asyncio
from typing import Annotated, Literal

from fastmcp import Context, FastMCP
from pycentral.new_monitoring.clients import Clients
from pydantic import Field

from constants import MAX_PAGE_SIZE
from models import ClientEnvelope
from tools import READ_ONLY
from utils.clients import clean_client_data
from utils.common import FilterField, api_context, build_filters
from utils.cursor import (
    INVALID_CURSOR_MESSAGE,
    decode_cursor,
    decode_next_page,
    encode_cursor,
    hash_query,
)
from utils.envelope import build_envelope, raise_central_error

DEFAULT_CLIENT_LIMIT = 100
MISSING_CLIENT_RESPONSE = "Resource not found for the given input."
CLIENT_TOOL_NAME = "central_get_clients"

# Mode -> supported caller parameters. The exact lookup path deliberately rejects
# list filters before opening a Central API connection so no argument is ignored.
CLIENT_MODE_PARAMS: dict[str, frozenset[str]] = {
    "list": frozenset(
        {
            "site_id",
            "site_name",
            "serial_number",
            "connection_type",
            "status",
            "wlan_name",
            "vlan_id",
            "tunnel_type",
            "start_query_time",
            "end_query_time",
        }
    ),
    "exact": frozenset({"mac_address"}),
}

# API field name mappings — Literal annotations in the function signature are the
# source of truth for allowed values; Pydantic validates them before the tool body.
CLIENT_FILTER_FIELDS: dict[str, FilterField] = {
    "status": FilterField("status"),
    "connection_type": FilterField("clientConnectionType"),
    "wlan_name": FilterField("wlanName"),
    "vlan_id": FilterField("vlanId"),
    "tunnel_type": FilterField("tunnelType"),
}


def _validate_client_params(
    mac_address: str | None,
    list_params: dict[str, object | None],
) -> None:
    """Reject list-only filters that an exact MAC lookup would ignore."""
    if mac_address is None:
        return
    for param, value in list_params.items():
        if value is not None:
            raise ValueError(
                f"Parameter '{param}' cannot be combined with exact mac_address "
                "lookup because it would be ignored."
            )


async def _fetch_exact_client(conn: object, mac_address: str) -> object:
    """Fetch one client, translating Central's not-found exception to None."""
    try:
        return await asyncio.to_thread(
            Clients.get_client_details,
            central_conn=conn,
            client_mac=mac_address,
        )
    except Exception as exc:
        if MISSING_CLIENT_RESPONSE in str(exc):
            return None
        raise


def register(mcp: FastMCP) -> None:
    """Register the folded client tool with the MCP server."""

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_clients(
        ctx: Context,
        mac_address: str | None = None,
        site_id: str | None = None,
        site_name: str | None = None,
        serial_number: str | None = None,
        connection_type: Literal["Wired", "Wireless"] | None = None,
        status: Literal["Connected", "Failed"] | None = None,
        wlan_name: str | None = None,
        vlan_id: str | None = None,
        tunnel_type: Literal["Port-based", "User-based", "Overlay"] | None = None,
        start_query_time: str | None = None,
        end_query_time: str | None = None,
        limit: Annotated[int | None, Field(ge=1, le=MAX_PAGE_SIZE)] = None,
        cursor: str | None = None,
        response_format: Literal["concise", "detailed"] = "concise",
    ) -> ClientEnvelope:
        """Retrieve filtered clients or one exact MAC-address match.

        Use for client browsing and lookup; mac_address selects detail mode.
        Cross-field rule: mac_address cannot combine with list filters, time bounds, limit, or cursor.
        Returns ClientEnvelope; response_format selects concise or detailed items. Replay next_cursor as cursor with identical filters and the original limit.
        """
        try:
            list_params = {
                "site_id": site_id,
                "site_name": site_name,
                "serial_number": serial_number,
                "connection_type": connection_type,
                "status": status,
                "wlan_name": wlan_name,
                "vlan_id": vlan_id,
                "tunnel_type": tunnel_type,
                "start_query_time": start_query_time,
                "end_query_time": end_query_time,
            }
            _validate_client_params(mac_address, list_params)

            if mac_address is None:
                query_hash = hash_query(list_params)
                page_size = limit if limit is not None else DEFAULT_CLIENT_LIMIT
                next_page = 1
                if cursor is not None:
                    decoded_cursor = decode_cursor(
                        cursor,
                        expected_tool=CLIENT_TOOL_NAME,
                        expected_query_hash=query_hash,
                    )
                    if decoded_cursor.page_size > MAX_PAGE_SIZE:
                        raise ValueError(INVALID_CURSOR_MESSAGE)
                    if limit is not None and limit != decoded_cursor.page_size:
                        raise ValueError("limit conflicts with the cursor page_size")
                    page_size = decoded_cursor.page_size
                    next_page = decode_next_page(decoded_cursor.position)

            async with api_context(ctx) as conn:
                if mac_address is not None:
                    result = await _fetch_exact_client(conn, mac_address)

                    if isinstance(result, list):
                        raw_items = result
                    elif isinstance(result, dict):
                        raw_items = [result]
                    elif result is None:
                        raw_items = []
                    else:
                        raise ValueError(
                            "Unexpected client detail response; expected an object or list."
                        )
                    if len(raw_items) > 1:
                        raise ValueError(
                            "Multiple clients found; mac_address must identify one client."
                        )
                    items = clean_client_data(raw_items)
                    return build_envelope(
                        ClientEnvelope,
                        items,
                        total=len(items),
                        ceiling=1,
                        response_format=response_format,
                    )
                else:
                    filter_str = build_filters(
                        CLIENT_FILTER_FIELDS,
                        status=status,
                        connection_type=connection_type,
                        wlan_name=wlan_name,
                        vlan_id=vlan_id,
                        tunnel_type=tunnel_type,
                    )
                    response = await asyncio.to_thread(
                        Clients.get_clients,
                        central_conn=conn,
                        site_id=site_id,
                        site_name=site_name,
                        serial_number=serial_number,
                        start_time=start_query_time,
                        end_time=end_query_time,
                        filter_str=filter_str,
                        next_page=next_page,
                        limit=page_size,
                    )
                    if not isinstance(response, dict):
                        raise ValueError(
                            "Unexpected clients response; expected an object."
                        )
                    raw_items = response.get("items", [])
                    if not isinstance(raw_items, list):
                        raise ValueError(
                            "Unexpected clients response; expected an items list."
                        )
                    total = response.get("total")
                    upstream_next = response.get("next")
                    next_cursor = None
                    if upstream_next not in (None, ""):
                        next_cursor = encode_cursor(
                            CLIENT_TOOL_NAME,
                            page_size,
                            {"upstream_next": str(upstream_next)},
                            query_hash,
                        )

                    items = clean_client_data(raw_items)
                    return build_envelope(
                        ClientEnvelope,
                        items,
                        total=total,
                        total_available=total,
                        next_cursor=next_cursor,
                        ceiling=page_size,
                        response_format=response_format,
                    )
        except Exception as exc:
            raise_central_error(exc, "retrieving clients")
