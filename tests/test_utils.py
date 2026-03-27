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


# ---------------------------------------------------------------------------
# clean_client_data
# ---------------------------------------------------------------------------
from utils import clean_client_data
from models import Client

_RAW_WIRELESS_CLIENT = {
    "macAddress": "f0:1a:a0:3d:00:af",
    "clientName": "MyLaptop",
    "ipv4": "10.0.0.1",
    "ipv6": None,
    "hostName": "laptop.local",
    "clientConnectionType": "Wireless",
    "status": "Connected",
    "connectedDeviceSerial": "SN456",
    "connectedTo": "AP-01",
    "vlanId": "10",
    "wlanName": "CorpWLAN",
    "wirelessBand": "5GHz",
    "wirelessChannel": "60",
    "wirelessSecurity": "WPA3",
    "keyManagement": "SAE",
    "bssid": "aa:bb:cc:dd:ee:01",
    "radioMacAddress": "aa:bb:cc:dd:ee:00",
    "siteId": "site-1",
    "siteName": "HQ",
}

_RAW_WIRED_CLIENT = {
    "macAddress": "00:11:22:33:44:55",
    "clientConnectionType": "Wired",
    "status": "Connected",
    "port": "GE0/0/1",
    "siteId": "site-1",
    "siteName": "HQ",
}


def test_clean_client_data_wireless_fields_mapped():
    c = clean_client_data([_RAW_WIRELESS_CLIENT])[0]
    assert isinstance(c, Client)
    assert c.mac == "f0:1a:a0:3d:00:af"
    assert c.connection_type == "Wireless"
    assert c.wlan_name == "CorpWLAN"
    assert c.wireless_band == "5GHz"
    assert c.bssid == "aa:bb:cc:dd:ee:01"


def test_clean_client_data_wireless_strips_port():
    c = clean_client_data([_RAW_WIRELESS_CLIENT])[0]
    assert c.port is None


def test_clean_client_data_wired_keeps_port():
    c = clean_client_data([_RAW_WIRED_CLIENT])[0]
    assert c.port == "GE0/0/1"


def test_clean_client_data_wired_strips_wireless_fields():
    c = clean_client_data([_RAW_WIRED_CLIENT])[0]
    assert c.wlan_name is None
    assert c.bssid is None
    assert c.wireless_band is None
    assert c.radio_mac is None


# ---------------------------------------------------------------------------
# clean_alert_data
# ---------------------------------------------------------------------------
from utils import clean_alert_data
from models import Alert

_RAW_ALERT = {
    "summary": "Device Offline",
    "clearedReason": None,
    "createdAt": "2026-03-21T10:00:00Z",
    "priority": "High",
    "updatedAt": "2026-03-21T10:05:00Z",
    "deviceType": "Access Point",
    "updatedBy": "system",
    "name": "AP Offline",
    "status": "Active",
    "category": "System",
    "severity": "Critical",
}


def test_clean_alert_data_returns_alert_models():
    result = clean_alert_data([_RAW_ALERT])
    assert len(result) == 1
    assert isinstance(result[0], Alert)


def test_clean_alert_data_field_mapping():
    a = clean_alert_data([_RAW_ALERT])[0]
    assert a.summary == "Device Offline"
    assert a.severity == "Critical"
    assert a.status == "Active"
    assert a.category == "System"
    assert a.priority == "High"
    assert a.cleared_reason is None
    assert a.device_type == "Access Point"


def test_clean_alert_data_multiple():
    raw2 = {**_RAW_ALERT, "summary": "CPU High", "severity": "Major"}
    result = clean_alert_data([_RAW_ALERT, raw2])
    assert len(result) == 2
    assert result[1].summary == "CPU High"
    assert result[1].severity == "Major"


# ---------------------------------------------------------------------------
# clean_event_filters
# ---------------------------------------------------------------------------
from utils import clean_event_filters
from models import EventFilters

_RAW_EVENT_FILTERS = {
    "categories": [
        {"category": "Clients", "count": 30},
        {"category": "System", "count": 10},
    ],
    "eventNames": [
        {"eventId": "32", "eventName": "Client DHCP Acknowledge", "count": 25},
    ],
    "sourceTypes": [
        {"sourceType": "Wireless Client", "count": 30},
    ],
}


def test_clean_event_filters_returns_model():
    result = clean_event_filters(_RAW_EVENT_FILTERS)
    assert isinstance(result, EventFilters)


def test_clean_event_filters_total_is_sum_of_categories():
    result = clean_event_filters(_RAW_EVENT_FILTERS)
    assert result.total == 40  # 30 + 10


def test_clean_event_filters_categories():
    result = clean_event_filters(_RAW_EVENT_FILTERS)
    assert len(result.categories) == 2
    assert result.categories[0].category == "Clients"
    assert result.categories[0].count == 30


def test_clean_event_filters_event_names():
    result = clean_event_filters(_RAW_EVENT_FILTERS)
    assert len(result.event_names) == 1
    assert result.event_names[0].event_id == "32"
    assert result.event_names[0].event_name == "Client DHCP Acknowledge"
    assert result.event_names[0].count == 25


def test_clean_event_filters_source_types():
    result = clean_event_filters(_RAW_EVENT_FILTERS)
    assert len(result.source_types) == 1
    assert result.source_types[0].source_type == "Wireless Client"


def test_clean_event_filters_empty_response():
    result = clean_event_filters({})
    assert result.total == 0
    assert result.categories == []
    assert result.event_names == []
    assert result.source_types == []


# ---------------------------------------------------------------------------
# groups_to_map
# ---------------------------------------------------------------------------
from utils import groups_to_map


def test_groups_to_map_flat_groups():
    obj = {"groups": [{"name": "Good", "value": 8}, {"name": "Poor", "value": 2}]}
    result = groups_to_map(obj)
    assert result["Good"] == 8
    assert result["Poor"] == 2
    assert result["Total"] == 10


def test_groups_to_map_nested_under_key():
    obj = {"health": {"groups": [{"name": "Good", "value": 5}]}}
    result = groups_to_map(obj)
    assert result["Good"] == 5


def test_groups_to_map_empty_dict():
    result = groups_to_map({})
    assert result == {}


def test_groups_to_map_list_of_typed_objects():
    obj = [
        {
            "name": "Access Points",
            "health": {"groups": [{"name": "Good", "value": 3}, {"name": "Poor", "value": 1}]},
        }
    ]
    result = groups_to_map(obj)
    assert "Access Points" in result
    assert result["Access Points"]["Good"] == 3
    assert result["Access Points"]["Poor"] == 1


# ---------------------------------------------------------------------------
# transform_to_site_data
# ---------------------------------------------------------------------------
from utils import transform_to_site_data
from models import SiteData

_RAW_SITE = {
    "siteName": "HQ",
    "id": "site-42",
    "health": {
        "groups": [
            {"name": "Good", "value": 8},
            {"name": "Fair", "value": 2},
            {"name": "Poor", "value": 0},
        ]
    },
    "devices": {"total": 10},
    "clients": {"total": 50},
    "alerts": {"total": 3},
    "address": {},
    "location": {"latitude": "37.7749", "longitude": "-122.4194"},
}


def test_transform_to_site_data_uses_sitename_key():
    # Regression test: field is "siteName", not "name" — previously caused KeyError
    result = transform_to_site_data(_RAW_SITE)
    assert isinstance(result, SiteData)
    assert result.name == "HQ"


def test_transform_to_site_data_site_id():
    result = transform_to_site_data(_RAW_SITE)
    assert result.site_id == "site-42"


def test_transform_to_site_data_health_summary():
    result = transform_to_site_data(_RAW_SITE)
    # Good=8, Fair=2, Poor=0 → round(8*1 + 2*0.5 + 0*0) = 9
    assert result.metrics.health["Summary"] == 9


def test_transform_to_site_data_location_parsed():
    result = transform_to_site_data(_RAW_SITE)
    assert result.location["lat"] == 37.7749
    assert result.location["lng"] == -122.4194


def test_transform_to_site_data_null_location():
    raw = {**_RAW_SITE, "location": None}
    result = transform_to_site_data(raw)
    assert result.location["lat"] is None
    assert result.location["lng"] is None
