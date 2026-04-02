import os
import time

import pytest

import prompts as prompts_mod
import tools.alerts as alerts_mod
import tools.clients as clients_mod
import tools.devices as devices_mod
import tools.events as events_mod
import tools.sites as sites_mod
from tests.conftest import FakeMCP

pytestmark = pytest.mark.integration

MAX_PROMPT_SECONDS = float(os.getenv("PROMPT_LIVE_MAX_SECONDS", "120"))


@pytest.fixture(scope="module")
def prompt_registry():
    fake = FakeMCP()
    prompts_mod.register(fake)
    return fake._prompts


@pytest.fixture(scope="module")
def sites_tools():
    fake = FakeMCP()
    sites_mod.register(fake)
    return fake._tools


@pytest.fixture(scope="module")
def alerts_tools():
    fake = FakeMCP()
    alerts_mod.register(fake)
    return fake._tools


@pytest.fixture(scope="module")
def devices_tools():
    fake = FakeMCP()
    devices_mod.register(fake)
    return fake._tools


@pytest.fixture(scope="module")
def clients_tools():
    fake = FakeMCP()
    clients_mod.register(fake)
    return fake._tools


@pytest.fixture(scope="module")
def events_tools():
    fake = FakeMCP()
    events_mod.register(fake)
    return fake._tools


@pytest.fixture(scope="module")
async def live_seed_data(sites_tools, devices_tools, clients_tools, live_ctx):
    mapping = await sites_tools["central_get_site_name_id_mapping"](live_ctx)
    if not mapping:
        pytest.skip("No sites available")

    site_names = list(mapping.keys())
    first_site_name = site_names[0]
    first_site_id = mapping[first_site_name]["site_id"]
    compare_site_names = site_names[:2] if len(site_names) >= 2 else [first_site_name]

    devices = await devices_tools["central_get_devices"](live_ctx, site_id=first_site_id)
    first_device = devices[0] if isinstance(devices, list) and devices else None

    clients = await clients_tools["central_get_clients"](live_ctx, site_id=first_site_id)
    first_client = clients[0] if isinstance(clients, list) and clients else None

    return {
        "site_name": first_site_name,
        "site_id": first_site_id,
        "compare_site_names": compare_site_names,
        "first_device": first_device,
        "first_client": first_client,
    }


def _assert_elapsed(label: str, elapsed: float):
    assert elapsed < MAX_PROMPT_SECONDS, (
        f"{label} exceeded performance budget: {elapsed:.2f}s > {MAX_PROMPT_SECONDS:.2f}s"
    )


def _is_rate_limited_error(exc: Exception) -> bool:
    msg = str(exc)
    return "429" in msg or "Too Many Requests" in msg


def _is_rate_limited_result(result) -> bool:
    return isinstance(result, str) and (
        "429" in result or "Too Many Requests" in result
    )


@pytest.mark.asyncio
async def test_prompt_network_health_overview_live(
    prompt_registry, sites_tools, live_ctx, record_property
):
    assert "network_health_overview" in prompt_registry
    prompt_text = prompt_registry["network_health_overview"]()
    assert "central_get_site_name_id_mapping" in prompt_text

    t0 = time.perf_counter()
    try:
        mapping = await sites_tools["central_get_site_name_id_mapping"](live_ctx)
        site_names = list(mapping.keys())[:3]
        await sites_tools["central_get_sites"](live_ctx, site_names=site_names)
    except Exception as exc:
        if _is_rate_limited_error(exc):
            pytest.skip(f"Rate limited by Central API: {exc}")
        raise
    elapsed = time.perf_counter() - t0
    record_property("duration_seconds", round(elapsed, 3))
    _assert_elapsed("network_health_overview", elapsed)


@pytest.mark.asyncio
async def test_prompt_troubleshoot_site_live(
    prompt_registry,
    sites_tools,
    alerts_tools,
    devices_tools,
    live_ctx,
    live_seed_data,
    record_property,
):
    prompt_text = prompt_registry["troubleshoot_site"](live_seed_data["site_name"])
    assert "site_names" in prompt_text

    t0 = time.perf_counter()
    try:
        await sites_tools["central_get_sites"](
            live_ctx, site_names=[live_seed_data["site_name"]]
        )
        await alerts_tools["central_get_alerts"](live_ctx, site_id=live_seed_data["site_id"])
        await devices_tools["central_get_devices"](live_ctx, site_id=live_seed_data["site_id"])
    except Exception as exc:
        if _is_rate_limited_error(exc):
            pytest.skip(f"Rate limited by Central API: {exc}")
        raise
    elapsed = time.perf_counter() - t0
    record_property("duration_seconds", round(elapsed, 3))
    _assert_elapsed("troubleshoot_site", elapsed)


@pytest.mark.asyncio
async def test_prompt_client_connectivity_check_live(
    prompt_registry,
    clients_tools,
    alerts_tools,
    devices_tools,
    live_ctx,
    live_seed_data,
    record_property,
):
    client = live_seed_data["first_client"]
    if client is None:
        pytest.skip("No clients available for connectivity check")

    prompt_text = prompt_registry["client_connectivity_check"](client.mac)
    assert "central_find_client" in prompt_text

    t0 = time.perf_counter()
    found_client = await clients_tools["central_find_client"](live_ctx, client.mac)
    if isinstance(found_client, str):
        if _is_rate_limited_result(found_client):
            pytest.skip(f"Rate limited by Central API: {found_client}")
        pytest.skip(f"Unable to fetch client details: {found_client}")
    await alerts_tools["central_get_alerts"](live_ctx, site_id=found_client.site_id)
    if found_client.connected_device_serial:
        await devices_tools["central_find_device"](
            live_ctx, serial_number=found_client.connected_device_serial
        )
    elapsed = time.perf_counter() - t0
    record_property("duration_seconds", round(elapsed, 3))
    _assert_elapsed("client_connectivity_check", elapsed)


@pytest.mark.asyncio
async def test_prompt_investigate_device_events_live(
    prompt_registry,
    devices_tools,
    events_tools,
    live_ctx,
    live_seed_data,
    record_property,
):
    device = live_seed_data["first_device"]
    if device is None:
        pytest.skip("No devices available for event investigation")
    if device.device_type not in {"ACCESS_POINT", "SWITCH", "GATEWAY"}:
        pytest.skip(f"Unsupported device type for event context: {device.device_type}")

    prompt_text = prompt_registry["investigate_device_events"](device.serial_number)
    assert "response_mode=\"compact\"" in prompt_text

    t0 = time.perf_counter()
    try:
        await devices_tools["central_find_device"](live_ctx, serial_number=device.serial_number)
        count = await events_tools["central_get_events_count"](
            live_ctx,
            site_id=device.site_id or live_seed_data["site_id"],
            context_type=device.device_type,
            context_identifier=device.serial_number,
            time_range="last_1h",
            response_mode="compact",
        )
    except Exception as exc:
        if _is_rate_limited_error(exc):
            pytest.skip(f"Rate limited by Central API: {exc}")
        raise
    if _is_rate_limited_result(count):
        pytest.skip(f"Rate limited by Central API: {count}")
    if not isinstance(count, str) and count.total > 0:
        await events_tools["central_get_events"](
            live_ctx,
            site_id=device.site_id or live_seed_data["site_id"],
            context_type=device.device_type,
            context_identifier=device.serial_number,
            time_range="last_1h",
            limit=20,
        )
    elapsed = time.perf_counter() - t0
    record_property("duration_seconds", round(elapsed, 3))
    _assert_elapsed("investigate_device_events", elapsed)


@pytest.mark.asyncio
async def test_prompt_site_event_summary_live(
    prompt_registry, events_tools, live_ctx, live_seed_data, record_property
):
    prompt_text = prompt_registry["site_event_summary"](live_seed_data["site_name"])
    assert "response_mode=\"compact\"" in prompt_text

    t0 = time.perf_counter()
    count = await events_tools["central_get_events_count"](
        live_ctx,
        site_id=live_seed_data["site_id"],
        time_range="last_1h",
        response_mode="compact",
    )
    if _is_rate_limited_result(count):
        pytest.skip(f"Rate limited by Central API: {count}")
    if not isinstance(count, str) and count.total > 0:
        await events_tools["central_get_events"](
            live_ctx, site_id=live_seed_data["site_id"], time_range="last_1h", limit=20
        )
    elapsed = time.perf_counter() - t0
    record_property("duration_seconds", round(elapsed, 3))
    _assert_elapsed("site_event_summary", elapsed)


@pytest.mark.asyncio
async def test_prompt_failed_clients_investigation_live(
    prompt_registry,
    clients_tools,
    devices_tools,
    alerts_tools,
    live_ctx,
    live_seed_data,
    record_property,
):
    prompt_text = prompt_registry["failed_clients_investigation"](live_seed_data["site_name"])
    assert "status=\"Failed\"" in prompt_text

    t0 = time.perf_counter()
    failed = await clients_tools["central_get_clients"](
        live_ctx, site_id=live_seed_data["site_id"], status="Failed"
    )
    if _is_rate_limited_result(failed):
        pytest.skip(f"Rate limited by Central API: {failed}")
    if isinstance(failed, list):
        for client in failed[:5]:
            await devices_tools["central_find_device"](
                live_ctx, serial_number=client.serial_number
            )
    await alerts_tools["central_get_alerts"](
        live_ctx, site_id=live_seed_data["site_id"], category="Clients"
    )
    elapsed = time.perf_counter() - t0
    record_property("duration_seconds", round(elapsed, 3))
    _assert_elapsed("failed_clients_investigation", elapsed)


@pytest.mark.asyncio
async def test_prompt_site_client_overview_live(
    prompt_registry, clients_tools, live_ctx, live_seed_data, record_property
):
    prompt_text = prompt_registry["site_client_overview"](live_seed_data["site_name"])
    assert "central_get_clients" in prompt_text

    t0 = time.perf_counter()
    clients = await clients_tools["central_get_clients"](
        live_ctx, site_id=live_seed_data["site_id"]
    )
    if _is_rate_limited_result(clients):
        pytest.skip(f"Rate limited by Central API: {clients}")
    elapsed = time.perf_counter() - t0
    record_property("duration_seconds", round(elapsed, 3))
    _assert_elapsed("site_client_overview", elapsed)


@pytest.mark.asyncio
@pytest.mark.parametrize("device_type", ["Access Point", "Switch", "Gateway"])
async def test_prompt_device_type_health_live(
    prompt_registry,
    devices_tools,
    alerts_tools,
    live_ctx,
    live_seed_data,
    device_type,
    record_property,
):
    prompt_text = prompt_registry["device_type_health"](
        live_seed_data["site_name"], device_type
    )
    assert "Normalize the requested type" in prompt_text

    normalized = {
        "Access Point": "ACCESS_POINT",
        "Switch": "SWITCH",
        "Gateway": "GATEWAY",
    }[device_type]

    t0 = time.perf_counter()
    devices = await devices_tools["central_get_devices"](
        live_ctx, site_id=live_seed_data["site_id"], device_type=normalized
    )
    if _is_rate_limited_result(devices):
        pytest.skip(f"Rate limited by Central API: {devices}")
    alerts = await alerts_tools["central_get_alerts"](
        live_ctx, site_id=live_seed_data["site_id"], device_type=device_type
    )
    if _is_rate_limited_result(alerts):
        pytest.skip(f"Rate limited by Central API: {alerts}")
    elapsed = time.perf_counter() - t0
    record_property("duration_seconds", round(elapsed, 3))
    _assert_elapsed(f"device_type_health[{device_type}]", elapsed)


@pytest.mark.asyncio
async def test_prompt_top_event_drivers_live(
    prompt_registry, events_tools, live_ctx, live_seed_data, record_property
):
    prompt_text = prompt_registry["top_event_drivers"](live_seed_data["site_name"])
    assert "event_id" in prompt_text

    t0 = time.perf_counter()
    count = await events_tools["central_get_events_count"](
        live_ctx,
        site_id=live_seed_data["site_id"],
        time_range="last_24h",
        response_mode="compact",
    )
    if isinstance(count, str):
        if _is_rate_limited_result(count):
            pytest.skip(f"Rate limited by Central API: {count}")
        pytest.skip(f"Event count error: {count}")
    event_ids = ",".join(item.event_id for item in count.event_names[:3]) or None
    categories = ",".join(count.categories[:2]) or None
    if count.total > 0 and (event_ids or categories):
        await events_tools["central_get_events"](
            live_ctx,
            site_id=live_seed_data["site_id"],
            time_range="last_24h",
            event_id=event_ids,
            category=categories,
            limit=20,
        )
    elapsed = time.perf_counter() - t0
    record_property("duration_seconds", round(elapsed, 3))
    _assert_elapsed("top_event_drivers", elapsed)


@pytest.mark.asyncio
async def test_prompt_critical_alerts_review_live(
    prompt_registry, sites_tools, alerts_tools, live_ctx, record_property
):
    prompt_text = prompt_registry["critical_alerts_review"]()
    assert "critical_alerts" in prompt_text

    t0 = time.perf_counter()
    mapping = await sites_tools["central_get_site_name_id_mapping"](live_ctx)
    critical_sites = [
        data["site_id"] for _, data in mapping.items() if data.get("critical_alerts", 0) > 0
    ][:3]
    for site_id in critical_sites:
        alerts = await alerts_tools["central_get_alerts"](
            live_ctx, site_id=site_id, status="Active"
        )
        if _is_rate_limited_result(alerts):
            pytest.skip(f"Rate limited by Central API: {alerts}")
    elapsed = time.perf_counter() - t0
    record_property("duration_seconds", round(elapsed, 3))
    _assert_elapsed("critical_alerts_review", elapsed)


@pytest.mark.asyncio
async def test_prompt_compare_site_health_live(
    prompt_registry,
    sites_tools,
    alerts_tools,
    live_ctx,
    live_seed_data,
    record_property,
):
    site_names = live_seed_data["compare_site_names"]
    prompt_text = prompt_registry["compare_site_health"](site_names)
    assert "side-by-side comparison table" in prompt_text

    t0 = time.perf_counter()
    try:
        mapping = await sites_tools["central_get_site_name_id_mapping"](live_ctx)
        await sites_tools["central_get_sites"](live_ctx, site_names=site_names)
        for name in site_names:
            site_id = mapping[name]["site_id"]
            alerts = await alerts_tools["central_get_alerts"](
                live_ctx, site_id=site_id, status="Active"
            )
            if _is_rate_limited_result(alerts):
                pytest.skip(f"Rate limited by Central API: {alerts}")
    except Exception as exc:
        if _is_rate_limited_error(exc):
            pytest.skip(f"Rate limited by Central API: {exc}")
        raise
    elapsed = time.perf_counter() - t0
    record_property("duration_seconds", round(elapsed, 3))
    _assert_elapsed("compare_site_health", elapsed)
