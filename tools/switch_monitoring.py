import asyncio
from typing import Literal

from fastmcp import Context, FastMCP
from pycentral.new_monitoring import MonitoringSwitches

from constants import SWITCH_DEPLOYMENT_VALUES, TIME_RANGE
from models import Switch, SwitchDetail, TrendSample
from tools import READ_ONLY
from utils.common import (
    FilterField,
    api_context,
    build_filters,
    format_tool_error,
    normalize_sort_direction,
)
from utils.events import _resolve_time_window
from utils.monitoring import (
    SWITCH_TREND_SCOPES,
    fetch_switch_snapshot,
    fetch_trends,
    normalize_switch_trends,
    resolve_switch_serial,
)

SWITCH_FILTER_FIELDS: dict[str, FilterField] = {
    "site_id": FilterField("siteId"),
    "site_name": FilterField("siteName"),
    "model": FilterField("model"),
    "status": FilterField("status", allowed_values=["Online", "Offline"]),
    "deployment": FilterField(
        "deployment", allowed_values=list(SWITCH_DEPLOYMENT_VALUES)
    ),
}


def register(mcp: FastMCP) -> None:
    """Register switch monitoring tools with the MCP server."""

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_switches(
        ctx: Context,
        site_id: str | None = None,
        site_name: str | None = None,
        model: str | None = None,
        status: Literal["Online", "Offline"] | None = None,
        deployment: Literal["Standalone", "Stack", "VSX"] | None = None,
        sort: str | None = None,
    ) -> list[Switch] | str:
        """Return a filtered list of switches from Central using typed filter parameters.

        Prefer this over broad inventory fetches when the request targets specific switches.
        Call central_get_summary first if you need to resolve site IDs.

        **Filterable fields** (5 only — these work as OData filters):
        - site_id, site_name, model, status, deployment.

        **Not filterable** (sortable only — passing these as filters causes a 500 error):
        - serialNumber, deviceName. Use sort to order by these fields; fetch the full list
          and filter client-side if you need exact-match lookup by serial or name.

        Status values are **title-case**: ``"Online"`` or ``"Offline"``.
        The filter will return no results if you use ``ONLINE``/``OFFLINE``.

        Each list item embeds a ``switchTrends`` snapshot (1 item) with current CPU,
        memory, PoE, power, temperature, and uplink port data.

        Parameters
        ----------
        - site_id: Exact site ID. Supports comma-separated values for multi-site queries.
        - site_name: Exact site name. Supports comma-separated values.
        - model: Switch model string (e.g. ``"CX-6300M"``). Supports comma-separated values.
        - status: Switch status. Title-case only. Allowed values: ``"Online"``, ``"Offline"``.
        - deployment: Deployment mode. Allowed values: ``"Standalone"``, ``"Stack"``, ``"VSX"``.
        - sort: Comma-separated sort expressions, for example ``"deviceName asc"``.
          Sortable fields: ``siteId``, ``model``, ``status``, ``deployment``,
          ``serialNumber``, ``deviceName``.

        """
        async with api_context(ctx) as conn:
            try:
                filter_str = build_filters(
                    SWITCH_FILTER_FIELDS,
                    site_id=site_id,
                    site_name=site_name,
                    model=model,
                    status=status,
                    deployment=deployment,
                )
                switches = await asyncio.to_thread(
                    MonitoringSwitches.get_all_switches,
                    central_conn=conn,
                    filter_str=filter_str,
                    sort=normalize_sort_direction(sort),
                )
            except Exception as e:
                return format_tool_error("fetching switches", e)

        if not switches:
            return "No switches found matching the specified criteria."
        try:
            return [Switch.from_api(sw) for sw in switches]
        except Exception as e:
            return format_tool_error("parsing switch data", e)

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_switch_details(
        ctx: Context,
        serial_number: str,
        include: list[
            Literal[
                "interfaces",
                "vlans",
                "poe",
                "lag",
                "vsx",
                "stack_members",
                "hardware",
            ]
        ]
        | None = None,
    ) -> SwitchDetail | str:
        """Return a detailed single-switch snapshot for the given serial number.

        Also accepts a **stack ID** (UUID) or **conductor serial** — for VSF/stack
        switches, querying the conductor's serial aggregates data across the whole stack.

        Unlike ``central_get_ap_details``, the base snapshot for switches embeds **no
        sub-resources** (no interfaces, VLANs, or PoE data).  Every ``include`` key is
        purely additive and triggers a separate API call.

        **Available includes** (all optional, all additive):

        - ``"interfaces"``: Port-level data from ``get_switch_interfaces``.
          Each port includes name, status, speed, duplex, VLAN mode, PoE status,
          uplink flag, and neighbour information.
        - ``"vlans"``: VLAN table from ``get_switch_vlans``.
          Each VLAN includes ID, name, type, status, tagged/untagged port lists.
        - ``"poe"``: PoE allocation from ``get_switch_interface_poe``.
          Returned as ``{items, count}`` (double-wrap already unwrapped).
          May have an empty items list on non-PoE switches.
        - ``"lag"``: LAG group configuration from ``get_switch_lag``.
          Empty on switches with no LACP groups configured.
        - ``"vsx"``: VSX peer info from ``get_switch_vsx``.
          On non-VSX platforms (standalone or stack), this is stored as
          ``{"error": "<msg>"}`` rather than raising.
        - ``"stack_members"``: Stack member details from ``get_stack_members``.
          Call using the conductor's serial; includes topology, member health,
          uptime, and VSF port-link status.
        - ``"hardware"``: Hardware category health from ``get_switch_hardware_categories``.
          One item per physical member (stacks produce multiple items).
          Covers CPU, memory, temperature, fans, and power supply health.

        Parameters
        ----------
        - serial_number: Serial number of the switch to query. Also accepts a stack
          conductor serial to get aggregated stack data. Required.
        - include: Optional list of sub-resources to fetch alongside the base detail.
          Allowed values: ``"interfaces"``, ``"vlans"``, ``"poe"``, ``"lag"``,
          ``"vsx"``, ``"stack_members"``, ``"hardware"``.

        """
        async with api_context(ctx) as conn:
            try:
                effective_serial = await asyncio.to_thread(
                    resolve_switch_serial, conn, serial_number
                )
                raw = await asyncio.to_thread(
                    fetch_switch_snapshot, conn, effective_serial, include
                )
            except Exception as e:
                return format_tool_error("fetching switch details", e)
        if not raw:
            return f"No switch found for serial number '{serial_number}'."
        try:
            return SwitchDetail.from_api(raw)
        except Exception as e:
            return format_tool_error("parsing switch details", e)

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_switch_trends(
        ctx: Context,
        serial_number: str,
        scope: Literal["hardware", "interface"] = "hardware",
        interface_id: str | None = None,
        uplink: bool | None = None,
        time_range: TIME_RANGE = "last_1h",
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> list[TrendSample] | str:
        """Return time-series trend samples for a switch (hardware or interface scope).

        Unlike ``central_get_ap_trends``, **no ``metric`` parameter is needed** —
        the switch trend APIs always return all metrics for every sample.

        **Divergence from AP trends**: The AP trend tool accepts a single ``metric``
        parameter because each AP trend call fetches one metric at a time.  Switch
        trend APIs return the full metric set per sample in a single call, so there
        is no metric selector.

        **Available scopes and their metric keys:**

        ``scope="hardware"`` (default) — hardware health over time:
        - ``cpuUtilization`` (int, %)
        - ``memoryUtilization`` (int, %)
        - ``systemTemperature`` (int/float)
        - ``poeAvailable`` (int/float, watts)
        - ``poeConsumption`` (int/float, watts)
        - ``powerConsumption`` (int/float, watts)
        - ``totalPowerConsumption`` (int/float, watts)
        - ``serialNumber`` (str, present in detail trend)

        ``scope="interface"`` — interface throughput and error counters:
        - ``rxBytes`` (int)
        - ``txBytes`` (int)
        - ``inErrors`` (int)
        - ``outErrors`` (int)
        - ``inDiscards`` (int)
        - ``outDiscards`` (int)
        - ``inFcs`` (int)
        - ``inCrcErrors`` (int)
        - ``inFragmented`` (int)
        - ``outCollision`` (int)
        - ``inRunts`` (int)
        - ``inGiants`` (int)

        All metric values are coerced from strings to numbers before returning.
        A trailing sparse sentinel sample (timestamp-only) is automatically stripped.
        Granularity is 5-minute buckets; a 1-hour window yields approximately 11 samples.

        The ``interface_id`` must match the ``id`` field from ``central_get_switch_details``
        with ``include=["interfaces"]`` (e.g. ``"Gi1/0/1"``), **not** the ``alias``
        (e.g. ``"GigabitEthernet1/0/1"``).

        NOTE (``scope="interface"``): Always specify either ``interface_id`` or
        ``uplink=True``.  If neither is provided, the API returns an all-interfaces
        aggregate whose behavior is not guaranteed and may show anomalous values.
        Specify one for deterministic per-port or uplink results.

        Time window: ``start_time`` + ``end_time`` (RFC 3339) override ``time_range``
        when both are supplied.  Otherwise ``time_range`` selects a named window
        relative to now.

        Parameters
        ----------
        - serial_number: Serial number of the switch to query. Required.
        - scope: Trend scope. Allowed values: ``"hardware"`` (default), ``"interface"``.
        - interface_id: Interface short ID (e.g. ``"Gi1/0/1"``). Scopes interface
          trends to a single port. Only valid when ``scope="interface"``.
        - uplink: When ``True``, limits interface trends to uplink ports only.
          Only valid when ``scope="interface"``.
        - time_range: Predefined time window. Allowed values: last_1h, last_6h,
          last_24h, last_7d, last_30d, today, yesterday. Ignored when both
          ``start_time`` and ``end_time`` are provided.
        - start_time: Start of the time window in RFC 3339 format
          (e.g. ``"2026-06-05T21:02:34.000Z"``). Overrides ``time_range`` when
          combined with ``end_time``.
        - end_time: End of the time window in RFC 3339 format
          (e.g. ``"2026-06-05T22:02:34.000Z"``). Overrides ``time_range`` when
          combined with ``start_time``.

        """
        start_at, end_at = _resolve_time_window(time_range, start_time, end_time)
        async with api_context(ctx) as conn:
            try:
                effective_serial = await asyncio.to_thread(
                    resolve_switch_serial, conn, serial_number
                )
                raw = await asyncio.to_thread(
                    fetch_trends,
                    conn,
                    effective_serial,
                    scope,
                    None,
                    (start_at, end_at),
                    extra_params={
                        "interface_id": interface_id,
                        "uplink": uplink,
                    },
                    monitor_cls=MonitoringSwitches,
                    scopes=SWITCH_TREND_SCOPES,
                )
            except ValueError as e:  # validation: invalid scope
                return format_tool_error("validating switch trend request", e)
            except Exception as e:
                return format_tool_error("fetching switch trends", e)

        if not raw:
            return f"No {scope} trend data found for serial number '{serial_number}'."
        try:
            normalized = normalize_switch_trends(raw)
        except Exception as e:
            return format_tool_error("parsing switch trends", e)
        if not normalized:
            return f"No {scope} trend data found for serial number '{serial_number}'."
        try:
            return [TrendSample(**sample) for sample in normalized]
        except Exception as e:
            return format_tool_error("parsing switch trends", e)
