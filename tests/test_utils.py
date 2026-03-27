import pytest
from utils import FilterField, build_odata_filter


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
from utils import compute_time_window


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
from unittest.mock import patch
from utils import paginated_fetch


def _page(items, next_cursor=None, total=None):
    """Build a fake retry_central_command response."""
    if total is None:
        total = len(items)
    return {"code": 200, "msg": {"items": items, "total": total, "next": next_cursor}}


def test_paginated_fetch_single_page():
    conn = object()
    with patch("utils.retry_central_command", return_value=_page([{"id": 1}])) as mock:
        result = paginated_fetch(conn, "some/path", limit=100)
    assert result == [{"id": 1}]
    mock.assert_called_once_with(
        conn,
        api_method="GET",
        api_path="some/path",
        api_params={"limit": 100, "next": 1},
    )


def test_paginated_fetch_multi_page_accumulates_items():
    conn = object()
    responses = [
        _page([{"id": 1}], next_cursor=2, total=2),
        _page([{"id": 2}], next_cursor=None, total=2),
    ]
    with patch("utils.retry_central_command", side_effect=responses):
        result = paginated_fetch(conn, "some/path", limit=1)
    assert result == [{"id": 1}, {"id": 2}]


def test_paginated_fetch_empty_result():
    conn = object()
    with patch("utils.retry_central_command", return_value=_page([], total=0)):
        result = paginated_fetch(conn, "some/path", limit=100)
    assert result == []


def test_paginated_fetch_passes_additional_params():
    conn = object()
    with patch("utils.retry_central_command", return_value=_page([])) as mock:
        paginated_fetch(conn, "some/path", limit=50, additional_params={"filter": "x eq 'y'"})
    _, kwargs = mock.call_args
    assert kwargs["api_params"]["filter"] == "x eq 'y'"
    assert kwargs["api_params"]["limit"] == 50


# ---------------------------------------------------------------------------
# clean_device_data
# ---------------------------------------------------------------------------
from utils import clean_device_data
from models import Device

_RAW_DEVICE = {
    "serialNumber": "SN123",
    "macAddress": "aa:bb:cc:dd:ee:ff",
    "deviceType": "ACCESS_POINT",
    "model": "AP-635",
    "partNumber": "JZ123A",
    "deviceName": "MyAP",
    "deviceFunction": None,
    "status": "ONLINE",
    "isProvisioned": "Yes",
    "role": None,
    "deployment": None,
    "tier": "ADVANCED_AP",
    "firmwareVersion": "10.6.0",
    "siteId": "site-1",
    "siteName": "HQ",
    "deviceGroupName": "Group1",
    "scopeId": "scope-1",
    "ipv4": "192.168.1.1",
    "stackId": None,
}


def test_clean_device_data_returns_device_models():
    result = clean_device_data([_RAW_DEVICE])
    assert len(result) == 1
    assert isinstance(result[0], Device)


def test_clean_device_data_field_mapping():
    d = clean_device_data([_RAW_DEVICE])[0]
    assert d.serial_number == "SN123"
    assert d.mac_address == "aa:bb:cc:dd:ee:ff"
    assert d.device_type == "ACCESS_POINT"
    assert d.name == "MyAP"
    assert d.firmware_version == "10.6.0"
    assert d.site_id == "site-1"
    assert d.site_name == "HQ"


def test_clean_device_data_is_provisioned_yes():
    d = clean_device_data([_RAW_DEVICE])[0]
    assert d.is_provisioned is True


def test_clean_device_data_is_provisioned_no():
    raw = {**_RAW_DEVICE, "isProvisioned": "No"}
    d = clean_device_data([raw])[0]
    assert d.is_provisioned is False


def test_clean_device_data_no_site():
    raw = {**_RAW_DEVICE, "siteId": None, "siteName": None}
    d = clean_device_data([raw])[0]
    assert d.site_id is None
    assert d.site_name is None
