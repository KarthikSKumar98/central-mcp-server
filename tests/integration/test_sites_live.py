import pytest
from tests.conftest import FakeMCP
from models import SiteData
import tools.sites as mod

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


async def test_get_site_name_id_mapping_returns_dict(tools, live_ctx):
    result = await tools["central_get_site_name_id_mapping"](live_ctx)
    assert isinstance(result, dict)
    assert len(result) >= 1
    first = next(iter(result.values()))
    assert "site_id" in first
    assert "health" in first
    assert "total_devices" in first
    assert "total_clients" in first
    assert "total_alerts" in first


async def test_get_sites_no_filter(tools, live_ctx):
    result = await tools["central_get_sites"](live_ctx)
    assert isinstance(result, list)
    assert all(isinstance(s, SiteData) for s in result)


async def test_get_sites_with_valid_name(tools, live_ctx):
    mapping = await tools["central_get_site_name_id_mapping"](live_ctx)
    if not mapping:
        pytest.skip("No sites available")
    first_name = next(iter(mapping))
    result = await tools["central_get_sites"](live_ctx, site_names=[first_name])
    assert len(result) == 1
    assert result[0].name == first_name


async def test_get_sites_unknown_name_skipped(tools, live_ctx):
    result = await tools["central_get_sites"](
        live_ctx, site_names=["__nonexistent_site__"]
    )
    assert result == []
