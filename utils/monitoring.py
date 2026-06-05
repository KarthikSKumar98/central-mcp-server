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
