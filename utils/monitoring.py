"""Device-agnostic monitoring helpers for AP (and future switch/gateway) trend and snapshot fetching.

This module provides thin, synchronous wrappers around ``pycentral``'s
``MonitoringAPs`` class.  Tool-layer functions run these in
``asyncio.to_thread``; errors propagate as exceptions for the tool layer to
format via ``format_tool_error``.
"""

from __future__ import annotations

from pycentral.new_monitoring import MonitoringAPs

from constants import AP_TREND_METRICS, PORT_TREND_METRICS, RADIO_TREND_METRICS

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
    metric: str,
    window: tuple[str, str],
    *,
    radio_number: int | None = None,
    port_index: int | None = None,
    interface_type: str = "WIRELESS",
    monitor_cls=MonitoringAPs,
    scopes: dict[str, tuple[str, tuple[str, ...], str | None]] = AP_TREND_SCOPES,
) -> list[dict]:
    """Fetch time-series trend samples for an AP, radio, or port.

    Validates ``scope`` and ``metric`` before making any network call so that
    errors surface immediately with actionable messages.  The tool layer wraps
    this function in ``asyncio.to_thread``.

    Args:
        conn: Central API connection object.
        serial_number: AP serial number.
        scope: One of ``"ap"``, ``"radio"``, or ``"port"``.
        metric: Metric name valid for the given scope (see ``constants.py``).
        window: ``(start_at, end_at)`` tuple of RFC 3339 strings, e.g. from
            ``_resolve_time_window``.
        radio_number: Required when ``scope == "radio"``.
        port_index: Required when ``scope == "port"``.
        interface_type: One of ``WIRED``, ``WIRELESS``, ``LTE``.  Applied only
            when ``scope == "ap"`` and ``metric == "throughput"``.
        monitor_cls: ``MonitoringAPs`` class (injectable for tests).
        scopes: Scope routing map (injectable for tests).

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

    if metric not in valid_metrics:
        raise ValueError(
            f"Invalid metric '{metric}' for scope '{scope}'. "
            f"Valid metrics: {', '.join(valid_metrics)}."
        )

    if required_kwarg == "radio_number" and radio_number is None:
        raise ValueError("scope 'radio' requires 'radio_number'.")
    if required_kwarg == "port_index" and port_index is None:
        raise ValueError("scope 'port' requires 'port_index'.")

    kwargs: dict = {
        "central_conn": conn,
        "serial_number": serial_number,
        "metric": metric,
        "start_time": window[0],
        "end_time": window[1],
    }

    if scope == "radio":
        kwargs["radio_number"] = radio_number
    elif scope == "port":
        kwargs["port_index"] = port_index
    elif scope == "ap" and metric == "throughput":
        kwargs["interface_type"] = interface_type

    return getattr(monitor_cls, method_name)(**kwargs)
