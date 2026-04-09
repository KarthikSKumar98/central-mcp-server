import pytest

import tools.clients as mod
from models import Client
from tests.conftest import FakeMCP

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


@pytest.fixture(scope="module")
async def mixed_site_id(tools, live_ctx):
    """Return a site_id that has both Wired and Wireless clients.

    Falls back to the site with the most clients if no mixed site exists.
    Skips if no clients are available at all.
    """
    all_clients = await tools["central_get_clients"](live_ctx)
    if not isinstance(all_clients, list) or not all_clients:
        pytest.skip("No clients available")

    # Group site_ids by connection types present
    site_types: dict[str, set[str]] = {}
    site_counts: dict[str, int] = {}
    for c in all_clients:
        if not c.site_id or not c.connection_type:
            continue
        site_types.setdefault(c.site_id, set()).add(c.connection_type)
        site_counts[c.site_id] = site_counts.get(c.site_id, 0) + 1

    if not site_counts:
        pytest.skip("No clients with site_id available")

    # Prefer a site with both Wired and Wireless clients
    for site_id, types in site_types.items():
        if "Wired" in types and "Wireless" in types:
            return site_id

    # Fall back to the busiest site
    return max(site_counts, key=lambda s: site_counts[s])


async def test_get_clients_no_filter(tools, live_ctx):
    result = await tools["central_get_clients"](live_ctx)
    assert isinstance(result, list)
    assert all(isinstance(c, Client) for c in result)


async def test_get_clients_wired(tools, live_ctx, mixed_site_id):
    result = await tools["central_get_clients"](
        live_ctx, site_id=mixed_site_id, connection_type="Wired"
    )
    if isinstance(result, str):
        pytest.skip("No wired clients in site")
    assert isinstance(result, list)
    assert all(c.connection_type == "Wired" for c in result)


async def test_get_clients_wireless(tools, live_ctx, mixed_site_id):
    result = await tools["central_get_clients"](
        live_ctx, site_id=mixed_site_id, connection_type="Wireless"
    )
    if isinstance(result, str):
        pytest.skip("No wireless clients in site")
    assert isinstance(result, list)
    assert all(c.connection_type == "Wireless" for c in result)


async def test_get_clients_connected_status(tools, live_ctx):
    result = await tools["central_get_clients"](live_ctx, status="Connected")
    assert isinstance(result, list)
    assert all(c.status == "Connected" for c in result)


async def test_get_clients_failed_status(tools, live_ctx):
    result = await tools["central_get_clients"](live_ctx, status="Failed")
    assert isinstance(result, list)


async def test_get_clients_wired_and_connected(tools, live_ctx, mixed_site_id):
    result = await tools["central_get_clients"](
        live_ctx, site_id=mixed_site_id, connection_type="Wired", status="Connected"
    )
    if isinstance(result, str):
        pytest.skip("No wired connected clients in site")
    assert isinstance(result, list)
    assert all(c.connection_type == "Wired" and c.status == "Connected" for c in result)


async def test_find_client_by_mac(tools, live_ctx, mixed_site_id):
    clients = await tools["central_get_clients"](live_ctx, site_id=mixed_site_id)
    if not isinstance(clients, list) or not clients:
        pytest.skip("No clients available in site")
    mac = clients[0].mac
    if not mac:
        pytest.skip("First client has no MAC address")
    result = await tools["central_find_client"](live_ctx, mac_address=mac)
    assert isinstance(result, Client)
    assert result.mac == mac


async def test_find_client_not_found(tools, live_ctx):
    result = await tools["central_find_client"](
        live_ctx, mac_address="00:00:00:00:00:00"
    )
    assert isinstance(result, str)
