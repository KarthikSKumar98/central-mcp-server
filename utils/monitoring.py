"""Device-agnostic monitoring helpers for AP/switch/gateway trend and snapshot fetching.

This module provides thin, synchronous wrappers around ``pycentral``'s
``new_monitoring`` classes.  Tool-layer functions run these in
``asyncio.to_thread``; errors propagate as exceptions for the tool layer to
format via ``format_tool_error``.
"""

from __future__ import annotations

from pycentral.new_monitoring import MonitoringAPs

from constants import AP_TREND_METRICS, PORT_TREND_METRICS, RADIO_TREND_METRICS
from utils.common import rfc3339_to_epoch

# ---------------------------------------------------------------------------
# Routing maps — method names stored as strings so that patches applied to
# ``MonitoringAPs.<method>`` are picked up at call time via ``getattr``.
# ---------------------------------------------------------------------------

# scope -> (method_name, valid_metrics, required_kwarg_name | None)
AP_TREND_SCOPES: dict[str, tuple[str, tuple[str, ...], str | None]] = {
    "ap": ("get_ap_trends", AP_TREND_METRICS, None),
    "radio": ("get_ap_radio_trends", RADIO_TREND_METRICS, "radio_number"),
    "port": ("get_ap_port_trends", PORT_TREND_METRICS, "port_index"),
}

# include key -> dedicated method name returning {items: [...]}
AP_INCLUDES: dict[str, str] = {
    "radios": "get_ap_radios",
    "ports": "get_ap_ports",
}


def fetch_snapshot(
    conn,
    serial_number: str,
    includes: list[str] | None = None,
    *,
    monitor_cls=MonitoringAPs,
    base_method: str = "get_ap_details",
    includes_map: dict[str, str] = AP_INCLUDES,
) -> dict | None:
    """Fetch an enriched AP detail snapshot.

    Calls ``base_method`` (default ``get_ap_details``) to retrieve the base
    AP dict, then optionally upgrades embedded summary sub-keys with richer
    dedicated payloads from ``includes_map``.

    Args:
        conn: Central API connection object.
        serial_number: AP serial number.
        includes: Optional list of keys to upgrade (e.g. ``["radios", "ports"]``).
            Keys not present in ``includes_map`` are silently ignored.
        monitor_cls: ``MonitoringAPs`` class (injectable for tests).
        base_method: Name of the base detail method on ``monitor_cls``.
        includes_map: Mapping of include key to dedicated method name.

    Returns:
        Enriched dict from ``base_method``, or whatever ``base_method`` returns
        when the AP is not found (falsy / non-dict).

    """
    base: dict = getattr(monitor_cls, base_method)(
        central_conn=conn, serial_number=serial_number
    )

    if not base or not isinstance(base, dict):
        return base  # type: ignore[return-value]

    for key in includes or []:
        if key not in includes_map:
            continue
        result = getattr(monitor_cls, includes_map[key])(
            central_conn=conn, serial_number=serial_number
        )
        if isinstance(result, dict) and "items" in result:
            base[key] = result["items"]
        elif isinstance(result, list):
            base[key] = result

    return base


def fetch_trends(
    conn,
    serial_number: str,
    scope: str,
    metric: str | None,
    window: tuple[str, str],
    *,
    radio_number: int | None = None,
    port_index: int | None = None,
    sub_id: object | None = None,
    extra_params: dict | None = None,
    epoch_window: bool = False,
    interface_type: str = "WIRELESS",
    monitor_cls=MonitoringAPs,
    scopes: dict[str, tuple[str, tuple[str, ...] | None, str | None]] = AP_TREND_SCOPES,
) -> list[dict]:
    """Fetch time-series trend samples for a device-level or sub-resource scope.

    Validates ``scope`` and ``metric`` before making any network call so that
    errors surface immediately with actionable messages.  The tool layer wraps
    this function in ``asyncio.to_thread``.

    Args:
        conn: Central API connection object.
        serial_number: Device serial number (or stack ID for switches).
        scope: A key of ``scopes`` (e.g. ``"ap"``, ``"radio"``, ``"port"``).
        metric: Metric name valid for the given scope (see ``constants.py``).
            Must be ``None`` for multi-metric scopes (``valid_metrics is None``
            in the scope tuple), where the API returns all metrics per sample.
        window: ``(start_at, end_at)`` tuple of RFC 3339 strings, e.g. from
            ``_resolve_time_window``.
        radio_number: Required when ``scope == "radio"``.
        port_index: Required when ``scope == "port"``.
        sub_id: Generic per-scope identifier for non-AP scopes whose required
            kwarg is neither ``radio_number`` nor ``port_index`` (e.g. a
            gateway ``port_number``, ``tunnel_name``, or ``link_tag``).
        extra_params: Optional extra kwargs forwarded to the pycentral method
            (``None`` values are dropped), e.g. switch ``interface_id``/``uplink``.
        epoch_window: When ``True``, convert the RFC 3339 window to epoch
            seconds (switch and gateway trend APIs expect epoch ints).
        interface_type: One of ``WIRED``, ``WIRELESS``, ``LTE``.  Applied only
            when ``scope == "ap"`` and ``metric == "throughput"``.
        monitor_cls: pycentral monitoring class (injectable for tests).
        scopes: Scope routing map of
            ``scope -> (method_name, valid_metrics | None, required_kwarg | None)``
            (injectable for tests).

    Returns:
        List of flat sample dicts, each containing ``"timestamp"`` and one or
        more dynamic metric keys as returned by ``pycentral``.

    Raises:
        ValueError: On invalid scope, invalid metric, or missing required id
            argument.

    """
    if scope not in scopes:
        raise ValueError(f"Invalid scope '{scope}'. Valid scopes: {', '.join(scopes)}.")

    method_name, valid_metrics, required_kwarg = scopes[scope]

    if valid_metrics is None:
        if metric is not None:
            raise ValueError(
                f"Scope '{scope}' does not take a metric; all metrics are "
                "returned per sample."
            )
    elif metric not in valid_metrics:
        raise ValueError(
            f"Invalid metric '{metric}' for scope '{scope}'. "
            f"Valid metrics: {', '.join(valid_metrics)}."
        )

    if required_kwarg is not None:
        sub_value = sub_id
        if required_kwarg == "radio_number" and radio_number is not None:
            sub_value = radio_number
        elif required_kwarg == "port_index" and port_index is not None:
            sub_value = port_index
        if sub_value is None:
            raise ValueError(f"scope '{scope}' requires '{required_kwarg}'.")

    start_at, end_at = window
    if epoch_window:
        start_at, end_at = rfc3339_to_epoch(start_at), rfc3339_to_epoch(end_at)

    kwargs: dict = {
        "central_conn": conn,
        "serial_number": serial_number,
        "start_time": start_at,
        "end_time": end_at,
    }

    if valid_metrics is not None:
        kwargs["metric"] = metric
    if required_kwarg is not None:
        kwargs[required_kwarg] = sub_value
    if scope == "ap" and metric == "throughput":
        kwargs["interface_type"] = interface_type
    if extra_params:
        kwargs.update({k: v for k, v in extra_params.items() if v is not None})

    return getattr(monitor_cls, method_name)(**kwargs)

# --- Gateway monitoring (a20) ---
from constants import (  # noqa: E402 — mid-file import intentional (append-only rule)
    GATEWAY_PORT_TREND_METRICS,
    GATEWAY_TREND_METRICS,
    GATEWAY_TUNNEL_TREND_METRICS,
    GATEWAY_UPLINK_TREND_METRICS,
)

# scope -> (method_name, valid_metrics, required_kwarg_name | None)
GATEWAY_TREND_SCOPES: dict[str, tuple[str, tuple[str, ...], str | None]] = {
    "gateway": ("get_gateway_trends", GATEWAY_TREND_METRICS, None),
    "port": ("get_gateway_port_trends", GATEWAY_PORT_TREND_METRICS, "port_number"),
    "tunnel": ("get_gateway_tunnel_trends", GATEWAY_TUNNEL_TREND_METRICS, "tunnel_name"),
    "uplink": ("get_gateway_uplink_trends", GATEWAY_UPLINK_TREND_METRICS, "link_tag"),
}

# include key -> dedicated method name for gateway sub-resources
GATEWAY_INCLUDES: dict[str, str] = {
    "ports": "get_all_gateway_ports",
    "tunnels": "get_all_gateway_tunnels",
    "uplinks": "get_gateway_uplinks",
    "vlans": "get_all_gateway_vlans",
}


def fetch_cluster_snapshot(
    conn,
    cluster_name: str,
    includes: list[str] | None = None,
    *,
    monitor_cls=None,
) -> dict | None:
    """Fetch a gateway cluster snapshot with optional include sub-resources.

    Always fetches cluster members (get_all_cluster_members) and the tunnel
    health summary (get_cluster_tunnel_summary, summary_type="health").

    Optionally fetches:
    - "tunnels": get_all_cluster_tunnels
    - "vlan_mismatch": get_cluster_vlan_mismatch
    - "connectivity": get_cluster_connectivity_graph

    Args:
        conn: Central API connection object.
        cluster_name: Name of the cluster.
        includes: Optional list of additional sub-resources to fetch.
        monitor_cls: MonitoringGateways class (injectable for tests).

    Returns:
        Dict with keys: cluster_name, members, tunnel_health_summary, and any
        requested includes. Returns None if cluster_name resolves to no members.

    """
    if monitor_cls is None:
        from pycentral.new_monitoring.gateways import MonitoringGateways as _MG
        monitor_cls = _MG

    members = monitor_cls.get_all_cluster_members(
        central_conn=conn, cluster_name=cluster_name
    )
    tunnel_health = monitor_cls.get_cluster_tunnel_summary(
        central_conn=conn, cluster_name=cluster_name, summary_type="health"
    )

    result: dict = {
        "cluster_name": cluster_name,
        "members": members if isinstance(members, list) else [],
        "tunnel_health_summary": tunnel_health,
    }

    _CLUSTER_INCLUDES: dict[str, tuple[str, dict]] = {
        "tunnels": ("get_all_cluster_tunnels", {}),
        "vlan_mismatch": ("get_cluster_vlan_mismatch", {}),
        "connectivity": ("get_cluster_connectivity_graph", {}),
    }

    for key in includes or []:
        if key not in _CLUSTER_INCLUDES:
            continue
        method_name, extra_kwargs = _CLUSTER_INCLUDES[key]
        data = getattr(monitor_cls, method_name)(
            central_conn=conn, cluster_name=cluster_name, **extra_kwargs
        )
        result[key] = data

    return result

# --- Switch monitoring (a20) ---
import ast

from pycentral.new_monitoring import MonitoringSwitches

from utils.common import (  # noqa: E402 — mid-file import intentional (append-only rule)
    lookup_inventory_device,
    stack_aware_serial,
)

# scope -> (method_name, valid_metrics | None, required_kwarg | None)
# Switch trend scopes return ALL metrics per sample (valid_metrics=None)
SWITCH_TREND_SCOPES: dict[str, tuple[str, tuple[str, ...] | None, str | None]] = {
    "hardware": ("get_switch_hardware_trends", None, None),
    "interface": ("get_switch_interface_trends", None, None),
}

# include key -> dedicated method name
SWITCH_INCLUDES: dict[str, str] = {
    "interfaces": "get_switch_interfaces",
    "vlans": "get_switch_vlans",
    "poe": "get_switch_interface_poe",
    "lag": "get_switch_lag",
    "vsx": "get_switch_vsx",
    "stack_members": "get_stack_members",
    "hardware": "get_switch_hardware_categories",
}


def _coerce_trend_values(sample: dict) -> dict:
    """Coerce string metric values in a trend sample to int or float.

    The switch trend APIs return all numeric metrics as strings
    (e.g. ``{"cpuUtilization": "2", "memoryUtilization": "35"}``).
    This helper converts each non-timestamp value to int if possible,
    then float, leaving other values as-is.
    """
    out: dict = {}
    for k, v in sample.items():
        if k == "timestamp" or not isinstance(v, str):
            out[k] = v
            continue
        try:
            out[k] = int(v)
            continue
        except (ValueError, TypeError):
            pass
        try:
            out[k] = float(v)
            continue
        except (ValueError, TypeError):
            pass
        out[k] = v
    return out


def _strip_sentinel(samples: list[dict]) -> list[dict]:
    """Remove the trailing sentinel sample that contains only a 'timestamp' key.

    Switch trend APIs always append a sparse final item with no metric values
    (just ``{"timestamp": "..."}``).  Strip it before returning to callers.
    """
    if samples and len(samples[-1]) == 1 and "timestamp" in samples[-1]:
        return samples[:-1]
    return samples


def normalize_switch_trends(samples: list[dict]) -> list[dict]:
    """Strip sentinel and coerce string metric values for switch trend samples."""
    return [_coerce_trend_values(s) for s in _strip_sentinel(samples)]


def resolve_switch_serial(conn, serial_number: str) -> str:
    """Resolve a switch serial to the identifier the monitoring API accepts.

    Stack member serials 404 on the monitoring API; the conductor serial and the
    stackId work. This transparently redirects any stack identifier to its
    stackId. On any lookup failure it returns the original serial unchanged so
    the caller's own error handling still applies.
    """
    try:
        device = lookup_inventory_device(conn, serial_number)
    except Exception:
        return serial_number
    return stack_aware_serial(device, serial_number)


def fetch_switch_snapshot(
    conn,
    serial_number: str,
    includes: list[str] | None = None,
    *,
    monitor_cls=MonitoringSwitches,
) -> dict | None:
    """Fetch an enriched switch detail snapshot with graceful include handling.

    Unlike ``fetch_snapshot`` for APs, switch includes are purely additive —
    ``get_switch_details`` embeds no sub-resources.  Each include key maps to a
    dedicated method whose result is stored on the base dict under that key.

    Special handling:
    - ``poe``: double-wrapped ``{response: {items, count}}`` — unwrapped to
      ``{items, count}`` before storing.
    - ``vsx``: raises on non-VSX platforms — caught and stored as
      ``{"error": "<msg>"}`` rather than propagating.
    - Other methods: if the result is a dict with ``"items"``, stored as-is.
      If a bare list, wrapped as ``{"items": result}``.  Failures stored as
      ``{"error": "<msg>"}``.

    Args:
        conn: Central API connection object.
        serial_number: Switch serial number or stack conductor serial.
        includes: Optional list of sub-resource keys (see ``SWITCH_INCLUDES``).
        monitor_cls: ``MonitoringSwitches`` class (injectable for tests).

    Returns:
        Enriched dict from ``get_switch_details``, or falsy/non-dict if not found.

    """
    base: dict = monitor_cls.get_switch_details(
        central_conn=conn, serial_number=serial_number
    )

    if not base or not isinstance(base, dict):
        return base  # type: ignore[return-value]

    for key in includes or []:
        method_name = SWITCH_INCLUDES.get(key)
        if not method_name:
            continue

        try:
            result = getattr(monitor_cls, method_name)(
                central_conn=conn, serial_number=serial_number
            )
        except Exception as exc:
            base[key] = {"error": str(exc)}
            continue

        # poe: double-wrapped {response: {items, count}}
        if key == "poe":
            if isinstance(result, dict) and "response" in result:
                base[key] = result["response"]
            else:
                base[key] = result
        elif isinstance(result, dict):
            base[key] = result
        elif isinstance(result, list):
            base[key] = {"items": result}
        else:
            base[key] = result

    # Normalize upLinkPorts in switchTrends from stringified Python list to real list
    for trend in base.get("switchTrends") or []:
        ul = trend.get("upLinkPorts")
        if isinstance(ul, str):
            try:
                trend["upLinkPorts"] = ast.literal_eval(ul)
            except (ValueError, SyntaxError):
                pass

    return base
