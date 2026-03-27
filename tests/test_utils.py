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
