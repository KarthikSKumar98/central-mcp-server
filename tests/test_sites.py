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
    "devices": {"count": 10},
    "clients": {"count": 50},
    "alerts": {"total": 3, "critical": 1},
}

RAW_SITE_PARTIAL_HEALTH = {
    **RAW_SITE,
    "health": {
        "groups": [
            {"name": "Good", "value": 8},
            {"name": "Fair", "value": 2},
        ]
    },
}

RAW_SITE_FLAT_HEALTH = {
    **RAW_SITE,
    "health": {"Poor": 0, "Fair": 2, "Good": 8},
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
    with patch("tools.sites.fetch_site_data", return_value=FAKE_SITES_DICT) as mock_fetch:
        result = await tools["central_get_sites"](ctx)
    mock_fetch.assert_called_once_with(ctx.lifespan_context["conn"], site_names=None)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_get_sites_with_filter(tools):
    ctx = make_ctx()
    with patch("tools.sites.fetch_site_data", return_value=FAKE_SITES_DICT) as mock_fetch:
        result = await tools["central_get_sites"](ctx, site_names=["Alpha"])
    mock_fetch.assert_called_once_with(
        ctx.lifespan_context["conn"], site_names=["Alpha"]
    )
    assert len(result) == 1
    assert result[0].name == "Alpha"


@pytest.mark.asyncio
async def test_get_sites_unknown_name_returns_error(tools):
    ctx = make_ctx()
    with patch("tools.sites.fetch_site_data", return_value=FAKE_SITES_DICT) as mock_fetch:
        result = await tools["central_get_sites"](
            ctx, site_names=["Alpha", "NONEXISTENT"]
        )
    mock_fetch.assert_called_once_with(
        ctx.lifespan_context["conn"], site_names=["Alpha", "NONEXISTENT"]
    )
    assert len(result) == 1
    assert result[0].name == "Alpha"


@pytest.mark.asyncio
async def test_get_sites_failure_returns_formatted_error(tools):
    ctx = make_ctx()
    with patch("tools.sites.fetch_site_data", side_effect=Exception("boom")):
        result = await tools["central_get_sites"](ctx)
    assert result == "Error fetching sites: boom"


# --- get_summary ---


@pytest.mark.asyncio
async def test_get_summary_keys(tools):
    ctx = make_ctx()
    with patch("tools.sites.MonitoringSites.get_all_sites", return_value=[RAW_SITE]):
        result = await tools["central_get_summary"](ctx)
    assert "HQ" in result
    entry = result["HQ"]
    assert "site_id" in entry
    assert "health" in entry
    assert "total_devices" in entry
    assert "total_clients" in entry
    assert "total_alerts" in entry
    assert "critical_alerts" in entry


@pytest.mark.asyncio
async def test_get_summary_health_calculation(tools):
    ctx = make_ctx()
    with patch("tools.sites.MonitoringSites.get_all_sites", return_value=[RAW_SITE]):
        result = await tools["central_get_summary"](ctx)
    # Good=8, Fair=2, Poor=0 → round(8*1 + 2*0.5 + 0*0) = round(9) = 9
    assert result["HQ"]["health"] == 9


@pytest.mark.asyncio
async def test_get_summary_partial_health_groups_treat_missing_groups_as_zero(tools):
    ctx = make_ctx()
    with patch(
        "tools.sites.MonitoringSites.get_all_sites",
        return_value=[RAW_SITE_PARTIAL_HEALTH],
    ):
        result = await tools["central_get_summary"](ctx)
    assert result["HQ"]["health"] == 9


@pytest.mark.asyncio
async def test_get_summary_flat_health_dict_is_normalized(tools):
    ctx = make_ctx()
    with patch(
        "tools.sites.MonitoringSites.get_all_sites",
        return_value=[RAW_SITE_FLAT_HEALTH],
    ):
        result = await tools["central_get_summary"](ctx)
    assert result["HQ"]["health"] == 9


@pytest.mark.asyncio
async def test_get_summary_missing_health_groups(tools):
    ctx = make_ctx()
    site_no_health = {**RAW_SITE, "health": {}}
    with patch(
        "tools.sites.MonitoringSites.get_all_sites", return_value=[site_no_health]
    ):
        result = await tools["central_get_summary"](ctx)
    assert result["HQ"]["health"] is None


@pytest.mark.asyncio
async def test_get_summary_counts(tools):
    ctx = make_ctx()
    with patch("tools.sites.MonitoringSites.get_all_sites", return_value=[RAW_SITE]):
        result = await tools["central_get_summary"](ctx)
    entry = result["HQ"]
    assert entry["site_id"] == "site-42"
    assert entry["total_devices"] == 10
    assert entry["total_clients"] == 50
    assert entry["total_alerts"] == 3
    assert entry["critical_alerts"] == 1


@pytest.mark.asyncio
async def test_get_summary_failure_returns_formatted_error(tools):
    ctx = make_ctx()
    with patch(
        "tools.sites.MonitoringSites.get_all_sites",
        side_effect=Exception("Central unavailable"),
    ):
        result = await tools["central_get_summary"](ctx)
    assert result == "Error fetching site summary: Central unavailable"
