import pytest
from tests.conftest import FakeMCP
from models import SiteData, SiteEnvelope, SiteSummary
import tools.sites as mod

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


async def test_get_site_name_id_mapping_returns_dict(tools, live_ctx):
    result = await tools["central_get_sites"](live_ctx, view="summary")
    assert isinstance(result, SiteEnvelope)
    assert len(result.items) >= 1
    first = result.items[0]
    assert isinstance(first, SiteSummary)
    assert first.site_id


async def test_get_sites_no_filter(tools, live_ctx):
    result = await tools["central_get_sites"](live_ctx)
    assert isinstance(result, SiteEnvelope)
    assert all(isinstance(s, SiteData) for s in result.items)


async def test_get_sites_with_valid_name(tools, live_ctx):
    summary = await tools["central_get_sites"](live_ctx, view="summary")
    if not summary.items:
        pytest.skip("No sites available")
    first_name = summary.items[0].name
    result = await tools["central_get_sites"](live_ctx, site_names=[first_name])
    assert len(result.items) == 1
    assert result.items[0].name == first_name


async def test_get_sites_unknown_name_skipped(tools, live_ctx):
    result = await tools["central_get_sites"](
        live_ctx, site_names=["__nonexistent_site__"]
    )
    assert result.items == []
