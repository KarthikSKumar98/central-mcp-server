import asyncio
from typing import Literal

from fastmcp import Context, FastMCP
from pycentral.new_monitoring import MonitoringAPs

from constants import TIME_RANGE
from models import AccessPoint, APDetail, TrendSample
from tools import READ_ONLY
from utils.common import (
    FilterField,
    api_context,
    build_filters,
    format_tool_error,
)
from utils.events import _resolve_time_window
from utils.monitoring import fetch_snapshot, fetch_trends

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
        Call central_get_summary first if you need to resolve site IDs.

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
    async def central_get_ap_details(
        ctx: Context,
        serial_number: str,
        include: list[Literal["radios", "ports"]] | None = None,
    ) -> APDetail | str:
        """Return a detailed single-AP snapshot for the given serial number.

        The base snapshot (no ``include``) already embeds summary radios, ports,
        and WLANs inline.  Pass ``include`` to upgrade specific sub-resources to
        the richer dedicated payloads:

        - ``"radios"``: upgrades embedded radio summaries with full RF-health data
          (channel quality/utilization, client count, noise floor, non-Wi-Fi
          interference, tx/rx utilization, and more).
        - ``"ports"``: upgrades embedded port summaries with additional fields
          (port id, type).

        Using ``include`` makes extra API calls; omit it when the embedded summary
        data is sufficient to keep responses fast and token-efficient.

        Parameters
        ----------
        - serial_number: Serial number of the AP to query. Required.
        - include: Optional list of sub-resources to upgrade to dedicated payloads.
          Allowed values: ``"radios"``, ``"ports"``.

        """
        async with api_context(ctx) as conn:
            try:
                raw = await asyncio.to_thread(
                    fetch_snapshot, conn, serial_number, include
                )
            except Exception as e:
                return format_tool_error("fetching AP details", e)
        if not raw:
            return f"No AP found for serial number '{serial_number}'."
        try:
            return APDetail.from_api(raw)
        except Exception as e:
            return format_tool_error("parsing AP details", e)

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_ap_trends(
        ctx: Context,
        serial_number: str,
        metric: str,
        scope: Literal["ap", "radio", "port"] = "ap",
        radio_number: int | None = None,
        port_index: int | None = None,
        time_range: TIME_RANGE = "last_1h",
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[TrendSample] | str:
        """Return time-series trend samples for an AP, radio, or wired port.

        The ``scope`` parameter selects which entity to query and determines
        which metrics are valid:

        - ``scope="ap"`` (default): AP-level metrics.
          Valid metrics: ``throughput``, ``cpu-utilization``, ``memory-utilization``,
          ``power-consumption``.
          No additional identifier required.

        - ``scope="radio"``: Per-radio RF metrics.
          Valid metrics: ``throughput``, ``channel-utilization``, ``channel-quality``,
          ``noise-floor``, ``frames``.
          Requires ``radio_number``.

        - ``scope="port"``: Per-wired-port metrics.
          Valid metrics: ``throughput``, ``frames``, ``crc``, ``collisions``.
          Requires ``port_index``.

        Each returned sample contains a ``timestamp`` (RFC 3339) plus one or more
        metric-specific value keys (e.g. ``tx``/``rx`` for throughput,
        ``cpu_utilization`` for cpu-utilization).

        Time window: ``start_time`` + ``end_time`` (RFC 3339) override
        ``time_range`` when both are supplied.  Otherwise ``time_range`` selects a
        named window relative to now (last_1h, last_6h, last_24h, last_7d,
        last_30d, today, yesterday).

        Parameters
        ----------
        - serial_number: Serial number of the AP to query. Required.
        - metric: Metric to retrieve. Must be valid for the chosen scope (see above).
        - scope: Entity scope: ``"ap"``, ``"radio"``, or ``"port"``. Default ``"ap"``.
        - radio_number: Radio index (0-based). Required when ``scope="radio"``.
        - port_index: Port index. Required when ``scope="port"``.
        - time_range: Predefined time window. Allowed values: last_1h, last_6h,
          last_24h, last_7d, last_30d, today, yesterday. Ignored when both
          ``start_time`` and ``end_time`` are provided.
        - start_time: Start of the time window in RFC 3339 format
          (e.g. ``"2026-03-21T00:00:00.000Z"``). Overrides ``time_range`` when
          combined with ``end_time``.
        - end_time: End of the time window in RFC 3339 format
          (e.g. ``"2026-03-21T23:59:59.999Z"``). Overrides ``time_range`` when
          combined with ``start_time``.

        """
        start_at, end_at = _resolve_time_window(time_range, start_time, end_time)
        async with api_context(ctx) as conn:
            try:
                raw = await asyncio.to_thread(
                    fetch_trends,
                    conn,
                    serial_number,
                    scope,
                    metric,
                    (start_at, end_at),
                    radio_number=radio_number,
                    port_index=port_index,
                )
            except ValueError as e:  # validation: invalid scope/metric/missing id
                return format_tool_error("validating AP trend request", e)
            except Exception as e:
                return format_tool_error("fetching AP trends", e)
        if not raw:
            return f"No {scope} trend data found for serial number '{serial_number}'."
        try:
            return [TrendSample(**sample) for sample in raw]
        except Exception as e:
            return format_tool_error("parsing AP trends", e)
