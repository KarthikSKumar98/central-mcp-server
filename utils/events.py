from models import (
    CompactEventName,
    CompactEventFilters,
    EventCategoryCount,
    EventFilters,
    EventNameCount,
    EventSourceTypeCount,
)
from utils.common import (
    compute_time_window,
    format_rfc3339,
)


def clean_event_filters(msg: dict) -> EventFilters:
    """Transform raw event-filters API response into a structured EventFilters model."""
    categories = [
        EventCategoryCount(category=c["category"], count=c["count"])
        for c in msg.get("categories", [])
    ]
    return EventFilters(
        total=sum(c.count for c in categories),
        event_names=[
            EventNameCount(
                event_id=e["eventId"], event_name=e["eventName"], count=e["count"]
            )
            for e in msg.get("eventNames", [])
        ],
        source_types=[
            EventSourceTypeCount(source_type=s["sourceType"], count=s["count"])
            for s in msg.get("sourceTypes", [])
        ],
        categories=categories,
    )


def compact_event_filters(filters: EventFilters) -> CompactEventFilters:
    """Convert EventFilters into a compact, LLM-friendly ranked representation."""
    ranked_event_names = sorted(
        filters.event_names, key=lambda item: (-item.count, item.event_name, item.event_id)
    )
    ranked_source_types = sorted(
        filters.source_types, key=lambda item: (-item.count, item.source_type)
    )
    ranked_categories = sorted(
        filters.categories, key=lambda item: (-item.count, item.category)
    )
    return CompactEventFilters(
        total=filters.total,
        event_names=[
            CompactEventName(event_id=item.event_id, event_name=item.event_name)
            for item in ranked_event_names
        ],
        source_types=[item.source_type for item in ranked_source_types],
        categories=[item.category for item in ranked_categories],
    )


def _resolve_time_window(
    time_range: str,
    start_time: str | None,
    end_time: str | None,
) -> tuple[str, str]:
    """Return (start_at, end_at) as RFC 3339 strings.

    If both start_time and end_time are provided, use them as-is.
    Otherwise compute the window from the time_range preset.
    """
    if start_time and end_time:
        return start_time, end_time
    start_dt, end_dt = compute_time_window(time_range)
    return format_rfc3339(start_dt), format_rfc3339(end_dt)
