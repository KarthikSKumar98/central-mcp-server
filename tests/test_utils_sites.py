from unittest.mock import MagicMock, patch

import pytest

from models import SiteData
from utils.sites import (
    compute_health_score,
    fetch_site_data,
    groups_to_map,
    process_site_health_data,
    transform_to_site_data,
)

# ---------------------------------------------------------------------------
# groups_to_map
# ---------------------------------------------------------------------------


def test_groups_to_map_flat_groups():
    obj = {"groups": [{"name": "Good", "value": 8}, {"name": "Poor", "value": 2}]}
    result = groups_to_map(obj)
    assert result["good"] == 8
    assert result["poor"] == 2
    assert result["total"] == 10


def test_groups_to_map_nested_under_key():
    obj = {"health": {"groups": [{"name": "Good", "value": 5}]}}
    result = groups_to_map(obj)
    assert result["good"] == 5


def test_groups_to_map_flat_dict_normalizes_keys():
    obj = {"Poor": 58, "Fair": 0, "Good": 42}
    result = groups_to_map(obj)
    assert result == {"poor": 58, "fair": 0, "good": 42}


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
    assert "access_points" in result
    assert result["access_points"]["good"] == 3
    assert result["access_points"]["poor"] == 1


# ---------------------------------------------------------------------------
# transform_to_site_data
# ---------------------------------------------------------------------------

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
    assert result.metrics.health["summary"] == 9


def test_transform_to_site_data_health_summary_with_missing_zero_value_groups():
    raw = {
        **_RAW_SITE,
        "health": {"groups": [{"name": "Good", "value": 8}, {"name": "Fair", "value": 2}]},
    }
    result = transform_to_site_data(raw)
    assert result.metrics.health["summary"] == 9


def test_transform_to_site_data_location_parsed():
    result = transform_to_site_data(_RAW_SITE)
    assert result.location["lat"] == 37.7749
    assert result.location["lng"] == -122.4194


def test_transform_to_site_data_null_location():
    raw = {**_RAW_SITE, "location": None}
    result = transform_to_site_data(raw)
    assert result.location["lat"] is None
    assert result.location["lng"] is None


# ---------------------------------------------------------------------------
# process_site_health_data
# ---------------------------------------------------------------------------

# Read-only fixtures — do not mutate these in tests; use copies if you need to modify values.
_SITE_HEALTH = [
    {
        "siteName": "HQ",
        "id": "site-1",
        "health": {},
        "devices": {},
        "clients": {},
        "alerts": {},
        "address": {},
        "location": None,
    }
]
_DEVICE_HEALTH = [
    {
        "siteName": "HQ",
        "deviceTypes": [
            {
                "name": "Access Points",
                "health": {"groups": [{"name": "Good", "value": 3}]},
            }
        ],
    }
]
_CLIENT_HEALTH = [
    {
        "siteName": "HQ",
        "clientTypes": [
            {
                "name": "Wireless",
                "health": {"groups": [{"name": "Good", "value": 10}]},
            }
        ],
    }
]


def test_fetch_site_data_applies_odata_site_filter_to_all_endpoints():
    conn = MagicMock()
    with patch(
        "utils.sites.paginated_fetch",
        side_effect=[_SITE_HEALTH, _DEVICE_HEALTH, _CLIENT_HEALTH],
    ) as mock_fetch:
        result = fetch_site_data(conn, site_names=["HQ", "Branch"])

    assert "HQ" in result
    assert mock_fetch.call_count == 3
    expected_filter = "siteName in ('HQ', 'Branch')"
    for call in mock_fetch.call_args_list:
        assert call.kwargs["additional_params"] == {"filter": expected_filter}


@pytest.mark.parametrize("site_names", [None, []])
def test_fetch_site_data_without_site_names_sends_no_filter(site_names):
    conn = MagicMock()
    with patch(
        "utils.sites.paginated_fetch",
        side_effect=[_SITE_HEALTH, _DEVICE_HEALTH, _CLIENT_HEALTH],
    ) as mock_fetch:
        result = fetch_site_data(conn, site_names=site_names)

    assert "HQ" in result
    assert mock_fetch.call_count == 3
    for call in mock_fetch.call_args_list:
        assert call.kwargs["additional_params"] is None


def test_process_site_health_data_returns_dict_keyed_by_sitename():
    result = process_site_health_data(_SITE_HEALTH, [], [])
    assert isinstance(result, dict)
    assert "HQ" in result
    assert isinstance(result["HQ"], SiteData)


def test_process_site_health_data_merges_device_details():
    result = process_site_health_data(_SITE_HEALTH, _DEVICE_HEALTH, [])
    assert result["HQ"].metrics.devices["details"]["access_points"]["good"] == 3


def test_process_site_health_data_merges_client_details():
    result = process_site_health_data(_SITE_HEALTH, [], _CLIENT_HEALTH)
    assert result["HQ"].metrics.clients["details"]["wireless"]["good"] == 10


def test_process_site_health_data_unknown_site_in_device_health_skipped():
    result = process_site_health_data(
        _SITE_HEALTH, [{"siteName": "Unknown", "deviceTypes": []}], []
    )
    assert len(result) == 1
    assert "HQ" in result


def test_process_site_health_data_multiple_sites():
    site_health = [
        {
            "siteName": "HQ",
            "id": "site-1",
            "health": {},
            "devices": {},
            "clients": {},
            "alerts": {},
            "address": {},
            "location": None,
        },
        {
            "siteName": "Branch",
            "id": "site-2",
            "health": {},
            "devices": {},
            "clients": {},
            "alerts": {},
            "address": {},
            "location": None,
        },
    ]
    result = process_site_health_data(site_health, [], [])
    assert "HQ" in result
    assert "Branch" in result


def test_process_site_health_data_unknown_site_in_client_health_skipped():
    result = process_site_health_data(
        _SITE_HEALTH,
        [],
        [{"siteName": "Unknown", "clientTypes": []}],
    )
    assert len(result) == 1
    assert "HQ" in result


def test_compute_health_score_partial_groups_treats_missing_buckets_as_zero():
    assert compute_health_score({"good": 8, "fair": 2}) == 9


def test_compute_health_score_no_known_groups_returns_none():
    assert compute_health_score({"total": 10}) is None
