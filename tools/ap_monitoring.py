import asyncio
from typing import Any, Literal

from fastmcp import Context, FastMCP
from pycentral.new_monitoring import MonitoringAPs

from constants import TIME_RANGE
from models import WLAN, AccessPoint, AccessPointStatistics
from tools import READ_ONLY
from utils.common import (
    FilterField,
    api_context,
    build_filters,
    format_tool_error,
)
from utils.events import _resolve_time_window
from utils.wlans import clean_wlan_data

AP_FILTER_FIELDS: dict[str, FilterField] = {
    "site_id": FilterField("siteId"),
    "site_name": FilterField("siteName"),
    "serial_number": FilterField("serialNumber"),
    "device_name": FilterField("deviceName"),
    "status": FilterField("status"),
    "model": FilterField("model"),
    "firmware_version": FilterField("firmwareVersion"),
    "deployment": FilterField("deployment"),
    "cluster_id": FilterField("clusterId"),
    "cluster_name": FilterField("clusterName"),
}


def register(mcp: FastMCP) -> None:
    """Register AP monitoring tools with the MCP server."""

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_aps(
        ctx: Context,
        site_id: str | None = None,
        site_name: str | None = None,
        serial_number: str | None = None,
        device_name: str | None = None,
        status: Literal["ONLINE", "OFFLINE"] | None = None,
        model: str | None = None,
        firmware_version: str | None = None,
        deployment: Literal["Standalone", "Cluster", "Unspecified"] | None = None,
        cluster_id: str | None = None,
        cluster_name: str | None = None,
        sort: str | None = None,
    ) -> list[AccessPoint] | str:
        """Return a filtered list of APs from Central using typed filter parameters.

        Prefer this over broad inventory fetches when the request targets specific APs.
        Call central_get_site_name_id_mapping first if you need to resolve site IDs.

        Parameters
        ----------
        - site_id: Exact site ID.
        - site_name: Exact site name.
        - serial_number: AP serial number. Supports comma-separated values.
        - device_name: AP device name. Supports comma-separated values.
        - status: AP status. Allowed values: ONLINE or OFFLINE.
        - model: AP model value. Supports comma-separated values.
        - firmware_version: AP firmware version. Supports comma-separated values.
        - deployment: AP deployment type. Allowed values: Standalone, Cluster, or Unspecified.
        - cluster_id: AP cluster ID. Supports comma-separated values.
        - cluster_name: AP cluster name. Supports comma-separated values.
        - sort: Comma-separated sort expressions, for example "deviceName asc".
          Supported fields are siteId, serialNumber, deviceName, model, status, and deployment.

        """
        async with api_context(ctx) as conn:
            try:
                filter_str = build_filters(
                    AP_FILTER_FIELDS,
                    site_id=site_id,
                    site_name=site_name,
                    serial_number=serial_number,
                    device_name=device_name,
                    status=status,
                    model=model,
                    firmware_version=firmware_version,
                    deployment=deployment,
                    cluster_id=cluster_id,
                    cluster_name=cluster_name,
                )
                aps = await asyncio.to_thread(
                    MonitoringAPs.get_all_aps,
                    central_conn=conn,
                    filter_str=filter_str,
                    sort=sort,
                )
            except Exception as e:
                return format_tool_error("fetching access points", e)

            if not aps:
                return "No access points found matching the specified criteria."
            try:
                return [AccessPoint.from_api(ap) for ap in aps]
            except Exception as e:
                return format_tool_error("parsing access point data", e)

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_ap_statistics(
        ctx: Context,
        serial_number: str,
        time_range: TIME_RANGE = "last_1h",
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[AccessPointStatistics] | str:
        """Return AP statistics (CPU, memory, power) for a given AP serial number within a time window.

        Parameters
        ----------
        - serial_number: Serial number of the AP.
        - time_range: Predefined time window. Allowed values: last_1h, last_6h, last_24h,
          last_7d, last_30d, today, yesterday. Ignored if both start_time and end_time are provided.
        - start_time: Start of the time window in RFC 3339 format (e.g. "2026-03-21T00:00:00.000Z").
          Overrides time_range when combined with end_time.
        - end_time: End of the time window in RFC 3339 format (e.g. "2026-03-21T23:59:59.999Z").
          Overrides time_range when combined with start_time.

        """
        start_at, end_at = _resolve_time_window(time_range, start_time, end_time)
        async with api_context(ctx) as conn:
            try:
                stats = await asyncio.to_thread(
                    MonitoringAPs.get_ap_stats,
                    central_conn=conn,
                    serial_number=serial_number,
                    start_time=start_at,
                    end_time=end_at,
                )
            except Exception as e:
                return format_tool_error("fetching access point statistics", e)

            if not stats:
                return f"No AP statistics found for serial number '{serial_number}'."
            return stats

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_ap_wlans(
        ctx: Context,
        serial_number: str,
        wlan_name: str | None = None,
    ) -> list[WLAN] | str:
        """Return WLANs associated with a specific AP.

        Retrieves all WLANs currently active on the AP identified by serial_number.
        Use wlan_name to narrow results to a single SSID by exact name.

        Parameters
        ----------
        - serial_number: Serial number of the AP to query. Required.
        - wlan_name: Exact WLAN name (SSID) to filter by. Applied client-side.

        """
        async with api_context(ctx) as conn:
            try:
                response = await asyncio.to_thread(
                    MonitoringAPs.get_ap_wlans,
                    central_conn=conn,
                    serial_number=serial_number,
                )
            except Exception as e:
                return format_tool_error("fetching AP WLANs", e)

        items = response.get("items", []) if isinstance(response, dict) else []
        if wlan_name:
            items = [w for w in items if w.get("wlanName") == wlan_name]

        if not items:
            return f"No WLANs found for AP '{serial_number}'."
        return clean_wlan_data(items)
