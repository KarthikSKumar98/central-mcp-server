"""Gateway monitoring tools for HPE Aruba Central.

Wraps MonitoringGateways endpoints and exposes them as MCP tools.
"""

import asyncio
from typing import Literal

from fastmcp import Context, FastMCP
from pycentral.new_monitoring.gateways import MonitoringGateways

from constants import TIME_RANGE
from models import GatewayCluster, GatewayClusterEnvelope
from tools import READ_ONLY
from utils.common import api_context
from utils.envelope import build_envelope, raise_central_error
from utils.events import _resolve_time_window
from utils.monitoring import fetch_cluster_snapshot

CLUSTER_INCLUDE_PARAMS: dict[str, frozenset[str]] = {
    "tunnels": frozenset(),
    "vlan_mismatch": frozenset(),
    "connectivity": frozenset(),
    "capacity": frozenset({"serial_number", "time_range", "start_time", "end_time"}),
}


def _normalize_temperature_trends(raw: list) -> list[dict]:
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


def _normalize_capacity_trends(raw: list) -> list[dict]:
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


def _validate_cluster_params(
    include: list[str] | None,
    serial_number: str | None,
    time_range: str | None,
    start_time: str | None,
    end_time: str | None,
) -> list[str]:
    """Validate include values and capacity-only parameters before API access."""
    if include is None:
        includes: list[str] = []
    elif not isinstance(include, list):
        raise ValueError("Parameter 'include' must be a list of include values.")
    else:
        includes = include

    for value in includes:
        if value not in CLUSTER_INCLUDE_PARAMS:
            valid = ", ".join(CLUSTER_INCLUDE_PARAMS)
            raise ValueError(
                f"Invalid include value '{value}'. Valid include values: {valid}."
            )

    if "capacity" not in includes and (
        serial_number is not None
        or time_range is not None
        or start_time is not None
        or end_time is not None
    ):
        raise ValueError(
            "serial_number, time_range, start_time, and end_time require "
            "include='capacity'."
        )
    return includes


def register(mcp: FastMCP) -> None:
    """Register the folded gateway-cluster tool with the MCP server."""

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_gateway_cluster(
        ctx: Context,
        cluster_name: str,
        include: list[Literal["tunnels", "vlan_mismatch", "connectivity", "capacity"]]
        | None = None,
        serial_number: str | None = None,
        time_range: TIME_RANGE | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        response_format: Literal["concise", "detailed"] = "concise",
    ) -> GatewayClusterEnvelope:
        """Retrieve a gateway-cluster snapshot with optional resources.

        Use for member or tunnel health and capacity trends.
        Cross-field rule: only include='capacity' enables serial_number and time-window parameters.
        Returns GatewayClusterEnvelope; response_format selects concise or detailed cluster data.
        """
        try:
            includes = _validate_cluster_params(
                include,
                serial_number,
                time_range,
                start_time,
                end_time,
            )
            capacity_window = (
                _resolve_time_window(time_range or "last_1h", start_time, end_time)
                if "capacity" in includes
                else None
            )
            snapshot_includes = [
                value for value in includes if value != "capacity"
            ] or None

            async with api_context(ctx) as conn:
                raw = await asyncio.to_thread(
                    fetch_cluster_snapshot,
                    conn,
                    cluster_name,
                    snapshot_includes,
                )
                if raw and raw.get("members") and "capacity" in includes:
                    assert capacity_window is not None
                    start_at, end_at = capacity_window
                    capacity_raw = await asyncio.to_thread(
                        MonitoringGateways.get_cluster_capacity_trends,
                        central_conn=conn,
                        cluster_name=cluster_name,
                        serial_number=serial_number,
                        start_time=start_at,
                        end_time=end_at,
                        return_raw_response=True,
                    )
                    raw["capacity"] = _normalize_capacity_trends(capacity_raw)

            items = [GatewayCluster.from_api(raw)] if raw and raw.get("members") else []
            return build_envelope(
                GatewayClusterEnvelope,
                items,
                total=len(items),
                response_format=response_format,
            )
        except Exception as exc:
            raise_central_error(exc, "retrieving gateway cluster")
