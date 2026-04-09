import asyncio
from typing import Literal

from fastmcp import Context, FastMCP

from constants import EVENT_LIMIT, TIME_RANGE
from models import CompactEventFilters, Event, EventFilters, PaginatedEvents
from tools import READ_ONLY
from utils.common import (
    FilterField,
    api_context,
    build_filters,
    format_tool_error,
)
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

RESPONSE_MODE = Literal["full", "compact"]

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


def register(mcp: FastMCP) -> None:
    """Register alert tools with the MCP server."""

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_events(
        ctx: Context,
        site_id: str,
        context_type: CONTEXT_TYPE = "SITE",
        context_identifier: str | None = None,
        event_id: str | None = None,
        category: str | None = None,
        source_type: str | None = None,
        time_range: TIME_RANGE = "last_1h",
        start_time: str | None = None,
        end_time: str | None = None,
        search: str | None = None,
        limit: int = EVENT_LIMIT,
        cursor: int | None = None,
    ) -> PaginatedEvents | str:
        """Retrieve events for a given context (site, device, or client) within a specified time range.

        Use central_get_events_count first to understand what event types and volumes exist before
        fetching full event records. The values for event_id, category, and source_type can be
        discovered from central_get_events_count output.

        Prefer applying event_id/category/source_type filters when possible to focus the returned
        events and improve troubleshooting context.

        To page through results, pass the `next_cursor` value from the previous response as `cursor`
        in the next call. When `next_cursor` is None, there are no more pages.

        Parameters
        ----------
        - site_id: Site ID to scope events to a specific site. Always required.
        - context_type: Optional context type to narrow within the site. Defaults to SITE.
          Allowed values: SITE, ACCESS_POINT, SWITCH, GATEWAY, WIRELESS_CLIENT,
          WIRED_CLIENT, BRIDGE.
        - context_identifier: Required only when context_type is not SITE.
          Use device serial number for device contexts or client MAC address for client contexts.
          Must be omitted when context_type is SITE.
        - event_id: Exact event type identifier to include. Supports comma-separated values.
          Find available event IDs via central_get_events_count.
        - category: Event category to include. Supports comma-separated values.
          Find available categories via central_get_events_count.
        - source_type: Source type to include (e.g., Access Point, Wireless Client).
          Supports comma-separated values.
          Find available source types via central_get_events_count.
        - time_range: Predefined time window. Allowed values: last_1h, last_6h, last_24h, last_7d,
          last_30d, today, yesterday. Ignored if both start_time and end_time are provided.
        - start_time: Start of the time window in RFC 3339 format (e.g. "2026-03-21T00:00:00.000Z").
          Overrides time_range when combined with end_time.
        - end_time: End of the time window in RFC 3339 format (e.g. "2026-03-21T23:59:59.999Z").
          Overrides time_range when combined with start_time.
        - search: Search events by name, serial number, host name, or MAC address. Restricted to
          metadata fields only; full-text search is not supported.
        - limit: Number of events per page (default 50, max 100).
        - cursor: Pagination cursor from a previous response's `next_cursor` field. Omit or
          pass None to start from the first page.

        WARNING: last_30d can match thousands of events. Use central_get_events_count first to
        assess volume, then page incrementally using cursor.

        Canonical calling patterns:
        - Site events: pass only site_id (or context_type="SITE" with no context_identifier).
        - Device/client events: pass site_id + context_type + context_identifier.

        """
        try:
            resolved_identifier = _resolve_context_identifier(
                context_type=context_type,
                context_identifier=context_identifier,
                site_id=site_id,
            )
        except ValueError as exc:
            return format_tool_error("fetching events", exc)

        async with api_context(ctx) as conn:
            try:
                start_at, end_at = _resolve_time_window(
                    time_range, start_time, end_time
                )
                filter_str = build_filters(
                    EVENT_FILTERS,
                    event_id=event_id,
                    category=category,
                    source_type=source_type,
                )

                query_params = {
                    "context-type": context_type,
                    "context-identifier": resolved_identifier,
                    "start-at": start_at,
                    "end-at": end_at,
                    "site-id": site_id,
                }
                if filter_str:
                    query_params["filter"] = filter_str
                if search:
                    query_params["search"] = search

                query_params["limit"] = limit
                if cursor is not None:
                    query_params["next"] = cursor

                response = await asyncio.to_thread(
                    conn.command,
                    api_method="GET",
                    api_path="network-troubleshooting/v1/events",
                    api_params=query_params,
                )
                if response["code"] != 200:
                    return format_tool_error("fetching events", response["msg"])
            except Exception as e:
                return format_tool_error("fetching events", e)

            msg = response["msg"]
            raw_events = msg.get("events", [])  # key is "events", not "items"
            try:
                return PaginatedEvents(
                    items=[Event(**e) for e in raw_events],
                    total=msg.get("total", 0),
                    next_cursor=msg.get("next"),
                )
            except Exception as e:
                return format_tool_error("parsing events", e)

    @mcp.tool(annotations=READ_ONLY)
    async def central_get_events_count(
        ctx: Context,
        site_id: str,
        context_type: CONTEXT_TYPE = "SITE",
        context_identifier: str | None = None,
        time_range: TIME_RANGE = "last_1h",
        start_time: str | None = None,
        end_time: str | None = None,
        response_mode: RESPONSE_MODE = "full",
    ) -> EventFilters | CompactEventFilters | str:
        """Return a breakdown of event counts for a context without fetching full event details.

        Use this before central_get_events to understand what types and volumes of events exist,
        avoiding the overhead of retrieving all event records.

        Parameters
        ----------
        - site_id: Site ID to scope events to a specific site. Always required.
        - context_type: Optional context type to narrow within the site. Defaults to SITE.
          Allowed values: SITE, ACCESS_POINT, SWITCH, GATEWAY, WIRELESS_CLIENT,
          WIRED_CLIENT, BRIDGE.
        - context_identifier: Required only when context_type is not SITE.
          Use device serial number for device contexts or client MAC address for client contexts.
          Must be omitted when context_type is SITE.
        - time_range: Predefined time window. Allowed values: last_1h, last_6h, last_24h, last_7d,
          last_30d, today, yesterday. Ignored if both start_time and end_time are provided.
        - start_time: Start of the time window in RFC 3339 format (e.g. "2026-03-21T00:00:00.000Z").
          Overrides time_range when combined with end_time.
        - end_time: End of the time window in RFC 3339 format (e.g. "2026-03-21T23:59:59.999Z").
          Overrides time_range when combined with start_time.
        - response_mode: Output shape for event filters. Use "compact" for an LLM-friendly
          ranked summary (event id/name pairs plus string lists), or "full" for per-item counts.

        Canonical calling patterns:
        - Site event counts: pass only site_id (or context_type="SITE" with no context_identifier).
        - Device/client event counts: pass site_id + context_type + context_identifier.

        Returns an EventFilters object: total event count plus breakdowns by event name, source
        type, and category in full mode. In compact mode, returns ranked lists of event names,
        source types, and categories.

        """
        try:
            resolved_identifier = _resolve_context_identifier(
                context_type=context_type,
                context_identifier=context_identifier,
                site_id=site_id,
            )
        except ValueError as exc:
            return format_tool_error("fetching event filters", exc)

        if response_mode not in ("full", "compact"):
            return format_tool_error(
                "fetching event filters",
                ValueError("response_mode must be one of: full, compact"),
            )
        async with api_context(ctx) as conn:
            try:
                start_at, end_at = _resolve_time_window(
                    time_range, start_time, end_time
                )
                response = await asyncio.to_thread(
                    conn.command,
                    api_method="GET",
                    api_path="network-troubleshooting/v1/event-filters",
                    api_params={
                        "context-type": context_type,
                        "context-identifier": resolved_identifier,
                        "start-at": start_at,
                        "end-at": end_at,
                        "site-id": site_id,
                    },
                )
                if response["code"] != 200:
                    return format_tool_error("fetching event filters", response["msg"])
            except Exception as e:
                return format_tool_error("fetching event filters", e)
            try:
                filters = clean_event_filters(response["msg"])
                if response_mode == "compact":
                    return compact_event_filters(filters)
                return filters
            except Exception as e:
                return format_tool_error("parsing event filters", e)
