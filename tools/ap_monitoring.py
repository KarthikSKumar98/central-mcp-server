import asyncio
from typing import Any, Literal

from fastmcp import Context, FastMCP
from pycentral.new_monitoring import MonitoringAPs

from models import AccessPoint
from tools import READ_ONLY
from utils.common import FilterField, api_context, build_filters, format_tool_error

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
        deployment: str | None = None,
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
        - deployment: AP deployment type. Supports comma-separated values.
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
                return [AccessPoint(**ap) for ap in aps]
            except Exception as e:
                return format_tool_error("parsing access point data", e)

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_ap_latest_stats(
        ctx: Context,
        serial_number: str,
    ) -> dict[str, Any] | str:
        """Return the latest AP stats (CPU, memory, power) for a given AP serial number.

        Parameters
        ----------
        - serial_number: Serial number of the AP.

        """
        async with api_context(ctx) as conn:
            try:
                stats = await asyncio.to_thread(
                    MonitoringAPs.get_latest_ap_stats,
                    central_conn=conn,
                    serial_number=serial_number,
                )
            except Exception as e:
                return format_tool_error("fetching latest access point stats", e)

            if not stats:
                return f"No AP stats found for serial number '{serial_number}'."
            return stats
