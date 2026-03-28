import pytest
from unittest.mock import patch
import tools.clients as mod
from tests.conftest import FakeMCP, make_ctx

RAW_CLIENT = {
    "macAddress": "11:22:33:44:55:66",
    "clientName": "laptop-01",
    "ipv4": "192.168.1.10",
    "ipv6": None,
    "hostName": "laptop-01.local",
    "clientConnectionType": "Wireless",
    "clientOperatingSystem": "Windows",
    "clientVendor": "Dell",
    "clientManufacturer": "Dell Inc.",
    "clientCategory": "Laptop",
    "clientFunction": None,
    "clientCapabilities": None,
    "status": "Connected",
    "connectedDeviceType": "ACCESS_POINT",
    "connectedDeviceSerial": "AP123",
    "connectedTo": "ap-lobby",
    "connectedAt": "2024-01-01T00:00:00Z",
    "lastSeenAt": "2024-01-01T01:00:00Z",
    "port": None,
    "vlanId": "10",
    "tunnelType": "User-based",
    "tunnelId": None,
    "wlanName": "Corp-WiFi",
    "wirelessBand": "5GHz",
    "wirelessChannel": "36",
    "wirelessSecurity": "WPA3",
    "keyManagement": "SAE",
    "bssid": "aa:bb:cc:dd:ee:ff",
    "radioMacAddress": "aa:bb:cc:dd:ee:ff",
    "userName": "user@corp.com",
    "authenticationType": "802.1X",
    "siteId": "site-1",
    "siteName": "HQ",
    "role": "Employee",
    "clientTags": None,
}


@pytest.fixture
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


@pytest.mark.asyncio
async def test_get_clients_no_odata_filters(tools):
    ctx = make_ctx()
    with patch("tools.clients.Clients.get_all_clients", return_value=[]) as mock_api:
        await tools["central_get_clients"](ctx, site_id="site-1")
    call_kwargs = mock_api.call_args.kwargs
    assert call_kwargs["filter_str"] is None
    assert call_kwargs["site_id"] == "site-1"


@pytest.mark.asyncio
async def test_get_clients_status(tools):
    ctx = make_ctx()
    with patch("tools.clients.Clients.get_all_clients", return_value=[]) as mock_api:
        await tools["central_get_clients"](ctx, status="Connected")
    assert mock_api.call_args.kwargs["filter_str"] == "status eq 'Connected'"


@pytest.mark.asyncio
async def test_get_clients_connection_type(tools):
    ctx = make_ctx()
    with patch("tools.clients.Clients.get_all_clients", return_value=[]) as mock_api:
        await tools["central_get_clients"](ctx, connection_type="Wireless")
    assert (
        mock_api.call_args.kwargs["filter_str"] == "clientConnectionType eq 'Wireless'"
    )


@pytest.mark.asyncio
async def test_get_clients_status_and_connection_type(tools):
    ctx = make_ctx()
    with patch("tools.clients.Clients.get_all_clients", return_value=[]) as mock_api:
        await tools["central_get_clients"](
            ctx, status="Connected", connection_type="Wireless"
        )
    filter_str = mock_api.call_args.kwargs["filter_str"]
    assert "status eq 'Connected'" in filter_str
    assert "clientConnectionType eq 'Wireless'" in filter_str
    assert " and " in filter_str


@pytest.mark.asyncio
async def test_get_clients_tunnel_type(tools):
    ctx = make_ctx()
    with patch("tools.clients.Clients.get_all_clients", return_value=[]) as mock_api:
        await tools["central_get_clients"](ctx, tunnel_type="Port-based")
    assert mock_api.call_args.kwargs["filter_str"] == "tunnelType eq 'Port-based'"


RAW_CLIENT_2 = {
    **RAW_CLIENT,
    "macAddress": "aa:bb:cc:dd:ee:ff",
    "clientName": "laptop-02",
}


@pytest.mark.asyncio
async def test_get_clients_result_cleaned(tools):
    ctx = make_ctx()
    with patch(
        "tools.clients.Clients.get_all_clients", return_value=[RAW_CLIENT, RAW_CLIENT_2]
    ):
        result = await tools["central_get_clients"](ctx)
    assert result[0].mac == "11:22:33:44:55:66"
    assert result[0].name == "laptop-01"
    assert not hasattr(result[0], "macAddress")


@pytest.mark.asyncio
async def test_find_client_returns_cleaned_result(tools):
    ctx = make_ctx()
    with patch("tools.clients.Clients.get_client_details", return_value=RAW_CLIENT):
        result = await tools["central_find_client"](
            ctx, mac_address="11:22:33:44:55:66"
        )
    assert result.mac == "11:22:33:44:55:66"


@pytest.mark.asyncio
async def test_find_client_none_returns_error_string(tools):
    ctx = make_ctx()
    with patch("tools.clients.Clients.get_client_details", return_value=None):
        result = await tools["central_find_client"](
            ctx, mac_address="de:ad:be:ef:00:00"
        )
    assert "de:ad:be:ef:00:00" in result


@pytest.mark.asyncio
async def test_find_client_missing_mac_returns_error_string(tools):
    ctx = make_ctx()
    with patch(
        "tools.clients.Clients.get_client_details",
        side_effect=Exception("Resource not found for the given input."),
    ):
        result = await tools["central_find_client"](
            ctx, mac_address="de:ad:00:00:00:01"
        )
    assert "de:ad:00:00:00:01" in result
