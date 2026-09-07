import asyncio
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from urllib.parse import quote

from fastmcp import Context, FastMCP
from pydantic import Field

from constants import MAX_RESPONSE_ITEMS
from models import (
    ClientAnalyticsEnvelope,
    ClientAnalyticsItem,
    ClientMobilityEvent,
    ClientTrendSample,
    ClientUsageSample,
    OnboardingStageCounts,
    OnboardingStageDimensions,
    OnboardingStageReasons,
    OnboardingStageSummary,
    TopClientUsage,
    coerce_number,
)
from tools import READ_ONLY
from utils.common import api_context, compute_time_window, format_rfc3339
from utils.cursor import (
    INVALID_CURSOR_MESSAGE,
    decode_cursor,
    encode_cursor,
    hash_query,
)
from utils.envelope import build_envelope, raise_central_error

CLIENT_ANALYTICS_TOOL_NAME = "central_get_client_analytics"
CLIENT_ANALYTICS_MAX_LIMIT = 100
DEFAULT_MOBILITY_LIMIT = 20
DEFAULT_TOP_N = 5

USAGE_PATH = "network-monitoring/v1/clients-usage"
TOP_USAGE_PATH = "network-monitoring/v1/clients-topn-usage"
TREND_PATH = "network-monitoring/v1/clients-trend"
MOBILITY_PATH = "network-monitoring/v1/clients/{mac-address}/mobility-trail"
ONBOARDING_SUMMARY_PATH = "network-monitoring/v1/client-onboarding-stage/export"
ONBOARDING_REASONS_PATH = "network-monitoring/v1/client-onboarding-stage/reasons"
ONBOARDING_COUNT_PATH = "network-monitoring/v1/client-onboarding-stage/count"

CLIENT_ANALYTICS_METRIC = Literal["usage", "mobility", "onboarding"]
CLIENT_ANALYTICS_VIEW = Literal[
    "usage",
    "top",
    "trend",
    "summary",
    "reasons",
    "count",
]
CLIENT_ANALYTICS_TIME_RANGE = Literal[
    "last_1h",
    "last_3h",
    "last_6h",
    "last_24h",
    "last_7d",
    "last_30d",
    "today",
    "yesterday",
]
CLIENT_TREND_GROUP_BY = Literal[
    "TYPE",
    "ROLE",
    "VLAN",
    "WLAN",
    "RADIO",
    "SECURITY",
    "PROTOCOL",
]
CLIENT_TYPE = Literal["ALL", "WIRELESS", "WIRED", "REMOTE"]
ONBOARDING_STAGE = Literal["assoc", "auth", "dhcp", "dns"]
ONBOARDING_STATUS = Literal["FAILED", "DELAY", "SUCCESS"]
ONBOARDING_FIELD = Literal[
    "topclients",
    "topaccessdevices",
    "band",
    "topwlans",
    "topreasons",
    "topservers",
]
ONBOARDING_VIEW_TYPE = Literal["DEFAULT", "BY_CLIENT", "BY_ATTEMPTS"]

# Metric -> allowed views; None stands for "view omitted" and the first named
# view is that metric's default.
VIEWS_BY_METRIC: dict[str, tuple[str, ...]] = {
    "usage": ("usage", "top", "trend"),
    "mobility": (),
    "onboarding": ("summary", "reasons", "count"),
}


def _resolve_time_window(
    time_range: CLIENT_ANALYTICS_TIME_RANGE,
    start_time: str | None,
    end_time: str | None,
) -> tuple[str, str]:
    """Resolve a preset or complete custom time window to RFC 3339 timestamps."""
    if (start_time is None) != (end_time is None):
        raise ValueError(
            "start_time and end_time must be provided together, or both omitted."
        )
    if start_time is not None and end_time is not None:
        return start_time, end_time
    if time_range == "last_3h":
        end = datetime.now(timezone.utc)
        return format_rfc3339(end - timedelta(hours=3)), format_rfc3339(end)
    start, end = compute_time_window(time_range)
    return format_rfc3339(start), format_rfc3339(end)


def _resolved_view(
    metric: CLIENT_ANALYTICS_METRIC,
    view: CLIENT_ANALYTICS_VIEW | None,
) -> str:
    """Return the default sub-view and reject views from another metric."""
    if metric not in VIEWS_BY_METRIC:
        raise ValueError("metric must be one of: usage, mobility, onboarding")
    allowed = VIEWS_BY_METRIC[metric]
    if view is not None and view not in allowed:
        suffix = ", ".join(allowed) or "no view value"
        raise ValueError(f"view for metric='{metric}' must be one of: {suffix}")
    if not allowed:
        return metric
    return view or allowed[0]


def _validate_params(
    *,
    metric: CLIENT_ANALYTICS_METRIC,
    resolved_view: str,
    mac_address: str | None,
    site_name: str | None,
    serial_number: str | None,
    top_n: int | None,
    group_by: CLIENT_TREND_GROUP_BY | None,
    client_type: CLIENT_TYPE | None,
    stage: ONBOARDING_STAGE | None,
    status: ONBOARDING_STATUS | None,
    field: ONBOARDING_FIELD | None,
    version: str | None,
    view_type: ONBOARDING_VIEW_TYPE | None,
    limit: int | None,
    cursor: str | None,
) -> None:
    """Reject parameters that the selected endpoint would silently ignore."""
    if limit is not None and (
        isinstance(limit, bool) or limit < 1 or limit > CLIENT_ANALYTICS_MAX_LIMIT
    ):
        raise ValueError(f"limit must be between 1 and {CLIENT_ANALYTICS_MAX_LIMIT}")
    if top_n is not None and (
        isinstance(top_n, bool) or top_n < 1 or top_n > CLIENT_ANALYTICS_MAX_LIMIT
    ):
        raise ValueError(f"top_n must be between 1 and {CLIENT_ANALYTICS_MAX_LIMIT}")

    if metric == "mobility":
        if not mac_address:
            raise ValueError("mac_address is required when metric='mobility'")
        unsupported = {
            "serial_number": serial_number,
            "top_n": top_n,
            "group_by": group_by,
            "client_type": client_type,
            "stage": stage,
            "status": status,
            "field": field,
            "version": version,
            "view_type": view_type,
        }
    elif metric == "usage":
        unsupported = {
            "stage": stage,
            "status": status,
            "field": field,
            "version": version,
            "view_type": view_type,
            "limit": limit,
            "cursor": cursor,
        }
        if resolved_view != "usage" and mac_address is not None:
            unsupported["mac_address"] = mac_address
        if resolved_view != "top" and top_n is not None:
            unsupported["top_n"] = top_n
        if resolved_view != "trend":
            unsupported["group_by"] = group_by
            unsupported["client_type"] = client_type
    else:
        unsupported = {
            "site_name": site_name,
            "mac_address": mac_address,
            "serial_number": serial_number,
            "top_n": top_n,
            "group_by": group_by,
            "client_type": client_type,
            "limit": limit,
            "cursor": cursor,
        }
        if resolved_view == "summary":
            unsupported["status"] = status
            unsupported["field"] = field
        elif resolved_view == "reasons":
            unsupported["field"] = field

    for name, value in unsupported.items():
        if value is not None:
            raise ValueError(
                f"Parameter '{name}' is not supported for "
                f"metric='{metric}', view='{resolved_view}'."
            )


def _odata_value(value: str) -> str:
    """Quote a caller value for an OData string literal."""
    return f"'{value.replace(chr(39), chr(39) * 2)}'"


def _usage_filter(
    *,
    start_at: str,
    end_at: str,
    site_id: str | None,
    site_name: str | None,
    mac_address: str | None,
    serial_number: str | None,
) -> str:
    """Build the clients-usage endpoint's documented limited OData filter."""
    parts = [f"timestamp gt {start_at}", f"timestamp lt {end_at}"]
    for api_field, value in (
        ("siteId", site_id),
        ("siteName", site_name),
        ("macAddress", mac_address),
        ("serialNumber", serial_number),
    ):
        if value is not None:
            parts.append(f"{api_field} eq {_odata_value(value)}")
    return " and ".join(parts)


def _query_params(start_at: str, end_at: str, **optional: object) -> dict[str, object]:
    """Build kebab-case query parameters, omitting unset optional values."""
    params: dict[str, object] = {"start-at": start_at, "end-at": end_at}
    for name, value in optional.items():
        if value is not None:
            params[name.replace("_", "-")] = value
    return params


def _require_payload(response: object, operation: str) -> dict:
    """Return a successful object payload or raise an actionable error."""
    if not isinstance(response, dict):
        raise ValueError(f"Unexpected {operation} response; expected an object.")
    if response.get("code") != 200:
        raise RuntimeError(
            f"{operation} API returned {response.get('code')}: {response.get('msg')}"
        )
    payload = response.get("msg")
    if not isinstance(payload, dict):
        raise ValueError(
            f"Unexpected {operation} response; expected an object payload."
        )
    return payload


def _require_list(payload: dict, key: str, operation: str) -> list[dict]:
    """Read a list of object records from an upstream payload; null reads as empty."""
    raw_items = payload.get(key) or []
    if not isinstance(raw_items, list) or any(
        not isinstance(item, dict) for item in raw_items
    ):
        raise ValueError(
            f"Unexpected {operation} response; expected a {key} list of objects."
        )
    return raw_items


def _upstream_total(payload: dict, key: str, fallback: int) -> int:
    """Read an integer count from the payload, falling back to the item count."""
    value = payload.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return fallback


def _stage_summary(stage: dict) -> OnboardingStageSummary:
    """Fold one export stage's SUMMARY, FAILED, and DELAY rows into a model."""
    rows = {row.get("type"): row for row in stage.get("data") or []}
    summary = rows.get("SUMMARY", {})

    def dimensions(row: dict | None) -> OnboardingStageDimensions | None:
        if row is None:
            return None
        servers = (
            row.get("authTopServers")
            or row.get("dhcpTopServers")
            or row.get("dnsTopServers")
            or []
        )
        return OnboardingStageDimensions(
            clients=row.get("clients") or [],
            access_devices=row.get("accessDevice") or [],
            wlans=row.get("wlans") or [],
            band=row.get("band") or [],
            servers=servers,
        )

    failed = rows.get("FAILED")
    delayed = rows.get("DELAY")
    return OnboardingStageSummary(
        stage=stage.get("type", ""),
        attempts=summary.get("attempts"),
        failures=summary.get("failures"),
        success=summary.get("success"),
        delays=summary.get("delays"),
        failure_reasons=(failed or {}).get("topReasons") or [],
        delay_reasons=(delayed or {}).get("topReasons") or [],
        failed=dimensions(failed),
        delayed=dimensions(delayed),
    )


async def _get(
    conn: object,
    *,
    api_path: str,
    api_params: dict[str, object],
    operation: str,
) -> dict:
    """Call one read-only Central endpoint and return its object payload."""
    response = await asyncio.to_thread(
        conn.command,
        api_method="GET",
        api_path=api_path,
        api_params=api_params,
    )
    return _require_payload(response, operation)


def register(mcp: FastMCP) -> None:
    """Register the folded client analytics tool with the MCP server."""

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_client_analytics(
        ctx: Context,
        metric: CLIENT_ANALYTICS_METRIC,
        view: CLIENT_ANALYTICS_VIEW | None = None,
        site_id: str | None = None,
        site_name: str | None = None,
        mac_address: str | None = None,
        serial_number: str | None = None,
        time_range: CLIENT_ANALYTICS_TIME_RANGE = "last_24h",
        start_time: str | None = None,
        end_time: str | None = None,
        top_n: Annotated[
            int | None,
            Field(ge=1, le=CLIENT_ANALYTICS_MAX_LIMIT),
        ] = None,
        group_by: CLIENT_TREND_GROUP_BY | None = None,
        client_type: CLIENT_TYPE | None = None,
        stage: ONBOARDING_STAGE | None = None,
        status: ONBOARDING_STATUS | None = None,
        field: ONBOARDING_FIELD | None = None,
        version: str | None = None,
        view_type: ONBOARDING_VIEW_TYPE | None = None,
        limit: Annotated[
            int | None,
            Field(ge=1, le=CLIENT_ANALYTICS_MAX_LIMIT),
        ] = None,
        cursor: str | None = None,
        response_format: Literal["concise", "detailed"] = "concise",
    ) -> ClientAnalyticsEnvelope:
        """Retrieve client usage, mobility, or onboarding analytics.

        Use metric usage (views usage, top, trend) for byte usage, ranked clients, or client-count trends; mobility for one client's roam trail; onboarding (views summary, reasons, count) for per-stage assoc/auth/dhcp/dns experience.
        Cross-field rules: mobility requires mac_address and alone takes limit/cursor; top_n needs usage/top; stage, status, field, version, view_type need onboarding, and status/field only reasons/count.
        Returns ClientAnalyticsEnvelope; onboarding items are stages and summary sets overall_score (0-100). Replay next_cursor with identical filters.
        """
        try:
            resolved_view = _resolved_view(metric, view)
            _validate_params(
                metric=metric,
                resolved_view=resolved_view,
                mac_address=mac_address,
                site_name=site_name,
                serial_number=serial_number,
                top_n=top_n,
                group_by=group_by,
                client_type=client_type,
                stage=stage,
                status=status,
                field=field,
                version=version,
                view_type=view_type,
                limit=limit,
                cursor=cursor,
            )
            start_at, end_at = _resolve_time_window(time_range, start_time, end_time)

            async with api_context(ctx) as conn:
                items: list[ClientAnalyticsItem]

                if resolved_view == "usage":
                    payload = await _get(
                        conn,
                        api_path=USAGE_PATH,
                        api_params={
                            "filter": _usage_filter(
                                start_at=start_at,
                                end_at=end_at,
                                site_id=site_id,
                                site_name=site_name,
                                mac_address=mac_address,
                                serial_number=serial_number,
                            )
                        },
                        operation="client usage",
                    )
                    items = [
                        ClientUsageSample(
                            **sample,
                            keys=payload.get("keys", []),
                            interval=payload.get("interval", ""),
                        )
                        for sample in _require_list(payload, "samples", "client usage")
                    ]
                    return build_envelope(
                        ClientAnalyticsEnvelope,
                        items,
                        total=len(items),
                        ceiling=MAX_RESPONSE_ITEMS,
                        response_format=response_format,
                    )

                if resolved_view == "top":
                    page_size = top_n if top_n is not None else DEFAULT_TOP_N
                    params = _query_params(
                        start_at,
                        end_at,
                        site_id=site_id,
                        site_name=site_name,
                        serial_number=serial_number,
                        limit=page_size,
                    )
                    payload = await _get(
                        conn,
                        api_path=TOP_USAGE_PATH,
                        api_params=params,
                        operation="top client usage",
                    )
                    items = [
                        TopClientUsage(**item)
                        for item in _require_list(payload, "items", "top client usage")
                    ]
                    total = _upstream_total(payload, "count", len(items))
                    return build_envelope(
                        ClientAnalyticsEnvelope,
                        items,
                        total=total,
                        total_available=total,
                        ceiling=page_size,
                        response_format=response_format,
                    )

                if resolved_view == "trend":
                    params = _query_params(
                        start_at,
                        end_at,
                        site_id=site_id,
                        site_name=site_name,
                        serial_number=serial_number,
                        group_by=group_by or "TYPE",
                        type=client_type or "ALL",
                    )
                    payload = await _get(
                        conn,
                        api_path=TREND_PATH,
                        api_params=params,
                        operation="client trend",
                    )
                    items = [
                        ClientTrendSample(
                            **sample,
                            keys=payload.get("keys", []),
                            interval=payload.get("interval", ""),
                        )
                        for sample in _require_list(payload, "samples", "client trend")
                    ]
                    return build_envelope(
                        ClientAnalyticsEnvelope,
                        items,
                        total=len(items),
                        ceiling=MAX_RESPONSE_ITEMS,
                        response_format=response_format,
                    )

                if resolved_view == "mobility":
                    page_size = limit if limit is not None else DEFAULT_MOBILITY_LIMIT
                    query_hash = hash_query(
                        {
                            "metric": metric,
                            "mac_address": mac_address,
                            "site_id": site_id,
                            "site_name": site_name,
                            "time_range": time_range,
                            "start_time": start_time,
                            "end_time": end_time,
                        }
                    )
                    upstream_next: str | None = None
                    if cursor is not None:
                        decoded = decode_cursor(
                            cursor,
                            expected_tool=CLIENT_ANALYTICS_TOOL_NAME,
                            expected_query_hash=query_hash,
                        )
                        if decoded.page_size > CLIENT_ANALYTICS_MAX_LIMIT:
                            raise ValueError(INVALID_CURSOR_MESSAGE)
                        if limit is not None and limit != decoded.page_size:
                            raise ValueError(
                                "limit conflicts with the cursor page_size"
                            )
                        page_size = decoded.page_size
                        position = decoded.position.get("upstream_next")
                        if not isinstance(position, str):
                            raise ValueError(INVALID_CURSOR_MESSAGE)
                        upstream_next = position

                    params = _query_params(
                        start_at,
                        end_at,
                        site_id=site_id,
                        site_name=site_name,
                        limit=page_size,
                        next=upstream_next,
                    )
                    payload = await _get(
                        conn,
                        api_path=MOBILITY_PATH.replace(
                            "{mac-address}", quote(mac_address or "", safe="")
                        ),
                        api_params=params,
                        operation="client mobility",
                    )
                    items = [
                        ClientMobilityEvent(**item)
                        for item in _require_list(payload, "items", "client mobility")
                    ]
                    raw_next = payload.get("next")
                    if raw_next is not None and not isinstance(raw_next, str):
                        raise ValueError(
                            "Unexpected client mobility response; "
                            "expected next to be a string or null."
                        )
                    next_cursor = (
                        encode_cursor(
                            CLIENT_ANALYTICS_TOOL_NAME,
                            page_size,
                            {"upstream_next": raw_next},
                            query_hash,
                        )
                        if raw_next
                        else None
                    )
                    total = _upstream_total(payload, "total", len(items))
                    return build_envelope(
                        ClientAnalyticsEnvelope,
                        items,
                        total=total,
                        total_available=total,
                        next_cursor=next_cursor,
                        ceiling=page_size,
                        response_format=response_format,
                    )

                # Onboarding: one item per stage.
                params = _query_params(
                    start_at,
                    end_at,
                    site_id=site_id,
                    stage=stage,
                    version=version,
                    view_type=view_type,
                    status=status if resolved_view != "summary" else None,
                    field=field if resolved_view == "count" else None,
                )
                overall_score = None
                if resolved_view == "summary":
                    payload = await _get(
                        conn,
                        api_path=ONBOARDING_SUMMARY_PATH,
                        api_params=params,
                        operation="client onboarding summary",
                    )
                    items = [
                        _stage_summary(stage_row)
                        for stage_row in _require_list(
                            payload, "items", "client onboarding summary"
                        )
                    ]
                    score = coerce_number(payload.get("overallSuccessScore"))
                    overall_score = None if score is None else float(score)
                elif resolved_view == "reasons":
                    payload = await _get(
                        conn,
                        api_path=ONBOARDING_REASONS_PATH,
                        api_params=params,
                        operation="client onboarding reasons",
                    )
                    items = [
                        OnboardingStageReasons(**row)
                        for row in _require_list(
                            payload, "items", "client onboarding reasons"
                        )
                    ]
                else:
                    payload = await _get(
                        conn,
                        api_path=ONBOARDING_COUNT_PATH,
                        api_params=params,
                        operation="client onboarding count",
                    )
                    items = [
                        OnboardingStageCounts(**row)
                        for row in _require_list(
                            payload, "items", "client onboarding count"
                        )
                    ]

                envelope = build_envelope(
                    ClientAnalyticsEnvelope,
                    items,
                    total=len(items),
                    response_format=response_format,
                )
                envelope.overall_score = overall_score
                return envelope
        except Exception as exc:
            raise_central_error(exc, "retrieving client analytics")
