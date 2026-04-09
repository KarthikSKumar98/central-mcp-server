import asyncio

from fastmcp import Context, FastMCP

from constants import TIME_RANGE
from models import WLAN, WLANThroughputSample
from tools import READ_ONLY
from utils.common import api_context, format_tool_error
from utils.events import _resolve_time_window
from utils.wlans import clean_wlan_data, clean_wlan_stats_data, get_all_wlans


def register(mcp: FastMCP) -> None:
    """Register WLAN tools with the MCP server."""

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_wlans(
        ctx: Context,
        wlan_name: str | None = None,
        site_id: str | None = None,
        sort: str | None = None,
    ) -> list[WLAN] | str:
        """Return WLANs configured in Central, with optional filtering by name or site.

        Fetches all pages automatically. Use site_id to scope results to a specific
        site; use wlan_name to match a single SSID by exact name.
        Call central_get_summary first to resolve site IDs, if site-specific filtering is needed.

        Parameters
        ----------
        - wlan_name: Exact WLAN name (SSID) to look up directly.
        - site_id: Site ID to scope results to a specific site. Max 128 characters.
        - sort: Comma-separated sort expressions. Supported fields: wlanName, band,
          status, securityLevel, security, vlan, primaryUsage.

        """
        async with api_context(ctx) as conn:
            try:
                if wlan_name:
                    api_params = {"site_id": site_id} if site_id else None
                    response = await asyncio.to_thread(
                        conn.command,
                        api_method="GET",
                        api_path=f"network-monitoring/v1/wlans/{wlan_name}",
                        api_params=api_params,
                    )
                    if response["code"] == 404:
                        return "No WLANs found matching the specified criteria."
                    if response["code"] != 200:
                        return format_tool_error(
                            "fetching WLANs",
                            Exception(
                                f"API returned {response['code']}: {response['msg']}"
                            ),
                        )
                    payload = response.get("msg")
                    wlans = [payload] if isinstance(payload, dict) else payload or []
                else:
                    wlans = await asyncio.to_thread(
                        get_all_wlans,
                        central_conn=conn,
                        site_id=site_id,
                        sort=sort,
                    )
            except Exception as e:
                return format_tool_error("fetching WLANs", e)

        if not wlans:
            return "No WLANs found matching the specified criteria."
        return clean_wlan_data(wlans)

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_wlan_stats(
        ctx: Context,
        wlan_name: str,
        time_range: TIME_RANGE = "last_1h",
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[WLANThroughputSample] | str:
        """Return throughput trend data for a specific WLAN over a time window.

        Returns a time-series of standardized throughput samples for the named
        WLAN. Each sample includes timestamp plus tx and rx throughput values in
        bits per second, where tx is transmitted data and rx is received data.
        Use time_range for common windows, or provide both start_time and
        end_time for a custom range (they override time_range when both are
        set).

        Parameters
        ----------
        - wlan_name: Name of the WLAN (SSID) to retrieve statistics for. Required.
        - time_range: Predefined time window. Allowed values: last_1h, last_6h,
          last_24h, last_7d, last_30d, today, yesterday. Ignored if both
          start_time and end_time are provided.
        - start_time: Start of the time window in RFC 3339 format
          (e.g. "2026-03-21T00:00:00.000Z"). Overrides time_range when combined
          with end_time.
        - end_time: End of the time window in RFC 3339 format
          (e.g. "2026-03-21T23:59:59.999Z"). Overrides time_range when combined
          with start_time.

        """
        start_at, end_at = _resolve_time_window(time_range, start_time, end_time)
        async with api_context(ctx) as conn:
            try:
                response = await asyncio.to_thread(
                    conn.command,
                    api_method="GET",
                    api_path=f"network-monitoring/v1/wlans/{wlan_name}/throughput-trends",
                    api_params={
                        "filter": f"timestamp gt {start_at} and timestamp lt {end_at}"
                    },
                )
            except Exception as e:
                return format_tool_error("fetching WLAN statistics", e)

        if response["code"] != 200:
            return format_tool_error(
                "fetching WLAN statistics",
                Exception(f"API returned {response['code']}: {response['msg']}"),
            )
        samples = clean_wlan_stats_data(response["msg"])
        if not samples:
            return f"No throughput data found for WLAN '{wlan_name}'."
        return samples
