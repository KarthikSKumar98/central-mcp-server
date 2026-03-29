from models import (
    EventCategoryCount,
    EventFilters,
    EventNameCount,
    EventSourceTypeCount,
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
