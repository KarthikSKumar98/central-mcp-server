"""Gateway monitoring tools for HPE Aruba Central.

Wraps MonitoringGateways endpoints and exposes them as MCP tools.
"""

import asyncio
from typing import Literal

from fastmcp import Context, FastMCP
from pycentral.new_monitoring.gateways import MonitoringGateways

from constants import TIME_RANGE
from models import Gateway, GatewayCluster, GatewayDetail, TrendSample
from tools import READ_ONLY
from utils.common import (
    FilterField,
    api_context,
    build_filters,
    format_tool_error,
)
from utils.events import _resolve_time_window
from utils.monitoring import (
    GATEWAY_INCLUDES,
    GATEWAY_TREND_SCOPES,
    fetch_cluster_snapshot,
    fetch_snapshot,
    fetch_trends,
)

GATEWAY_FILTER_FIELDS: dict[str, FilterField] = {
    "site_id": FilterField("siteId"),
    "site_name": FilterField("siteName"),
    "serial_number": FilterField("serialNumber"),
    "device_name": FilterField("deviceName"),
    "model": FilterField("model"),
    "status": FilterField("status"),
    "cluster_name": FilterField("clusterName"),
}


def _normalize_temperature_trends(raw) -> list[dict]:
    """Normalize hardware-temperature trends to a flat per-timestamp format.

    ``hardware-temperature`` returns a *list* of sensor dicts (one per sensor),
    each with ``graph.samples`` and ``graph.keys[0]`` as the sensor name.
    This normalizer merges all sensors into a single list of samples where each
    sample contains a ``timestamp`` key plus one key per sensor (e.g. ``CPU``,
    ``Ambient``).  Sensor names are preserved as returned by the API.

    Example output::

        [
            {"timestamp": "2026-06-05T19:05:00Z", "CPU": 42.0, "Ambient": 30.0},
            {"timestamp": "2026-06-05T19:10:00Z", "CPU": 43.0, "Ambient": 31.0},
        ]
    """
    if not isinstance(raw, list):
        # Already normalized by pycentral; return as-is
        return raw if isinstance(raw, list) else []

    # Build a mapping: timestamp -> {sensor: value, ...}
    merged: dict[str, dict] = {}
    for sensor_block in raw:
        if not isinstance(sensor_block, dict):
            continue
        graph = sensor_block.get("graph", {})
        keys = graph.get("keys", [])
        samples = graph.get("samples", [])
        if not keys or not samples:
            continue
        sensor_name = keys[0]
        for sample in samples:
            ts = sample.get("timestamp", "")
            data = sample.get("data", [])
            if not ts:
                continue
            if ts not in merged:
                merged[ts] = {"timestamp": ts}
            if data:
                merged[ts][sensor_name] = data[0]

    # Sort ascending by timestamp
    return sorted(merged.values(), key=lambda s: s["timestamp"])


def _normalize_capacity_trends(raw) -> list[dict]:
    """Normalize cluster capacity trends to an LLM-friendly flat list.

    ``get_cluster_capacity_trends`` returns a list of capacity-type dicts,
    each with a multi-key ``graph``.  This normalizer flattens each into a
    list of per-timestamp samples with all metric keys present, grouped under
    a ``capacity_type`` field.

    Example output::

        [
            {
                "capacity_type": "client_capacity",
                "timestamp": "2026-06-05T19:00:00Z",
                "active_client_count": 0,
                "standby_client_count": 0,
                "cluster_client_max_capacity": 65536,
                "active_client_percentage": 0,
                "standby_client_percentage": 0,
            },
            ...
        ]

    Each capacity type's samples appear sequentially; callers can filter on
    ``capacity_type`` to isolate ``"client_capacity"`` vs ``"device_capacity"``.
    """
    if not isinstance(raw, list):
        return []

    result: list[dict] = []
    for block in raw:
        if not isinstance(block, dict):
            continue
        capacity_type = block.get("capacityType", "unknown")
        graph = block.get("graph", {})
        keys = graph.get("keys", [])
        samples = graph.get("samples", [])
        for sample in samples:
            ts = sample.get("timestamp", "")
            data = sample.get("data", [])
            flat: dict = {"capacity_type": capacity_type, "timestamp": ts}
            for i, key in enumerate(keys):
                flat[key] = data[i] if i < len(data) else None
            result.append(flat)

    return result


def register(mcp: FastMCP) -> None:
    """Register gateway monitoring tools with the MCP server."""

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_gateways(
        ctx: Context,
        site_id: str | None = None,
        site_name: str | None = None,
        serial_number: str | None = None,
        device_name: str | None = None,
        model: str | None = None,
        status: Literal["Online", "Offline"] | None = None,
        cluster_name: str | None = None,
        sort: str | None = None,
    ) -> list[Gateway] | str:
        """Return a filtered list of gateways from Central using typed filter parameters.

        Prefer this over broad inventory fetches when the request targets specific
        gateways. Call central_get_summary first if you need to resolve site IDs.

        NOTE: Gateway ``status`` uses **title-case** values (``"Online"`` /
        ``"Offline"``), which is different from APs (``"ONLINE"`` / ``"OFFLINE"``).
        Passing ``"ONLINE"`` will return zero results.

        Parameters
        ----------
        - site_id: Exact site ID.
        - site_name: Exact site name.
        - serial_number: Gateway serial number. Supports comma-separated values.
        - device_name: Gateway device name. Supports comma-separated values.
        - model: Gateway model (e.g. 'A7240XM', 'A9004'). Supports comma-separated values.
        - status: Gateway status. Allowed values: Online or Offline (title-case).
        - cluster_name: Cluster name the gateway belongs to.
        - sort: Comma-separated sort expressions, for example "deviceName asc".

        """
        async with api_context(ctx) as conn:
            try:
                filter_str = build_filters(
                    GATEWAY_FILTER_FIELDS,
                    site_id=site_id,
                    site_name=site_name,
                    serial_number=serial_number,
                    device_name=device_name,
                    model=model,
                    status=status,
                    cluster_name=cluster_name,
                )
                gateways = await asyncio.to_thread(
                    MonitoringGateways.get_all_gateways,
                    central_conn=conn,
                    filter_str=filter_str,
                    sort=sort,
                )
            except Exception as e:
                return format_tool_error("fetching gateways", e)

            if not gateways:
                return "No gateways found matching the specified criteria."
            try:
                return [Gateway.from_api(gw) for gw in gateways]
            except Exception as e:
                return format_tool_error("parsing gateway data", e)

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_gateway_details(
        ctx: Context,
        serial_number: str,
        include: list[Literal["ports", "tunnels", "uplinks", "vlans"]] | None = None,
    ) -> GatewayDetail | str:
        """Return a detailed single-gateway snapshot for the given serial number.

        Unlike APs, ``get_gateway_details`` returns the **same shape** as a list
        item — no sub-resources are embedded in the base response.  Pass
        ``include`` to add richer sub-resource data via separate API calls.

        All includes are **additive** — the base response embeds nothing.

        Available includes:

        - ``"ports"``: Wired port list with health, speed, duplex, throughput.
          Use the ``port_number`` field from ports to query port trends.
        - ``"tunnels"``: Tunnel list with health, status, peer type, throughput.
          Use the ``tunnel_name`` field from tunnels to query tunnel trends.
        - ``"uplinks"``: Uplink list (``{items, total}`` envelope unwrapped).
          Use the ``link_tag`` field from uplinks to query uplink trends.
        - ``"vlans"``: VLAN list with IP, subnet, and status.

        Using ``include`` makes extra API calls; omit it when the base data
        is sufficient to keep responses fast and token-efficient.

        Parameters
        ----------
        - serial_number: Serial number of the gateway to query. Required.
        - include: Optional list of sub-resources to fetch. Allowed values:
          ``"ports"``, ``"tunnels"``, ``"uplinks"``, ``"vlans"``.

        """
        async with api_context(ctx) as conn:
            try:
                raw = await asyncio.to_thread(
                    fetch_snapshot,
                    conn,
                    serial_number,
                    include,
                    monitor_cls=MonitoringGateways,
                    base_method="get_gateway_details",
                    includes_map=GATEWAY_INCLUDES,
                )
            except Exception as e:
                return format_tool_error("fetching gateway details", e)
        if not raw:
            return f"No gateway found for serial number '{serial_number}'."
        try:
            return GatewayDetail.from_api(raw)
        except Exception as e:
            return format_tool_error("parsing gateway details", e)

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_gateway_trends(
        ctx: Context,
        serial_number: str,
        metric: str,
        scope: Literal["gateway", "port", "tunnel", "uplink"] = "gateway",
        port_number: str | None = None,
        tunnel_name: str | None = None,
        link_tag: str | None = None,
        time_range: TIME_RANGE = "last_1h",
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[TrendSample] | str:
        """Return time-series trend samples for a gateway, port, tunnel, or uplink.

        The ``scope`` parameter selects which entity to query and determines
        which metrics are valid:

        - ``scope="gateway"`` (default): Gateway-level metrics.
          Valid metrics: ``cpu-utilization``, ``memory-utilization``,
          ``wan-availability``, ``vpn-availability``, ``hardware-temperature``.
          No additional identifier required.
          NOTE: ``wan-availability`` and ``vpn-availability`` return ``-1`` when
          no WAN/VPN probes are configured on the gateway (typical for branch
          gateways).

        - ``scope="port"``: Per-port metrics.
          Valid metrics: ``throughput``, ``frames``, ``frames-errors``,
          ``frames-packets``.
          Requires ``port_number`` (string, e.g. ``"0"``). Retrieve port numbers
          via ``central_get_gateway_details`` with ``include=["ports"]``.

        - ``scope="tunnel"``: Per-tunnel metrics.
          Valid metrics: ``throughput``, ``status``, ``dropped-packets``.
          Requires ``tunnel_name`` (e.g. ``"GW01:inet::AP04:inet"``). Retrieve
          tunnel names via ``central_get_gateway_details`` with
          ``include=["tunnels"]``.

        - ``scope="uplink"``: Per-uplink metrics.
          Valid metrics: ``throughput``, ``wan-compression``, ``wan-availability``.
          Requires ``link_tag``. Retrieve link tags via
          ``central_get_gateway_details`` with ``include=["uplinks"]``.

        **hardware-temperature normalization**: returns a list of samples where
        each sample contains a ``timestamp`` plus one key per sensor (e.g.
        ``CPU``, ``Ambient``).  Example::

            {"timestamp": "2026-06-05T19:05:00Z", "CPU": 42.0, "Ambient": 30.0}

        Time window: ``start_time`` + ``end_time`` (RFC 3339) override
        ``time_range`` when both are supplied.  Otherwise ``time_range`` selects
        a named window relative to now (last_1h, last_6h, last_24h, last_7d,
        last_30d, today, yesterday).

        Parameters
        ----------
        - serial_number: Serial number of the gateway to query. Required.
        - metric: Metric to retrieve. Must be valid for the chosen scope (see above).
        - scope: Entity scope: ``"gateway"``, ``"port"``, ``"tunnel"``, or
          ``"uplink"``. Default ``"gateway"``.
        - port_number: Port number string (e.g. ``"0"``). Required when
          ``scope="port"``.
        - tunnel_name: Tunnel name string. Required when ``scope="tunnel"``.
        - link_tag: Uplink link tag. Required when ``scope="uplink"``.
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
                    sub_id=port_number or tunnel_name or link_tag,
                    monitor_cls=MonitoringGateways,
                    scopes=GATEWAY_TREND_SCOPES,
                )
            except ValueError as e:
                return format_tool_error("validating gateway trend request", e)
            except Exception as e:
                return format_tool_error("fetching gateway trends", e)

        if not raw:
            return f"No {scope} trend data found for serial number '{serial_number}'."

        # hardware-temperature raw response is a list of per-sensor dicts;
        # normalize into a merged per-timestamp structure.
        if metric == "hardware-temperature" and isinstance(raw, list) and raw and isinstance(raw[0], dict) and "graph" in raw[0]:
            try:
                normalized = _normalize_temperature_trends(raw)
                return [TrendSample(**s) for s in normalized]
            except Exception as e:
                return format_tool_error("parsing gateway temperature trends", e)

        try:
            return [TrendSample(**sample) for sample in raw]
        except Exception as e:
            return format_tool_error("parsing gateway trends", e)

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_gateway_cluster(
        ctx: Context,
        cluster_name: str,
        include: list[Literal["tunnels", "vlan_mismatch", "connectivity"]] | None = None,
    ) -> GatewayCluster | str:
        """Return a snapshot of a gateway cluster with members and tunnel health.

        Always fetches:
        - **members**: List of cluster member gateways with role, status, model,
          and IP.  NOTE: cluster member ``status`` is ``"ONLINE"`` / ``"OFFLINE"``
          (ALL-CAPS), unlike the gateway list which uses ``"Online"`` / ``"Offline"``.
        - **tunnel_health_summary**: Per-member tunnel health counts
          (``{good, fair, poor}``).

        Optional includes (each makes an additional API call):

        - ``"tunnels"``: All cluster tunnels (from get_cluster_tunnel_summary,
          status type — a single dict with up/down counts).
        - ``"vlan_mismatch"``: VLAN mismatch summary across members
          (``{good, poor}`` counts).
        - ``"connectivity"``: Cluster connectivity graph showing peer
          relationships and VLAN mismatch details per node.

        Parameters
        ----------
        - cluster_name: Name of the cluster to query. Required.
        - include: Optional list of additional sub-resources. Allowed values:
          ``"tunnels"``, ``"vlan_mismatch"``, ``"connectivity"``.

        """
        async with api_context(ctx) as conn:
            try:
                raw = await asyncio.to_thread(
                    fetch_cluster_snapshot,
                    conn,
                    cluster_name,
                    include,
                )
            except Exception as e:
                return format_tool_error("fetching gateway cluster", e)

        if not raw or not raw.get("members"):
            return f"No cluster found for cluster name '{cluster_name}'."
        try:
            return GatewayCluster.from_api(raw)
        except Exception as e:
            return format_tool_error("parsing gateway cluster data", e)

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_cluster_capacity_trends(
        ctx: Context,
        cluster_name: str,
        serial_number: str | None = None,
        time_range: TIME_RANGE = "last_1h",
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[dict] | str:
        """Return capacity trend samples for a gateway cluster.

        Fetches both capacity types in a single API call:

        - ``client_capacity``: Active/standby client counts and percentages vs
          the cluster's maximum client capacity.
          Keys: ``active_client_count``, ``standby_client_count``,
          ``cluster_client_max_capacity``, ``active_client_percentage``,
          ``standby_client_percentage``.

        - ``device_capacity``: Active/standby AP and switch counts and
          percentages vs the cluster's maximum device capacity.
          Keys: ``active_ap_count``, ``standby_ap_count``, ``active_sw_count``,
          ``standby_sw_count``, ``active_ap_percentage``,
          ``standby_ap_percentage``, ``active_sw_percentage``,
          ``standby_sw_percentage``, ``cluster_device_max_capacity``.

        Returns a flat list of dicts, each containing ``capacity_type``,
        ``timestamp``, and the metric keys for that type.  Filter on
        ``capacity_type`` to isolate ``"client_capacity"`` or
        ``"device_capacity"``.  Example sample::

            {
                "capacity_type": "client_capacity",
                "timestamp": "2026-06-05T19:00:00Z",
                "active_client_count": 0,
                "standby_client_count": 0,
                "cluster_client_max_capacity": 65536,
                "active_client_percentage": 0,
                "standby_client_percentage": 0,
            }

        Time window: ``start_time`` + ``end_time`` (RFC 3339) override
        ``time_range`` when both are supplied.

        Parameters
        ----------
        - cluster_name: Name of the cluster to query. Required.
        - serial_number: Optional serial number to drill down to a specific
          cluster member's capacity contribution.
        - time_range: Predefined time window. Allowed values: last_1h, last_6h,
          last_24h, last_7d, last_30d, today, yesterday. Ignored when both
          ``start_time`` and ``end_time`` are provided.
        - start_time: Start of the time window in RFC 3339 format.
          Overrides ``time_range`` when combined with ``end_time``.
        - end_time: End of the time window in RFC 3339 format.
          Overrides ``time_range`` when combined with ``start_time``.

        """
        start_at, end_at = _resolve_time_window(time_range, start_time, end_time)
        async with api_context(ctx) as conn:
            try:
                raw = await asyncio.to_thread(
                    MonitoringGateways.get_cluster_capacity_trends,
                    central_conn=conn,
                    cluster_name=cluster_name,
                    serial_number=serial_number,
                    start_time=start_at,
                    end_time=end_at,
                    return_raw_response=True,
                )
            except Exception as e:
                return format_tool_error("fetching cluster capacity trends", e)

        if not raw:
            return f"No capacity trend data found for cluster '{cluster_name}'."
        try:
            return _normalize_capacity_trends(raw)
        except Exception as e:
            return format_tool_error("parsing cluster capacity trends", e)
