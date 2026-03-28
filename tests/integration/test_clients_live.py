import pytest
from tests.conftest import FakeMCP
from models import Client
import tools.clients as mod

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


async def test_get_clients_no_filter(tools, live_ctx):
    result = await tools["central_get_clients"](live_ctx)
    assert isinstance(result, list)
    assert all(isinstance(c, Client) for c in result)


async def test_get_clients_wired(tools, live_ctx):
    result = await tools["central_get_clients"](live_ctx, connection_type="Wired")
    assert isinstance(result, list)
    assert all(c.connection_type == "Wired" for c in result)


async def test_get_clients_wireless(tools, live_ctx):
    result = await tools["central_get_clients"](live_ctx, connection_type="Wireless")
    assert isinstance(result, list)
    assert all(c.connection_type == "Wireless" for c in result)


async def test_get_clients_connected_status(tools, live_ctx):
    result = await tools["central_get_clients"](live_ctx, status="Connected")
    assert isinstance(result, list)
    assert all(c.status == "Connected" for c in result)


async def test_get_clients_failed_status(tools, live_ctx):
    result = await tools["central_get_clients"](live_ctx, status="Failed")
    assert isinstance(result, list)


async def test_get_clients_wired_and_connected(tools, live_ctx):
    result = await tools["central_get_clients"](
        live_ctx, connection_type="Wired", status="Connected"
    )
    assert isinstance(result, list)
    assert all(c.connection_type == "Wired" and c.status == "Connected" for c in result)


async def test_find_client_by_mac(tools, live_ctx):
    clients = await tools["central_get_clients"](live_ctx)
    if not clients:
        pytest.skip("No clients available")
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
