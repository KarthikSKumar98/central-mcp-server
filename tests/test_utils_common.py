import pytest

from utils.common import FilterField, build_odata_filter

FREE_FIELD = FilterField("myField")
ENUM_FIELD = FilterField("status", ["Active", "Inactive", "Pending"])


def test_empty_pairs_returns_none():
    assert build_odata_filter([]) is None


def test_single_free_text_field():
    result = build_odata_filter([(FREE_FIELD, "hello")])
    assert result == "myField eq 'hello'"


def test_comma_value_uses_in():
    result = build_odata_filter([(FREE_FIELD, "a,b")])
    assert result == "myField in ('a', 'b')"


def test_enum_valid_single():
    result = build_odata_filter([(ENUM_FIELD, "Active")])
    assert result == "status eq 'Active'"


def test_enum_invalid_single_raises():
    with pytest.raises(ValueError) as exc_info:
        build_odata_filter([(ENUM_FIELD, "BOGUS")])
    assert "BOGUS" in str(exc_info.value)
    assert "status" in str(exc_info.value)


def test_enum_valid_comma():
    result = build_odata_filter([(ENUM_FIELD, "Active,Inactive")])
    assert result == "status in ('Active', 'Inactive')"


def test_enum_comma_with_one_invalid_raises():
    with pytest.raises(ValueError) as exc_info:
        build_odata_filter([(ENUM_FIELD, "Active,BOGUS")])
    assert "BOGUS" in str(exc_info.value)


def test_multiple_fields_joined_with_and():
    field_a = FilterField("fieldA")
    field_b = FilterField("fieldB")
    result = build_odata_filter([(field_a, "x"), (field_b, "y")])
    assert result == "fieldA eq 'x' and fieldB eq 'y'"


def test_whitespace_in_comma_value_stripped():
    result = build_odata_filter([(FREE_FIELD, "a, b")])
    assert result == "myField in ('a', 'b')"


# ---------------------------------------------------------------------------
# compute_time_window
# ---------------------------------------------------------------------------
from datetime import timedelta, timezone

from utils.common import compute_time_window


def test_compute_time_window_last_1h():
    start, end = compute_time_window("last_1h")
    assert end - start == timedelta(hours=1)
    assert end.tzinfo == timezone.utc


def test_compute_time_window_last_6h():
    start, end = compute_time_window("last_6h")
    assert end - start == timedelta(hours=6)


def test_compute_time_window_last_24h():
    start, end = compute_time_window("last_24h")
    assert end - start == timedelta(hours=24)


def test_compute_time_window_last_7d():
    start, end = compute_time_window("last_7d")
    assert end - start == timedelta(days=7)


def test_compute_time_window_last_30d():
    start, end = compute_time_window("last_30d")
    assert end - start == timedelta(days=30)


def test_compute_time_window_today_starts_at_midnight():
    start, end = compute_time_window("today")
    assert start.hour == 0
    assert start.minute == 0
    assert start.second == 0
    assert start.microsecond == 0
    assert start.tzinfo == timezone.utc


def test_compute_time_window_yesterday_full_day():
    start, end = compute_time_window("yesterday")
    assert start.hour == 0 and start.minute == 0 and start.second == 0
    assert end.hour == 23 and end.minute == 59 and end.second == 59
    assert end.microsecond == 999999
    assert start.date() == end.date()


def test_compute_time_window_invalid_raises():
    with pytest.raises(ValueError):
        compute_time_window("last_100y")


# ---------------------------------------------------------------------------
# paginated_fetch
# ---------------------------------------------------------------------------
from unittest.mock import MagicMock

from utils.common import paginated_fetch


def _page(items, next_cursor=None, total=None):
    """Build a fake conn.command response."""
    if total is None:
        total = len(items)
    return {"code": 200, "msg": {"items": items, "total": total, "next": next_cursor}}


def test_paginated_fetch_single_page():
    conn = MagicMock()
    conn.command.return_value = _page([{"id": 1}])
    result = paginated_fetch(conn, "some/path", limit=100)
    assert result == [{"id": 1}]
    conn.command.assert_called_once_with(
        api_method="GET", api_path="some/path", api_params={"limit": 100, "next": 1}
    )


def test_paginated_fetch_raises_on_non_200():
    conn = MagicMock()
    conn.command.return_value = {"code": 500, "msg": "Internal Server Error"}
    with pytest.raises(Exception, match="API error 500"):
        paginated_fetch(conn, "some/path", limit=10)


def test_paginated_fetch_multi_page_accumulates_items():
    conn = MagicMock()
    conn.command.side_effect = [
        _page([{"id": 1}], next_cursor=2, total=2),
        _page([{"id": 2}], next_cursor=None, total=2),
    ]
    result = paginated_fetch(conn, "some/path", limit=1)
    assert result == [{"id": 1}, {"id": 2}]


def test_paginated_fetch_empty_result():
    conn = MagicMock()
    conn.command.return_value = _page([], total=0)
    result = paginated_fetch(conn, "some/path", limit=100)
    assert result == []


def test_paginated_fetch_passes_additional_params():
    conn = MagicMock()
    conn.command.return_value = _page([])
    paginated_fetch(conn, "some/path", limit=50, additional_params={"filter": "x eq 'y'"})
    assert conn.command.call_args.kwargs["api_params"]["filter"] == "x eq 'y'"
    assert conn.command.call_args.kwargs["api_params"]["limit"] == 50


# ---------------------------------------------------------------------------
# normalize_sort_direction
# ---------------------------------------------------------------------------
from utils.common import normalize_sort_direction


def test_normalize_sort_direction_none_passthrough():
    assert normalize_sort_direction(None) is None


def test_normalize_sort_direction_empty_passthrough():
    assert normalize_sort_direction("") == ""


def test_normalize_sort_direction_asc_uppercased():
    assert normalize_sort_direction("deviceName asc") == "deviceName ASC"


def test_normalize_sort_direction_desc_uppercased():
    assert normalize_sort_direction("model desc") == "model DESC"


def test_normalize_sort_direction_already_uppercase():
    assert normalize_sort_direction("deviceName ASC") == "deviceName ASC"


def test_normalize_sort_direction_mixed_case():
    assert normalize_sort_direction("deviceName Asc") == "deviceName ASC"


def test_normalize_sort_direction_multiple_exprs():
    result = normalize_sort_direction("deviceName asc, model desc")
    assert result == "deviceName ASC, model DESC"


def test_normalize_sort_direction_field_only_no_direction():
    """A sort expression with no direction token is left unchanged."""
    assert normalize_sort_direction("deviceName") == "deviceName"


def test_normalize_sort_direction_extra_whitespace():
    """Extra surrounding whitespace in each expression is handled."""
    result = normalize_sort_direction("  deviceName   asc  ,  model   desc  ")
    assert result == "deviceName ASC, model DESC"


# ---------------------------------------------------------------------------
# lookup_inventory_device / stack_aware_serial  (stack identifier resolution)
# ---------------------------------------------------------------------------
from unittest.mock import patch

from utils.common import lookup_inventory_device, stack_aware_serial

_STACK_MEMBER = {
    "serialNumber": "SG39KN419Z",
    "stackId": "f91f11e4-ca19-4b1a-89b7-0a7130f65ad0",
    "deployment": "Stack",
    "role": "Member",
    "deviceType": "SWITCH",
    "model": "6300",
    "status": "ONLINE",
}
_STANDALONE = {
    "serialNumber": "CN0000001",
    "stackId": None,
    "deployment": "Standalone",
    "deviceType": "SWITCH",
    "model": "6300",
    "status": "ONLINE",
}


def test_lookup_inventory_device_found_by_serial():
    """A serial that matches on the first (serialNumber) query returns that record
    and never issues the stackId fallback query.
    """
    with patch("utils.common.MonitoringDevices") as md:
        md.get_all_device_inventory.return_value = [_STACK_MEMBER]
        result = lookup_inventory_device("conn", "SG39KN419Z")
    assert result == _STACK_MEMBER
    md.get_all_device_inventory.assert_called_once_with(
        central_conn="conn", filter_str="serialNumber eq 'SG39KN419Z'"
    )


def test_lookup_inventory_device_falls_back_to_stack_id():
    """When the serialNumber query misses, the stackId query is tried next."""
    stack_id = "f91f11e4-ca19-4b1a-89b7-0a7130f65ad0"
    with patch("utils.common.MonitoringDevices") as md:
        md.get_all_device_inventory.side_effect = [[], [_STACK_MEMBER]]
        result = lookup_inventory_device("conn", stack_id)
    assert result == _STACK_MEMBER
    assert md.get_all_device_inventory.call_count == 2
    second_call = md.get_all_device_inventory.call_args_list[1]
    assert second_call.kwargs["filter_str"] == f"stackId eq '{stack_id}'"


def test_lookup_inventory_device_returns_none_when_unmatched():
    with patch("utils.common.MonitoringDevices") as md:
        md.get_all_device_inventory.return_value = []
        result = lookup_inventory_device("conn", "NOPE")
    assert result is None
    assert md.get_all_device_inventory.call_count == 2


def test_stack_aware_serial_returns_stack_id_for_stack_device():
    assert (
        stack_aware_serial(_STACK_MEMBER, "SG39KN419Z")
        == "f91f11e4-ca19-4b1a-89b7-0a7130f65ad0"
    )


def test_stack_aware_serial_passthrough_for_standalone():
    assert stack_aware_serial(_STANDALONE, "CN0000001") == "CN0000001"


def test_stack_aware_serial_passthrough_when_device_none():
    assert stack_aware_serial(None, "CN0000001") == "CN0000001"


def test_stack_aware_serial_passthrough_when_stack_id_missing():
    """A record flagged Stack but lacking a stackId falls back to the identifier."""
    device = {"deployment": "Stack", "stackId": None}
    assert stack_aware_serial(device, "SG39KN419Z") == "SG39KN419Z"
