import asyncio
from typing import Literal

from fastmcp import Context, FastMCP

from constants import APP_LIMIT, TIME_RANGE
from models import App, PaginatedApps
from tools import READ_ONLY
from utils.applications import clean_app_data
from utils.common import FilterField, api_context, build_filters, format_tool_error
from utils.events import _resolve_time_window

APP_FILTER_FIELDS: dict[str, FilterField] = {
    "app_category": FilterField(
        "APP_CAT",
        [
            "Antivirus",
            "Business and Economy",
            "Computer and Internet Info",
            "Computer and Internet Security",
            "Encrypted",
            "Internet Communications",
            "Network Service",
            "Office365 SAAS",
            "Standard",
            "Web",
        ],
    ),
    "state": FilterField("STATE", ["allowed", "partial", "blocked"]),
    "risk": FilterField(
        "RISK",
        ["Low", "High", "Suspicious", "Moderate", "Trustworthy", "Not Evaluated"],
    ),
    "tls_version": FilterField("TLS_VERSION"),
    "host_type": FilterField("APPLICATION_HOST_TYPE", ["Hybrid", "Private", "Public"]),
    "country": FilterField("COUNTRY"),
}


def register(mcp: FastMCP) -> None:
    """Register app visibility tools with the MCP server."""

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_apps(
        ctx: Context,
        site_id: str,
        time_range: TIME_RANGE | None = "last_1h",
        start_time: str | None = None,
        end_time: str | None = None,
        client_id: str | None = None,
        app_category: (
            Literal[
                "Antivirus",
                "Business and Economy",
                "Computer and Internet Info",
                "Computer and Internet Security",
                "Encrypted",
                "Internet Communications",
                "Network Service",
                "Office365 SAAS",
                "Standard",
                "Web",
            ]
            | None
        ) = None,
        state: Literal["allowed", "partial", "blocked"] | None = None,
        risk: (
            Literal[
                "Low",
                "High",
                "Suspicious",
                "Moderate",
                "Trustworthy",
                "Not Evaluated",
            ]
            | None
        ) = None,
        tls_version: str | None = None,
        host_type: Literal["Hybrid", "Private", "Public"] | None = None,
        country: str | None = None,
        limit: int = APP_LIMIT,
        offset: int = 0,
    ) -> PaginatedApps | str:
        """Return application visibility data for a site over a time window.

        Always provide `site_id` — never call without one. Combine filters to
        narrow results; multiple filters are AND-combined.

        Parameters
        ----------
        - site_id: Site ID to scope the query (required).
        - time_range: Named time window preset (e.g. "last_1h", "last_24h"); defaults to
          "last_1h". Mutually exclusive with start_time/end_time.
        - start_time: RFC 3339 start of the time window. Requires end_time.
        - end_time: RFC 3339 end of the time window. Requires start_time.
        - client_id: Filter by client identifier.
        - app_category: Filter by app category. Allowed values: Antivirus,
          Business and Economy, Computer and Internet Info, Computer and Internet
          Security, Encrypted, Internet Communications, Network Service, Office365
          SAAS, Standard, Web.
        - state: Filter by permission state. Allowed values: allowed, partial, blocked.
        - risk: Filter by risk level. Allowed values: Low, High, Suspicious, Moderate,
          Trustworthy, Not Evaluated.
        - tls_version: Filter by TLS version (e.g. "TLS 1.2").
        - host_type: Filter by application host type. Allowed values: Hybrid, Private,
          Public.
        - country: Filter by application server country (ISO code, e.g. "IN").
        - limit: Max records to return per page (default 100). Max 1000.
        - offset: Pagination offset (default 0).

        """
        async with api_context(ctx) as conn:
            try:
                start_at, end_at = _resolve_time_window(
                    time_range, start_time, end_time
                )
                filter_str = build_filters(
                    APP_FILTER_FIELDS,
                    app_category=app_category,
                    state=state,
                    risk=risk,
                    tls_version=tls_version,
                    host_type=host_type,
                    country=country,
                )

                query_params: dict = {
                    "site-id": site_id,
                    "start-at": start_at,
                    "end-at": end_at,
                    "limit": limit,
                    "offset": offset,
                }
                if client_id:
                    query_params["client-id"] = client_id
                if filter_str:
                    query_params["filter"] = filter_str

                response = await asyncio.to_thread(
                    conn.command,
                    api_method="GET",
                    api_path="network-monitoring/v1/applications",
                    api_params=query_params,
                )
                if response["code"] != 200:
                    return format_tool_error("fetching apps", response["msg"])
            except Exception as e:
                return format_tool_error("fetching apps", e)

            msg = response["msg"]

            # Initial processing
            response = msg.get("applicationsV1", msg.get("applications", []))
            try:
                return PaginatedApps(
                    items=clean_app_data(response["items"]),
                    total=response.get("total", 0),
                    offset=response.get("offset", offset),
                    limit=response.get("limit", limit),
                )
            except Exception as e:
                return format_tool_error("parsing apps", e)
