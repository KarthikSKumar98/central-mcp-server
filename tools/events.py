import asyncio
from typing import Annotated, Literal

from fastmcp import Context, FastMCP
from pydantic import Field

from constants import EVENT_LIMIT, MAX_PAGE_SIZE, MAX_RESPONSE_ITEMS, TIME_RANGE
from models import (
    CompactEventFilters,
    Event,
    EventAttribute,
    EventEnvelope,
    EventFacetsEnvelope,
    EventFilters,
)
from tools import READ_ONLY
from utils.common import FilterField, api_context, build_filters
from utils.cursor import (
    INVALID_CURSOR_MESSAGE,
    decode_cursor,
    encode_cursor,
    hash_query,
)
from utils.envelope import build_envelope, raise_central_error
from utils.events import (
    _resolve_time_window,
    clean_event_filters,
    compact_event_filters,
)

CONTEXT_TYPE = Literal[
    "SITE",
    "ACCESS_POINT",
    "SWITCH",
    "GATEWAY",
    "WIRELESS_CLIENT",
    "WIRED_CLIENT",
    "BRIDGE",
]

EVENT_MODE = Literal["records", "facets"]
RESPONSE_MODE = Literal["full", "compact"]
EVENT_INCLUDE = Literal["attributes"]

# include="attributes" fetches per-event extra attributes one record at a time
# (the event-extra-attributes API is keyed per event — no bulk form). Cap the
# fan-out so a large records page cannot trigger hundreds of serial API calls.
EVENT_ATTRIBUTES_MAX = 25
EVENTS_TOOL_NAME = "central_get_events"

EVENT_FILTERS: dict[str, FilterField] = {
    "event_id": FilterField("eventId"),
    "category": FilterField("category"),
    "source_type": FilterField("sourceType"),
}

NON_SITE_CONTEXT_TYPES = (
    "ACCESS_POINT",
    "SWITCH",
    "GATEWAY",
    "WIRELESS_CLIENT",
    "WIRED_CLIENT",
    "BRIDGE",
)

# Mode -> caller parameters that route supports. Context and time-window inputs
# are common to both routes and therefore intentionally omitted from this map.
EVENT_MODE_PARAMS: dict[str, frozenset[str]] = {
    "records": frozenset(
        {
            "event_id",
            "category",
            "source_type",
            "search",
            "include",
            "limit",
            "cursor",
        }
    ),
    "facets": frozenset({"response_mode"}),
}


def _resolve_context_identifier(
    context_type: CONTEXT_TYPE,
    context_identifier: str | None,
    site_id: str,
) -> str:
    """Resolve and validate context identifier based on context type."""
    if context_type == "SITE":
        if context_identifier is not None:
            raise ValueError(
                "context_identifier must not be provided when context_type=SITE"
            )
        return site_id

    if not context_identifier:
        allowed = "/".join(NON_SITE_CONTEXT_TYPES)
        raise ValueError(
            f"context_identifier is required when context_type is {allowed}"
        )

    return context_identifier


def _validate_event_params(
    mode: str,
    mode_params: dict[str, object | None],
) -> None:
    """Reject parameters that the selected event route would ignore."""
    supported = EVENT_MODE_PARAMS.get(mode)
    if supported is None:
        valid_modes = ", ".join(EVENT_MODE_PARAMS)
        raise ValueError(f"mode must be one of: {valid_modes}")

    for param, value in mode_params.items():
        if value is not None and param not in supported:
            raise ValueError(
                f"Parameter '{param}' is not supported when mode='{mode}'."
            )

    response_mode = mode_params["response_mode"]
    if response_mode is not None and response_mode not in ("full", "compact"):
        raise ValueError("response_mode must be one of: full, compact")

    include = mode_params["include"]
    if include is not None and include != "attributes":
        raise ValueError("include must be 'attributes' when provided")

    if include == "attributes":
        limit = mode_params["limit"]
        if limit is not None and limit > EVENT_ATTRIBUTES_MAX:
            raise ValueError(
                f"limit must be <= {EVENT_ATTRIBUTES_MAX} when include='attributes' "
                "(each record triggers a separate attribute lookup)."
            )


def _event_query_params(
    *,
    context_type: str,
    context_identifier: str,
    site_id: str,
    start_at: str,
    end_at: str,
) -> dict[str, object]:
    """Build request parameters shared by event records and facets."""
    return {
        "context-type": context_type,
        "context-identifier": context_identifier,
        "start-at": start_at,
        "end-at": end_at,
        "site-id": site_id,
    }


def _require_success(response: dict, operation: str) -> dict:
    """Return a successful response payload or raise an actionable error."""
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


def _decoded_upstream_next(position: dict[str, str | int]) -> str:
    """Extract the upstream cursor token from a validated public cursor."""
    upstream_next = position.get("upstream_next")
    if not isinstance(upstream_next, str) or not upstream_next:
        raise ValueError(INVALID_CURSOR_MESSAGE)
    return upstream_next


async def _event_attributes(
    conn: object,
    event: Event,
    site_id: str,
) -> list[EventAttribute]:
    """Retrieve the documented extra attributes for one event record."""
    response = await asyncio.to_thread(
        conn.command,
        api_method="GET",
        api_path="network-troubleshooting/v1/event-extra-attributes",
        api_params={
            "event-identifier": event.event_identifier,
            "site-id": site_id,
            "time-at": event.time_at,
        },
    )
    payload = _require_success(response, "event attributes")
    raw_attributes = payload.get("eventExtraAttributes", [])
    if not isinstance(raw_attributes, list):
        raise ValueError(
            "Unexpected event attributes response; expected eventExtraAttributes list."
        )
    return [EventAttribute(**attribute) for attribute in raw_attributes]


def register(mcp: FastMCP) -> None:
    """Register the folded event tool with the MCP server."""

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_events(
        ctx: Context,
        site_id: str,
        mode: EVENT_MODE = "records",
        context_type: CONTEXT_TYPE = "SITE",
        context_identifier: str | None = None,
        event_id: str | None = None,
        category: str | None = None,
        source_type: str | None = None,
        time_range: TIME_RANGE = "last_1h",
        start_time: str | None = None,
        end_time: str | None = None,
        search: str | None = None,
        include: EVENT_INCLUDE | None = None,
        response_mode: RESPONSE_MODE | None = None,
        limit: Annotated[int | None, Field(ge=1, le=MAX_PAGE_SIZE)] = None,
        cursor: str | None = None,
        response_format: Literal["concise", "detailed"] = "concise",
    ) -> EventEnvelope | EventFacetsEnvelope:
        """Retrieve event records or aggregate facets for a site context.

        Use records for troubleshooting and facets to discover volume and filter values.
        Cross-field rules: record filters, search, include, limit, and cursor require records; response_mode requires facets. attributes enrichment caps the page.
        Returns EventEnvelope or EventFacetsEnvelope; response_format selects concise or detailed items. Replay next_cursor as cursor with the identical records query.
        """
        try:
            mode_params = {
                "event_id": event_id,
                "category": category,
                "source_type": source_type,
                "search": search,
                "include": include,
                "response_mode": response_mode,
                "limit": limit,
                "cursor": cursor,
            }
            _validate_event_params(mode, mode_params)
            resolved_identifier = _resolve_context_identifier(
                context_type=context_type,
                context_identifier=context_identifier,
                site_id=site_id,
            )
            start_at, end_at = _resolve_time_window(
                time_range,
                start_time,
                end_time,
            )
            common_params = _event_query_params(
                context_type=context_type,
                context_identifier=resolved_identifier,
                site_id=site_id,
                start_at=start_at,
                end_at=end_at,
            )

            async with api_context(ctx) as conn:
                if mode == "facets":
                    response = await asyncio.to_thread(
                        conn.command,
                        api_method="GET",
                        api_path="network-troubleshooting/v1/event-filters",
                        api_params=common_params,
                    )
                    payload = _require_success(response, "event facets")
                    facets: EventFilters | CompactEventFilters = clean_event_filters(
                        payload
                    )
                    if response_mode == "compact":
                        facets = compact_event_filters(facets)
                    return build_envelope(
                        EventFacetsEnvelope,
                        [facets],
                        total=facets.total,
                        response_format=response_format,
                    )

                filter_str = build_filters(
                    EVENT_FILTERS,
                    event_id=event_id,
                    category=category,
                    source_type=source_type,
                )
                default_limit = (
                    EVENT_ATTRIBUTES_MAX if include == "attributes" else EVENT_LIMIT
                )
                query_filters = {
                    "site_id": site_id,
                    "context_type": context_type,
                    "context_identifier": context_identifier,
                    "event_id": event_id,
                    "category": category,
                    "source_type": source_type,
                    "search": search,
                    "include": include,
                    "time_range": time_range,
                    "start_time": start_time,
                    "end_time": end_time,
                }
                query_hash = hash_query(query_filters)
                page_size = limit if limit is not None else default_limit
                upstream_next = None
                if cursor is not None:
                    decoded_cursor = decode_cursor(
                        cursor,
                        expected_tool=EVENTS_TOOL_NAME,
                        expected_query_hash=query_hash,
                    )
                    if decoded_cursor.page_size > MAX_PAGE_SIZE:
                        raise ValueError(INVALID_CURSOR_MESSAGE)
                    if limit is not None and limit != decoded_cursor.page_size:
                        raise ValueError("limit conflicts with the cursor page_size")
                    page_size = decoded_cursor.page_size
                    upstream_next = _decoded_upstream_next(decoded_cursor.position)

                query_params = {
                    **common_params,
                    "limit": page_size,
                }
                if filter_str:
                    query_params["filter"] = filter_str
                if search:
                    query_params["search"] = search
                if upstream_next is not None:
                    query_params["next"] = upstream_next

                response = await asyncio.to_thread(
                    conn.command,
                    api_method="GET",
                    api_path="network-troubleshooting/v1/events",
                    api_params=query_params,
                )
                payload = _require_success(response, "events")
                raw_events = payload.get("events", [])
                if not isinstance(raw_events, list):
                    raise ValueError(
                        "Unexpected events response; expected an events list."
                    )
                items = [Event(**event) for event in raw_events]
                if include == "attributes":
                    attribute_items = items[:EVENT_ATTRIBUTES_MAX]
                    for event in attribute_items:
                        event.attributes = await _event_attributes(conn, event, site_id)

            response_next = payload.get("next")
            if isinstance(response_next, bool) or not isinstance(
                response_next, (str, int)
            ):
                response_next = None
            else:
                response_next = str(response_next)
                if not response_next:
                    response_next = None

            next_cursor = None
            if response_next is not None:
                next_cursor = encode_cursor(
                    EVENTS_TOOL_NAME,
                    page_size,
                    {"upstream_next": response_next},
                    query_hash,
                )

            return build_envelope(
                EventEnvelope,
                items,
                total=payload.get("total", 0),
                next_cursor=next_cursor,
                ceiling=(
                    EVENT_ATTRIBUTES_MAX
                    if include == "attributes"
                    else MAX_RESPONSE_ITEMS
                ),
                response_format=response_format,
            )
        except Exception as exc:
            raise_central_error(exc, "retrieving events")
