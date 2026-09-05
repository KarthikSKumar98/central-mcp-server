import pytest
from fastmcp.exceptions import ToolError
from tests.conftest import FakeMCP
from models import (
    CompactEventFilters,
    Event,
    EventEnvelope,
    EventFacetsEnvelope,
    EventFilters,
)
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
    summary = await sites_tools["central_get_sites"](live_ctx, view="summary")
    if not summary.items:
        pytest.skip("No sites available")
    site = summary.items[0]
    return {"name": site.name, "site_id": site.site_id}


@pytest.fixture(scope="module")
async def first_device(devices_tools, live_ctx):
    devices = await devices_tools["central_get_devices"](live_ctx)
    if not devices.items:
        pytest.skip("No devices available")
    return devices.items[0]


async def test_get_events_site_context_last_1h(tools, live_ctx, first_site):
    result = await tools["central_get_events"](
        live_ctx,
        site_id=first_site["site_id"],
        time_range="last_1h",
    )
    assert isinstance(result, EventEnvelope)
    assert all(isinstance(e, Event) for e in result.items)


async def test_get_events_site_context_last_24h(tools, live_ctx, first_site):
    result = await tools["central_get_events"](
        live_ctx,
        site_id=first_site["site_id"],
        time_range="last_24h",
    )
    assert isinstance(result, EventEnvelope)


async def test_get_events_site_context_last_7d(tools, live_ctx, first_site):
    result = await tools["central_get_events"](
        live_ctx,
        site_id=first_site["site_id"],
        time_range="last_7d",
    )
    assert isinstance(result, EventEnvelope)


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
    assert isinstance(result, EventEnvelope)


async def test_get_events_explicit_time_range(tools, live_ctx, first_site):
    result = await tools["central_get_events"](
        live_ctx,
        site_id=first_site["site_id"],
        start_time="2026-03-21T00:00:00.000Z",
        end_time="2026-03-21T23:59:59.999Z",
    )
    assert isinstance(result, EventEnvelope)


async def test_get_events_with_search(tools, live_ctx, first_site):
    result = await tools["central_get_events"](
        live_ctx,
        site_id=first_site["site_id"],
        time_range="last_24h",
        search="AP",
    )
    assert isinstance(result, EventEnvelope)


async def test_get_events_site_context_rejects_context_identifier(
    tools, live_ctx, first_site
):
    with pytest.raises(
        ToolError,
        match="context_identifier must not be provided when context_type=SITE",
    ):
        await tools["central_get_events"](
            live_ctx,
            site_id=first_site["site_id"],
            context_type="SITE",
            context_identifier=first_site["site_id"],
        )


async def test_get_events_non_site_requires_context_identifier(
    tools, live_ctx, first_site
):
    with pytest.raises(ToolError, match="context_identifier is required"):
        await tools["central_get_events"](
            live_ctx,
            site_id=first_site["site_id"],
            context_type="ACCESS_POINT",
        )


async def test_get_events_facets_site_context(tools, live_ctx, first_site):
    result = await tools["central_get_events"](
        live_ctx,
        site_id=first_site["site_id"],
        mode="facets",
        time_range="last_1h",
    )
    assert isinstance(result, EventFacetsEnvelope)
    assert isinstance(result.items[0], EventFilters)
    assert result.items[0].total >= 0


async def test_get_events_facets_compact_site_context(tools, live_ctx, first_site):
    result = await tools["central_get_events"](
        live_ctx,
        site_id=first_site["site_id"],
        mode="facets",
        time_range="last_24h",
        response_mode="compact",
    )
    assert isinstance(result, EventFacetsEnvelope)
    facets = result.items[0]
    assert isinstance(facets, CompactEventFilters)
    assert facets.total >= 0
    assert isinstance(facets.event_names, list)
    assert isinstance(facets.source_types, list)
    assert isinstance(facets.categories, list)


async def test_get_events_facets_invalid_response_mode_raises_tool_error(
    tools, live_ctx, first_site
):
    with pytest.raises(ToolError, match="response_mode must be one of"):
        await tools["central_get_events"](
            live_ctx,
            site_id=first_site["site_id"],
            mode="facets",
            response_mode="invalid",  # type: ignore[arg-type]
        )


async def test_get_events_facets_last_24h(tools, live_ctx, first_site):
    result = await tools["central_get_events"](
        live_ctx,
        site_id=first_site["site_id"],
        mode="facets",
        time_range="last_24h",
    )
    assert isinstance(result, EventFacetsEnvelope)
    assert isinstance(result.items[0], EventFilters)
    assert result.items[0].total >= 0


async def test_get_events_facets_explicit_times(tools, live_ctx, first_site):
    result = await tools["central_get_events"](
        live_ctx,
        site_id=first_site["site_id"],
        mode="facets",
        start_time="2026-03-21T00:00:00.000Z",
        end_time="2026-03-21T23:59:59.999Z",
    )
    assert isinstance(result, EventFacetsEnvelope)
    assert isinstance(result.items[0], EventFilters)
    assert result.items[0].total >= 0


async def test_get_events_facets_site_context_rejects_context_identifier(
    tools, live_ctx, first_site
):
    with pytest.raises(
        ToolError,
        match="context_identifier must not be provided when context_type=SITE",
    ):
        await tools["central_get_events"](
            live_ctx,
            site_id=first_site["site_id"],
            mode="facets",
            context_type="SITE",
            context_identifier=first_site["site_id"],
        )


async def test_get_events_facets_non_site_requires_context_identifier(
    tools, live_ctx, first_site
):
    with pytest.raises(ToolError, match="context_identifier is required"):
        await tools["central_get_events"](
            live_ctx,
            site_id=first_site["site_id"],
            mode="facets",
            context_type="ACCESS_POINT",
        )


async def test_get_events_facets_device_context(
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
    result = await tools["central_get_events"](
        live_ctx,
        mode="facets",
        context_type=context_type,
        context_identifier=first_device.serial_number,
        site_id=site_id,
        time_range="last_24h",
    )
    assert isinstance(result, EventFacetsEnvelope)
    assert isinstance(result.items[0], EventFilters)
    assert result.items[0].total >= 0
