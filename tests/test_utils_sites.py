from models import SiteData
from utils.sites import groups_to_map, process_site_health_data, transform_to_site_data

# ---------------------------------------------------------------------------
# groups_to_map
# ---------------------------------------------------------------------------


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


def test_process_site_health_data_returns_dict_keyed_by_sitename():
    result = process_site_health_data(_SITE_HEALTH, [], [])
    assert isinstance(result, dict)
    assert "HQ" in result
    assert isinstance(result["HQ"], SiteData)


def test_process_site_health_data_merges_device_details():
    result = process_site_health_data(_SITE_HEALTH, _DEVICE_HEALTH, [])
    assert result["HQ"].metrics.devices["Details"]["Access Points"]["Good"] == 3


def test_process_site_health_data_merges_client_details():
    result = process_site_health_data(_SITE_HEALTH, [], _CLIENT_HEALTH)
    assert result["HQ"].metrics.clients["Details"]["Wireless"]["Good"] == 10


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
