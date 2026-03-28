import pytest
from tests.conftest import FakeMCP
from models import Alert, PaginatedAlerts
import tools.sites as sites_mod
import tools.alerts as mod

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


@pytest.fixture(scope="module")
def sites_tools():
    fake = FakeMCP()
    sites_mod.register(fake)
    return fake._tools


@pytest.fixture(scope="module")
async def first_site_id(sites_tools, live_ctx):
    mapping = await sites_tools["central_get_site_name_id_mapping"](live_ctx)
    if not mapping:
        pytest.skip("No sites available")
    return next(iter(mapping.values()))["site_id"]


async def test_get_alerts_active_default(tools, live_ctx, first_site_id):
    result = await tools["central_get_alerts"](live_ctx, site_id=first_site_id)
    assert isinstance(result, (PaginatedAlerts, str))
    if isinstance(result, PaginatedAlerts):
        assert all(isinstance(a, Alert) for a in result.items)


async def test_get_alerts_cleared(tools, live_ctx, first_site_id):
    result = await tools["central_get_alerts"](
        live_ctx, site_id=first_site_id, status="Cleared"
    )
    assert isinstance(result, (PaginatedAlerts, str))


async def test_get_alerts_deferred(tools, live_ctx, first_site_id):
    result = await tools["central_get_alerts"](
        live_ctx, site_id=first_site_id, status="Deferred"
    )
    assert isinstance(result, (PaginatedAlerts, str))


async def test_get_alerts_sort_ascending(tools, live_ctx, first_site_id):
    result = await tools["central_get_alerts"](
        live_ctx, site_id=first_site_id, sort="createdAt asc"
    )
    assert isinstance(result, (PaginatedAlerts, str))


async def test_get_alerts_by_device_type_ap(tools, live_ctx, first_site_id):
    result = await tools["central_get_alerts"](
        live_ctx, site_id=first_site_id, device_type="Access Point"
    )
    assert isinstance(result, (PaginatedAlerts, str))


async def test_get_alerts_by_category_system(tools, live_ctx, first_site_id):
    result = await tools["central_get_alerts"](
        live_ctx, site_id=first_site_id, category="System", status="Cleared"
    )
    assert isinstance(result, (PaginatedAlerts, str))


async def test_get_alerts_device_type_and_category(tools, live_ctx, first_site_id):
    result = await tools["central_get_alerts"](
        live_ctx,
        site_id=first_site_id,
        device_type="Switch",
        category="LAN",
        sort="severity desc",
    )
    assert isinstance(result, (PaginatedAlerts, str))
