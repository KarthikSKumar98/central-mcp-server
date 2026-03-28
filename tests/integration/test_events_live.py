import pytest
from tests.conftest import FakeMCP
from models import Event, EventFilters, PaginatedEvents
import tools.sites as sites_mod
import tools.devices as devices_mod
import tools.events as mod

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
def devices_tools():
    fake = FakeMCP()
    devices_mod.register(fake)
    return fake._tools


@pytest.fixture(scope="module")
async def first_site(sites_tools, live_ctx):
    mapping = await sites_tools["central_get_site_name_id_mapping"](live_ctx)
    if not mapping:
        pytest.skip("No sites available")
    name, data = next(iter(mapping.items()))
    return {"name": name, "site_id": data["site_id"]}


@pytest.fixture(scope="module")
async def first_device(devices_tools, live_ctx):
    devices = await devices_tools["central_get_devices"](live_ctx)
    if not devices:
        pytest.skip("No devices available")
    return devices[0]


async def test_get_events_site_context_last_1h(tools, live_ctx, first_site):
    result = await tools["central_get_events"](
        live_ctx,
        context_type="SITE",
        context_identifier=first_site["site_id"],
        site_id=first_site["site_id"],
        time_range="last_1h",
    )
    assert isinstance(result, (PaginatedEvents, str))
    if isinstance(result, PaginatedEvents):
        assert all(isinstance(e, Event) for e in result.items)


async def test_get_events_site_context_last_24h(tools, live_ctx, first_site):
    result = await tools["central_get_events"](
        live_ctx,
        context_type="SITE",
        context_identifier=first_site["site_id"],
        site_id=first_site["site_id"],
        time_range="last_24h",
    )
    assert isinstance(result, (PaginatedEvents, str))


async def test_get_events_site_context_last_7d(tools, live_ctx, first_site):
    result = await tools["central_get_events"](
        live_ctx,
        context_type="SITE",
        context_identifier=first_site["site_id"],
        site_id=first_site["site_id"],
        time_range="last_7d",
    )
    assert isinstance(result, (PaginatedEvents, str))


async def test_get_events_device_context(tools, live_ctx, first_device, first_site):
    device_type_map = {
        "ACCESS_POINT": "ACCESS_POINT",
        "SWITCH": "SWITCH",
        "GATEWAY": "GATEWAY",
    }
    context_type = device_type_map.get(first_device.device_type)
    if context_type is None:
        pytest.skip(f"Unsupported device type: {first_device.device_type}")
    site_id = first_device.site_id or first_site["site_id"]
    result = await tools["central_get_events"](
        live_ctx,
        context_type=context_type,
        context_identifier=first_device.serial_number,
        site_id=site_id,
        time_range="last_24h",
    )
    assert isinstance(result, (PaginatedEvents, str))


async def test_get_events_explicit_time_range(tools, live_ctx, first_site):
    result = await tools["central_get_events"](
        live_ctx,
        context_type="SITE",
        context_identifier=first_site["site_id"],
        site_id=first_site["site_id"],
        start_time="2026-03-21T00:00:00.000Z",
        end_time="2026-03-21T23:59:59.999Z",
    )
    assert isinstance(result, (PaginatedEvents, str))


async def test_get_events_with_search(tools, live_ctx, first_site):
    result = await tools["central_get_events"](
        live_ctx,
        context_type="SITE",
        context_identifier=first_site["site_id"],
        site_id=first_site["site_id"],
        time_range="last_24h",
        search="AP",
    )
    assert isinstance(result, (PaginatedEvents, str))


async def test_get_events_count_site_context(tools, live_ctx, first_site):
    result = await tools["central_get_events_count"](
        live_ctx,
        context_type="SITE",
        context_identifier=first_site["site_id"],
        site_id=first_site["site_id"],
        time_range="last_1h",
    )
    assert isinstance(result, EventFilters)
    assert result.total >= 0


async def test_get_events_count_last_24h(tools, live_ctx, first_site):
    result = await tools["central_get_events_count"](
        live_ctx,
        context_type="SITE",
        context_identifier=first_site["site_id"],
        site_id=first_site["site_id"],
        time_range="last_24h",
    )
    assert isinstance(result, EventFilters)
    assert result.total >= 0


async def test_get_events_count_explicit_times(tools, live_ctx, first_site):
    result = await tools["central_get_events_count"](
        live_ctx,
        context_type="SITE",
        context_identifier=first_site["site_id"],
        site_id=first_site["site_id"],
        start_time="2026-03-21T00:00:00.000Z",
        end_time="2026-03-21T23:59:59.999Z",
    )
    assert isinstance(result, EventFilters)
    assert result.total >= 0


async def test_get_events_count_device_context(
    tools, live_ctx, first_device, first_site
):
    device_type_map = {
        "ACCESS_POINT": "ACCESS_POINT",
        "SWITCH": "SWITCH",
        "GATEWAY": "GATEWAY",
    }
    context_type = device_type_map.get(first_device.device_type)
    if context_type is None:
        pytest.skip(f"Unsupported device type: {first_device.device_type}")
    site_id = first_device.site_id or first_site["site_id"]
    result = await tools["central_get_events_count"](
        live_ctx,
        context_type=context_type,
        context_identifier=first_device.serial_number,
        site_id=site_id,
        time_range="last_24h",
    )
    assert isinstance(result, EventFilters)
    assert result.total >= 0
