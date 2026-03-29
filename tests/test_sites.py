import pytest
from unittest.mock import patch
from models import SiteData, SiteMetrics
import tools.sites as mod
from tests.conftest import FakeMCP, make_ctx


def make_site_data(name: str) -> SiteData:
    return SiteData(
        site_id=f"id-{name}",
        name=name,
        address={},
        location={"lat": None, "lng": None},
        metrics=SiteMetrics(health={}, devices={}, clients={}, alerts={}),
    )


FAKE_SITES_DICT = {
    "Alpha": make_site_data("Alpha"),
    "Beta": make_site_data("Beta"),
    "Gamma": make_site_data("Gamma"),
}

RAW_SITE = {
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
}


@pytest.fixture
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


# --- get_sites ---


@pytest.mark.asyncio
async def test_get_sites_no_filter_returns_all(tools):
    ctx = make_ctx()
    with patch("tools.sites.fetch_site_data_parallel", return_value=FAKE_SITES_DICT):
        result = await tools["central_get_sites"](ctx)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_get_sites_with_filter(tools):
    ctx = make_ctx()
    with patch("tools.sites.fetch_site_data_parallel", return_value=FAKE_SITES_DICT):
        result = await tools["central_get_sites"](ctx, site_names=["Alpha"])
    assert len(result) == 1
    assert result[0].name == "Alpha"


@pytest.mark.asyncio
async def test_get_sites_unknown_name_skipped(tools):
    ctx = make_ctx()
    with patch("tools.sites.fetch_site_data_parallel", return_value=FAKE_SITES_DICT):
        result = await tools["central_get_sites"](
            ctx, site_names=["Alpha", "NONEXISTENT"]
        )
    assert len(result) == 1
    assert result[0].name == "Alpha"


# --- get_site_name_id_mapping ---


@pytest.mark.asyncio
async def test_get_site_name_id_mapping_keys(tools):
    ctx = make_ctx()
    with patch("tools.sites.MonitoringSites.get_all_sites", return_value=[RAW_SITE]):
        result = await tools["central_get_site_name_id_mapping"](ctx)
    assert "HQ" in result
    entry = result["HQ"]
    assert "site_id" in entry
    assert "health" in entry
    assert "total_devices" in entry
    assert "total_clients" in entry
    assert "total_alerts" in entry


@pytest.mark.asyncio
async def test_get_site_name_id_mapping_health_calculation(tools):
    ctx = make_ctx()
    with patch("tools.sites.MonitoringSites.get_all_sites", return_value=[RAW_SITE]):
        result = await tools["central_get_site_name_id_mapping"](ctx)
    # Good=8, Fair=2, Poor=0 → round(8*1 + 2*0.5 + 0*0) = round(9) = 9
    assert result["HQ"]["health"] == 9


@pytest.mark.asyncio
async def test_get_site_name_id_mapping_missing_health_groups(tools):
    ctx = make_ctx()
    site_no_health = {**RAW_SITE, "health": {}}
    with patch(
        "tools.sites.MonitoringSites.get_all_sites", return_value=[site_no_health]
    ):
        result = await tools["central_get_site_name_id_mapping"](ctx)
    assert result["HQ"]["health"] is None


@pytest.mark.asyncio
async def test_get_site_name_id_mapping_counts(tools):
    ctx = make_ctx()
    with patch("tools.sites.MonitoringSites.get_all_sites", return_value=[RAW_SITE]):
        result = await tools["central_get_site_name_id_mapping"](ctx)
    entry = result["HQ"]
    assert entry["site_id"] == "site-42"
    assert entry["total_devices"] == 10
    assert entry["total_clients"] == 50
    assert entry["total_alerts"] == 3
