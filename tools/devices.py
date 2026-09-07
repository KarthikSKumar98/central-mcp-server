import asyncio
from typing import Annotated, Literal

from fastmcp import Context, FastMCP
from pycentral.new_monitoring import (
    MonitoringAPs,
    MonitoringDevices,
    MonitoringSwitches,
)
from pycentral.new_monitoring.gateways import MonitoringGateways
from pydantic import Field

from constants import (
    GATEWAY_MAX_PAGE_SIZE,
    MAX_PAGE_SIZE,
    MAX_RESPONSE_ITEMS,
    SWITCH_DEPLOYMENT_VALUES,
    TIME_RANGE,
)
from models import (
    APDetail,
    Device,
    DeviceEnvelope,
    DeviceTrendsEnvelope,
    GatewayDetail,
    SwitchDetail,
    TrendSample,
)
from tools import READ_ONLY
from tools.gateway_monitoring import _normalize_temperature_trends
from utils.common import (
    FilterField,
    api_context,
    build_filters,
    lookup_inventory_device,
    normalize_sort_direction,
    stack_aware_serial,
)
from utils.cursor import (
    INVALID_CURSOR_MESSAGE,
    decode_cursor,
    decode_next_page,
    encode_cursor,
    hash_query,
)
from utils.devices import clean_device_data, process_device_status
from utils.envelope import build_envelope, raise_central_error
from utils.events import _resolve_time_window
from utils.monitoring import (
    AP_INCLUDES,
    GATEWAY_INCLUDES,
    GATEWAY_TREND_SCOPES,
    SWITCH_INCLUDES,
    SWITCH_TREND_SCOPES,
    fetch_snapshot,
    fetch_switch_snapshot,
    fetch_trends,
    normalize_switch_trends,
    resolve_switch_serial,
)

DEFAULT_DEVICE_LIMIT = 100
DEFAULT_MAX_POINTS = 100
DEVICE_TOOL_NAME = "central_get_devices"

DeviceDetailInclude = Literal[
    "radios",
    "ports",
    "interfaces",
    "vlans",
    "poe",
    "lag",
    "vsx",
    "stack_members",
    "hardware",
    "tunnels",
    "uplinks",
    "dhcp",
]

DEVICE_TYPE_FILTER_PARAMS: dict[str, frozenset[str]] = {
    "ap": frozenset(
        {
            "site_id",
            "site_name",
            "serial_number",
            "device_name",
            "device_status",
            "model",
            "firmware_version",
            "deployment",
            "cluster_id",
            "cluster_name",
        }
    ),
    "switch": frozenset(
        {"site_id", "site_name", "model", "device_status", "deployment"}
    ),
    "gateway": frozenset(
        {
            "site_id",
            "site_name",
            "serial_number",
            "device_name",
            "model",
            "device_status",
            "cluster_name",
        }
    ),
}

INVENTORY_DEVICE_TYPE_FAMILIES = {
    "ACCESS_POINT": "ap",
    "SWITCH": "switch",
    "GATEWAY": "gateway",
}

INVENTORY_FILTER_PARAMS = frozenset(
    {
        "site_id",
        "device_name",
        "serial_number",
        "device_status",
        "model",
        "device_function",
        "is_provisioned",
        "site_assigned",
    }
)

DEVICE_TYPE_INCLUDES: dict[str, frozenset[str]] = {
    "ap": frozenset(AP_INCLUDES),
    "switch": frozenset(SWITCH_INCLUDES),
    "gateway": frozenset({*GATEWAY_INCLUDES, "dhcp"}),
}

TREND_IDENTIFIER_PARAMS = frozenset(
    {
        "radio_number",
        "port_index",
        "interface_id",
        "uplink",
        "port_number",
        "tunnel_name",
        "link_tag",
    }
)

# (family, scope) -> identifier and metric rules preserved from the pre-fold
# AP, switch, and gateway trend tools.
DEVICE_TREND_RULES: dict[tuple[str, str], dict[str, object]] = {
    ("ap", "ap"): {
        "allowed": frozenset(),
        "required": frozenset(),
        "metric_required": True,
    },
    ("ap", "radio"): {
        "allowed": frozenset({"radio_number"}),
        "required": frozenset({"radio_number"}),
        "metric_required": True,
    },
    ("ap", "port"): {
        "allowed": frozenset({"port_index"}),
        "required": frozenset({"port_index"}),
        "metric_required": True,
    },
    ("switch", "hardware"): {
        "allowed": frozenset(),
        "required": frozenset(),
        "metric_required": False,
    },
    ("switch", "interface"): {
        "allowed": frozenset({"interface_id", "uplink"}),
        "required": frozenset(),
        "metric_required": False,
    },
    ("gateway", "gateway"): {
        "allowed": frozenset(),
        "required": frozenset(),
        "metric_required": True,
    },
    ("gateway", "port"): {
        "allowed": frozenset({"port_number"}),
        "required": frozenset({"port_number"}),
        "metric_required": True,
    },
    ("gateway", "tunnel"): {
        "allowed": frozenset({"tunnel_name"}),
        "required": frozenset({"tunnel_name"}),
        "metric_required": True,
    },
    ("gateway", "uplink"): {
        "allowed": frozenset({"link_tag"}),
        "required": frozenset({"link_tag"}),
        "metric_required": True,
    },
}

DEFAULT_TREND_SCOPES = {"ap": "ap", "switch": "hardware", "gateway": "gateway"}

DEVICE_FILTER_FIELDS: dict[str, FilterField] = {
    "site_id": FilterField("siteId"),
    "device_name": FilterField("deviceName"),
    "serial_number": FilterField("serialNumber"),
    "model": FilterField("model"),
    "device_function": FilterField("deviceFunction"),
    "is_provisioned": FilterField("isProvisioned"),
}

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

SWITCH_FILTER_FIELDS: dict[str, FilterField] = {
    "site_id": FilterField("siteId"),
    "site_name": FilterField("siteName"),
    "model": FilterField("model"),
    "status": FilterField("status", allowed_values=["Online", "Offline"]),
    "deployment": FilterField(
        "deployment", allowed_values=list(SWITCH_DEPLOYMENT_VALUES)
    ),
}

GATEWAY_FILTER_FIELDS: dict[str, FilterField] = {
    "site_id": FilterField("siteId"),
    "site_name": FilterField("siteName"),
    "serial_number": FilterField("serialNumber"),
    "device_name": FilterField("deviceName"),
    "model": FilterField("model"),
    "status": FilterField("status", allowed_values=["Online", "Offline"]),
    "cluster_name": FilterField("clusterName"),
}


def _monitoring_device(raw: dict, device_type: str) -> Device:
    """Normalize a family monitoring item to the shared inventory model."""
    serial_number = raw.get("serialNumber")
    if not serial_number:
        raise ValueError("Monitoring device payload is missing 'serialNumber'.")
    provisioned = raw.get("isProvisioned", True)
    if isinstance(provisioned, str):
        provisioned = provisioned.lower() == "yes"
    status = raw.get("status")
    return Device(
        serial_number=serial_number,
        mac_address=raw.get("macAddress", ""),
        device_type=device_type,
        model=raw.get("model", ""),
        part_number=raw.get("partNumber", ""),
        name=raw.get("deviceName", ""),
        function=raw.get("deviceFunction"),
        status=status.upper() if isinstance(status, str) else status,
        is_provisioned=bool(provisioned),
        role=raw.get("role") or raw.get("switchRole"),
        deployment=raw.get("deployment"),
        tier=raw.get("tier"),
        firmware_version=raw.get("firmwareVersion"),
        site_id=raw.get("siteId"),
        site_name=raw.get("siteName"),
        device_group_name=raw.get("deviceGroupName"),
        scope_id=raw.get("scopeId"),
        ipv4=raw.get("ipv4") or raw.get("ipAddress"),
        stack_id=raw.get("stackId"),
    )


def _resolve_monitoring_family(conn: object, serial_number: str) -> tuple[str, str]:
    """Resolve inventory deviceType and a stack-aware monitoring identifier."""
    device = lookup_inventory_device(conn, serial_number)
    if device is None:
        raise ValueError(
            f"Device family for serial '{serial_number}' could not be determined "
            "from Central inventory; pass device_type explicitly."
        )

    device_type = (device.get("deviceType") or "").upper()
    if device_type not in INVENTORY_DEVICE_TYPE_FAMILIES:
        raise ValueError(
            f"Unrecognised deviceType '{device_type}' for serial '{serial_number}'; "
            "pass device_type explicitly."
        )
    return (
        INVENTORY_DEVICE_TYPE_FAMILIES[device_type],
        stack_aware_serial(device, serial_number),
    )


def _normalize_status(device_status: str | None, *, upper: bool) -> str | None:
    if device_status is None:
        return None
    return device_status.upper() if upper else device_status.title()


def _device_cursor_tool(family: str) -> str:
    """Bind a device-list cursor to one monitoring family or inventory."""
    return f"{DEVICE_TOOL_NAME}:{family}"


def _validate_device_filter_params(
    device_type: str | None,
    filter_values: dict[str, object | None],
    *,
    sort: str | None,
) -> None:
    """Reject unsupported or exact-lookup-ignored parameters before API access."""
    serial_number = filter_values["serial_number"]
    device_name = filter_values["device_name"]
    if serial_number and device_name:
        raise ValueError(
            "Provide only one exact identifier: serial_number or device_name."
        )

    if device_type is None:
        supported = INVENTORY_FILTER_PARAMS
        family_description = "when device_type is omitted"
    else:
        supported = DEVICE_TYPE_FILTER_PARAMS.get(device_type)
        if supported is None:
            valid_types = ", ".join(DEVICE_TYPE_FILTER_PARAMS)
            raise ValueError(
                f"Invalid device_type='{device_type}'. Valid values: {valid_types}."
            )
        family_description = f"for device_type='{device_type}'"

    exact_param = (
        "serial_number" if serial_number else "device_name" if device_name else None
    )
    if exact_param is not None:
        for param, value in filter_values.items():
            if param not in {"serial_number", "device_name"} and value is not None:
                selected_type = device_type or "inventory"
                raise ValueError(
                    f"Parameter '{param}' cannot be combined with exact {exact_param} "
                    f"lookup for device_type='{selected_type}' because it would be ignored."
                )
        if sort is not None:
            selected_type = device_type or "inventory"
            raise ValueError(
                f"Parameter 'sort' cannot be combined with exact {exact_param} lookup "
                f"for device_type='{selected_type}' because it would be ignored."
            )
        return

    for param, value in filter_values.items():
        if value is not None and param not in supported:
            raise ValueError(
                f"Parameter '{param}' is not supported {family_description}."
            )


def _validate_device_trend_params(
    family: str,
    scope: str | None,
    metric: str | None,
    identifier_values: dict[str, object | None],
) -> str:
    """Validate folded trend parameters against the resolved family and scope."""
    selected_scope = scope or DEFAULT_TREND_SCOPES[family]
    rule = DEVICE_TREND_RULES.get((family, selected_scope))
    if rule is None:
        valid_scopes = ", ".join(
            scope_name
            for family_name, scope_name in DEVICE_TREND_RULES
            if family_name == family
        )
        raise ValueError(
            f"Invalid scope '{selected_scope}' for device_type='{family}'. "
            f"Valid scopes: {valid_scopes}."
        )

    allowed = rule["allowed"]
    required = rule["required"]
    for param, value in identifier_values.items():
        if value is not None and param not in allowed:
            raise ValueError(
                f"Parameter '{param}' is not supported for "
                f"device_type='{family}', scope='{selected_scope}'."
            )
    for param in required:
        if identifier_values[param] is None:
            raise ValueError(
                f"device_type='{family}', scope='{selected_scope}' requires '{param}'."
            )

    if rule["metric_required"]:
        if metric is None:
            family_name = "AP" if family == "ap" else "Gateway"
            raise ValueError(f"{family_name} trend scopes require metric.")
    elif metric is not None:
        raise ValueError(
            f"Scope '{selected_scope}' does not take a metric; all metrics are "
            "returned per sample."
        )

    return selected_scope


def _validate_detail_includes(family: str, includes: list[str] | None) -> list[str]:
    """Validate resolved-family include values before any detail resource fetch."""
    if includes is None:
        return []
    if not isinstance(includes, list):
        raise ValueError("Parameter 'include' must be a list of include values.")

    supported = DEVICE_TYPE_INCLUDES[family]
    for include in includes:
        if include not in supported:
            valid_values = ", ".join(sorted(supported))
            raise ValueError(
                f"include value '{include}' is not supported for "
                f"device_type='{family}'. Valid include values: {valid_values}."
            )
    return includes


def _trend_envelope(
    samples: list[dict],
    max_points: int,
    response_format: Literal["concise", "detailed"],
) -> DeviceTrendsEnvelope:
    items = [TrendSample(**sample) for sample in samples]
    envelope = build_envelope(
        DeviceTrendsEnvelope,
        items,
        total=len(items),
        ceiling=max_points,
        response_format=response_format,
    )
    envelope.meta.sampled = len(items) > max_points
    return envelope


def register(mcp: FastMCP) -> None:
    """Register the folded device-family tools with the MCP server."""

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_devices(
        ctx: Context,
        device_type: Literal["ap", "switch", "gateway"] | None = None,
        site_id: str | None = None,
        site_name: str | None = None,
        device_name: str | None = None,
        serial_number: str | None = None,
        device_status: Literal["ONLINE", "OFFLINE"] | None = None,
        model: str | None = None,
        device_function: str | None = None,
        is_provisioned: bool | None = None,
        site_assigned: bool | None = None,
        firmware_version: str | None = None,
        deployment: str | None = None,
        cluster_id: str | None = None,
        cluster_name: str | None = None,
        sort: str | None = None,
        limit: Annotated[int | None, Field(ge=1, le=MAX_PAGE_SIZE)] = None,
        cursor: str | None = None,
        response_format: Literal["concise", "detailed"] = "concise",
    ) -> DeviceEnvelope:
        """Retrieve filtered devices or one exact inventory match.

        Use for fleet browsing; device_type selects a family-specific monitoring view.
        Cross-field rules: family filters vary; exact serial_number or device_name rejects other filters and sort. Inventory status filtering can yield an empty page with next_cursor.
        Returns DeviceEnvelope; response_format selects concise or detailed items. Replay next_cursor as cursor with identical filters and the original limit.
        """
        try:
            filter_values = {
                "site_id": site_id,
                "site_name": site_name,
                "device_name": device_name,
                "serial_number": serial_number,
                "device_status": device_status,
                "model": model,
                "device_function": device_function,
                "is_provisioned": is_provisioned,
                "site_assigned": site_assigned,
                "firmware_version": firmware_version,
                "deployment": deployment,
                "cluster_id": cluster_id,
                "cluster_name": cluster_name,
            }
            _validate_device_filter_params(device_type, filter_values, sort=sort)

            exact_lookup = bool(serial_number or device_name)
            if not exact_lookup:
                family = device_type or "inventory"
                query_hash = hash_query(
                    {
                        "device_type": device_type,
                        **filter_values,
                        "sort": sort,
                    }
                )
                cursor_tool = _device_cursor_tool(family)
                page_size = limit if limit is not None else DEFAULT_DEVICE_LIMIT
                next_page = 1
                if cursor is not None:
                    decoded_cursor = decode_cursor(
                        cursor,
                        expected_tool=cursor_tool,
                        expected_query_hash=query_hash,
                    )
                    if decoded_cursor.page_size > MAX_PAGE_SIZE:
                        raise ValueError(INVALID_CURSOR_MESSAGE)
                    if limit is not None and limit != decoded_cursor.page_size:
                        raise ValueError("limit conflicts with the cursor page_size")
                    page_size = decoded_cursor.page_size
                    next_page = decode_next_page(decoded_cursor.position)
                if family == "gateway" and page_size > GATEWAY_MAX_PAGE_SIZE:
                    raise ValueError(
                        f"gateway page size max is {GATEWAY_MAX_PAGE_SIZE}"
                    )

            async with api_context(ctx) as conn:
                if exact_lookup:
                    filter_str = build_filters(
                        DEVICE_FILTER_FIELDS,
                        serial_number=serial_number,
                        device_name=device_name,
                    )
                    response = await asyncio.to_thread(
                        MonitoringDevices.get_device_inventory,
                        central_conn=conn,
                        filter_str=filter_str,
                    )
                    if "items" not in response:
                        raise ValueError("Unexpected API response: missing 'items'.")
                    raw_items = response["items"]
                    if len(raw_items) > 1:
                        raise ValueError(
                            "Multiple devices found; use serial_number for a unique match."
                        )
                    if device_type is not None and raw_items:
                        raw_device = raw_items[0]
                        raw_device_type = (
                            raw_device.get("deviceType")
                            if isinstance(raw_device, dict)
                            else None
                        )
                        normalized_device_type = (
                            raw_device_type.upper()
                            if isinstance(raw_device_type, str)
                            else None
                        )
                        actual_family = INVENTORY_DEVICE_TYPE_FAMILIES.get(
                            normalized_device_type
                        )
                        if actual_family != device_type:
                            raise ValueError(
                                "Exact lookup returned "
                                f"actual device_type='{actual_family or 'unknown'}', "
                                f"but requested device_type='{device_type}'."
                            )
                    items = clean_device_data(raw_items)
                    return build_envelope(
                        DeviceEnvelope,
                        items,
                        total=len(items),
                        ceiling=1,
                        response_format=response_format,
                    )
                elif device_type == "ap":
                    filter_str = build_filters(
                        AP_FILTER_FIELDS,
                        site_id=site_id,
                        site_name=site_name,
                        status=_normalize_status(device_status, upper=True),
                        model=model,
                        firmware_version=firmware_version,
                        deployment=deployment,
                        cluster_id=cluster_id,
                        cluster_name=cluster_name,
                    )
                    response = await asyncio.to_thread(
                        MonitoringAPs.get_aps,
                        central_conn=conn,
                        filter_str=filter_str,
                        sort=normalize_sort_direction(sort),
                        limit=page_size,
                        next_page=next_page,
                    )
                elif device_type == "switch":
                    filter_str = build_filters(
                        SWITCH_FILTER_FIELDS,
                        site_id=site_id,
                        site_name=site_name,
                        model=model,
                        status=_normalize_status(device_status, upper=False),
                        deployment=deployment,
                    )
                    response = await asyncio.to_thread(
                        MonitoringSwitches.get_switches,
                        central_conn=conn,
                        filter_str=filter_str,
                        sort=normalize_sort_direction(sort),
                        limit=page_size,
                        next_page=next_page,
                    )
                elif device_type == "gateway":
                    filter_str = build_filters(
                        GATEWAY_FILTER_FIELDS,
                        site_id=site_id,
                        site_name=site_name,
                        model=model,
                        status=_normalize_status(device_status, upper=False),
                        cluster_name=cluster_name,
                    )
                    response = await asyncio.to_thread(
                        MonitoringGateways.get_gateways,
                        central_conn=conn,
                        filter_str=filter_str,
                        sort=normalize_sort_direction(sort),
                        limit=page_size,
                        next_page=next_page,
                    )
                else:
                    filter_pairs = dict(
                        site_id=site_id,
                        model=model,
                        device_function=device_function,
                    )
                    if is_provisioned is not None:
                        filter_pairs["is_provisioned"] = (
                            "Yes" if is_provisioned else "No"
                        )
                    filter_str = build_filters(DEVICE_FILTER_FIELDS, **filter_pairs)
                    assigned = (
                        None
                        if site_assigned is None
                        else ("ASSIGNED" if site_assigned else "UNASSIGNED")
                    )
                    response = await asyncio.to_thread(
                        MonitoringDevices.get_device_inventory,
                        central_conn=conn,
                        filter_str=filter_str,
                        site_assigned=assigned,
                        sort=sort,
                        limit=page_size,
                        next=next_page,
                    )

                if not isinstance(response, dict):
                    raise ValueError("Unexpected devices response; expected an object.")
                raw_items = response.get("items", [])
                if not isinstance(raw_items, list):
                    raise ValueError(
                        "Unexpected devices response; expected an items list."
                    )

                if device_type == "ap":
                    items = [
                        _monitoring_device(raw, "ACCESS_POINT") for raw in raw_items
                    ]
                elif device_type == "switch":
                    items = [_monitoring_device(raw, "SWITCH") for raw in raw_items]
                elif device_type == "gateway":
                    items = [_monitoring_device(raw, "GATEWAY") for raw in raw_items]
                else:
                    selected_status = _normalize_status(device_status, upper=True)
                    if selected_status:
                        raw_items = process_device_status(raw_items, selected_status)
                    items = clean_device_data(raw_items)

                total = response.get("total")
                upstream_next = response.get("next")
                next_cursor = None
                if upstream_next not in (None, ""):
                    next_cursor = encode_cursor(
                        cursor_tool,
                        page_size,
                        {"upstream_next": str(upstream_next)},
                        query_hash,
                    )

                return build_envelope(
                    DeviceEnvelope,
                    items,
                    total=total,
                    total_available=total,
                    next_cursor=next_cursor,
                    ceiling=page_size,
                    response_format=response_format,
                )
        except Exception as exc:
            raise_central_error(exc, "retrieving devices")

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_device_details(
        ctx: Context,
        serial_number: str,
        device_type: Literal["ap", "switch", "gateway"] | None = None,
        include: list[DeviceDetailInclude] | None = None,
    ) -> APDetail | SwitchDetail | GatewayDetail:
        """Retrieve a typed detail snapshot for one device.

        Use after central_get_devices; pass its device_type for reliable routing.
        Cross-field rule: include values must match device_type; omitting device_type uses best-effort inventory resolution.
        Returns APDetail, SwitchDetail, or GatewayDetail for the resolved family.
        """
        try:
            includes = (
                _validate_detail_includes(device_type, include)
                if device_type is not None
                else None
            )
            async with api_context(ctx) as conn:
                if device_type is None:
                    family, effective_serial = await asyncio.to_thread(
                        _resolve_monitoring_family, conn, serial_number
                    )
                    includes = _validate_detail_includes(family, include)
                else:
                    family = device_type
                    effective_serial = serial_number
                    if family == "switch":
                        effective_serial = await asyncio.to_thread(
                            resolve_switch_serial, conn, serial_number
                        )

                if family == "ap":
                    raw = await asyncio.to_thread(
                        fetch_snapshot,
                        conn,
                        effective_serial,
                        includes,
                        includes_map=AP_INCLUDES,
                    )
                    if not raw:
                        raise ValueError(f"No AP found for serial '{serial_number}'.")
                    return APDetail.from_api(raw)

                if family == "switch":
                    raw = await asyncio.to_thread(
                        fetch_switch_snapshot, conn, effective_serial, includes
                    )
                    if not raw:
                        raise ValueError(
                            f"No switch found for serial '{serial_number}'."
                        )
                    return SwitchDetail.from_api(raw)

                gateway_includes = [value for value in includes if value != "dhcp"]
                raw = await asyncio.to_thread(
                    fetch_snapshot,
                    conn,
                    effective_serial,
                    gateway_includes,
                    monitor_cls=MonitoringGateways,
                    base_method="get_gateway_details",
                    includes_map=GATEWAY_INCLUDES,
                )
                if not raw:
                    raise ValueError(f"No gateway found for serial '{serial_number}'.")
                if "dhcp" in includes:
                    raw["dhcp_pools"] = await asyncio.to_thread(
                        MonitoringGateways.get_all_gateway_dhcp_pools,
                        central_conn=conn,
                        serial_number=effective_serial,
                    )
                    raw["dhcp_leases"] = await asyncio.to_thread(
                        MonitoringGateways.get_all_gateway_dhcp_clients,
                        central_conn=conn,
                        serial_number=effective_serial,
                    )
                return GatewayDetail.from_api(raw)
        except Exception as exc:
            raise_central_error(exc, "retrieving device details")

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_device_trends(
        ctx: Context,
        serial_number: str,
        device_type: Literal["ap", "switch", "gateway"] | None = None,
        scope: str | None = None,
        metric: str | None = None,
        radio_number: int | None = None,
        port_index: int | None = None,
        interface_id: str | None = None,
        uplink: bool | None = None,
        port_number: str | None = None,
        tunnel_name: str | None = None,
        link_tag: str | None = None,
        time_range: TIME_RANGE = "last_1h",
        start_time: str | None = None,
        end_time: str | None = None,
        max_points: Annotated[
            int, Field(ge=1, le=MAX_RESPONSE_ITEMS)
        ] = DEFAULT_MAX_POINTS,
        response_format: Literal["concise", "detailed"] = "concise",
    ) -> DeviceTrendsEnvelope:
        """Retrieve bounded time-series samples for one device.

        Use after central_get_devices; pass its device_type for reliable routing.
        Cross-field rules: scope, metric, identifiers, and time window are family-specific; omitting device_type uses best-effort inventory resolution.
        Returns DeviceTrendsEnvelope; response_format selects concise or detailed samples.
        """
        try:
            identifier_values = {
                "radio_number": radio_number,
                "port_index": port_index,
                "interface_id": interface_id,
                "uplink": uplink,
                "port_number": port_number,
                "tunnel_name": tunnel_name,
                "link_tag": link_tag,
            }
            start_at, end_at = _resolve_time_window(time_range, start_time, end_time)
            selected_scope = None
            if device_type is not None:
                selected_scope = _validate_device_trend_params(
                    device_type, scope, metric, identifier_values
                )
            async with api_context(ctx) as conn:
                if device_type is None:
                    family, effective_serial = await asyncio.to_thread(
                        _resolve_monitoring_family, conn, serial_number
                    )
                    selected_scope = _validate_device_trend_params(
                        family, scope, metric, identifier_values
                    )
                else:
                    family = device_type
                    effective_serial = serial_number
                    if family == "switch":
                        effective_serial = await asyncio.to_thread(
                            resolve_switch_serial, conn, serial_number
                        )

                if family == "ap":
                    raw = await asyncio.to_thread(
                        fetch_trends,
                        conn,
                        effective_serial,
                        selected_scope,
                        metric,
                        (start_at, end_at),
                        radio_number=radio_number,
                        port_index=port_index,
                    )
                    return _trend_envelope(raw, max_points, response_format)

                if family == "switch":
                    raw = await asyncio.to_thread(
                        fetch_trends,
                        conn,
                        effective_serial,
                        selected_scope,
                        metric,
                        (start_at, end_at),
                        extra_params={
                            "interface_id": interface_id,
                            "uplink": uplink,
                        },
                        monitor_cls=MonitoringSwitches,
                        scopes=SWITCH_TREND_SCOPES,
                    )
                    return _trend_envelope(
                        normalize_switch_trends(raw), max_points, response_format
                    )

                raw = await asyncio.to_thread(
                    fetch_trends,
                    conn,
                    effective_serial,
                    selected_scope,
                    metric,
                    (start_at, end_at),
                    sub_id={
                        "port": port_number,
                        "tunnel": tunnel_name,
                        "uplink": link_tag,
                    }.get(selected_scope),
                    monitor_cls=MonitoringGateways,
                    scopes=GATEWAY_TREND_SCOPES,
                )
                if (
                    metric == "hardware-temperature"
                    and raw
                    and isinstance(raw[0], dict)
                    and "graph" in raw[0]
                ):
                    raw = _normalize_temperature_trends(raw)
                return _trend_envelope(raw, max_points, response_format)
        except Exception as exc:
            raise_central_error(exc, "retrieving device trends")
