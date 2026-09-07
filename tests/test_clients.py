import inspect
import json
from typing import get_type_hints
from unittest.mock import patch

import pytest
from fastmcp.exceptions import ToolError

import tools.clients as mod
from constants import MAX_PAGE_SIZE
from models import Client, ClientEnvelope
from tests.conftest import FakeMCP, annotated_field, make_ctx
from utils.clients import clean_client_data
from utils.cursor import decode_cursor, hash_query

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


def client_page(
    items: list[dict] | None = None,
    *,
    total: int | None = None,
    next_cursor: str | None = None,
) -> dict:
    page_items = items or []
    return {
        "items": page_items,
        "count": len(page_items),
        "total": len(page_items) if total is None else total,
        "next": next_cursor,
    }


def test_registers_only_client_survivor(tools):
    assert list(tools) == ["central_get_clients"]


def test_get_clients_limit_has_schema_bounds(tools):
    parameter = inspect.signature(tools["central_get_clients"]).parameters["limit"]
    assert parameter.default is None
    annotation = get_type_hints(tools["central_get_clients"], include_extras=True)[
        "limit"
    ]
    field = annotated_field(annotation)
    assert field.metadata[0].ge == 1
    assert field.metadata[1].le == MAX_PAGE_SIZE


@pytest.mark.asyncio
async def test_get_clients_no_odata_filters(tools):
    ctx = make_ctx()
    with patch(
        "tools.clients.Clients.get_clients",
        return_value=client_page(),
    ) as mock_api:
        await tools["central_get_clients"](ctx, site_id="site-1")
    call_kwargs = mock_api.call_args.kwargs
    assert call_kwargs["filter_str"] is None
    assert call_kwargs["site_id"] == "site-1"
    assert call_kwargs["next_page"] == 1
    assert call_kwargs["limit"] == mod.DEFAULT_CLIENT_LIMIT


@pytest.mark.asyncio
async def test_get_clients_status(tools):
    ctx = make_ctx()
    with patch(
        "tools.clients.Clients.get_clients",
        return_value=client_page(),
    ) as mock_api:
        await tools["central_get_clients"](ctx, status="Connected")
    assert mock_api.call_args.kwargs["filter_str"] == "status eq 'Connected'"


@pytest.mark.asyncio
async def test_get_clients_connection_type(tools):
    ctx = make_ctx()
    with patch(
        "tools.clients.Clients.get_clients",
        return_value=client_page(),
    ) as mock_api:
        await tools["central_get_clients"](ctx, connection_type="Wireless")
    assert (
        mock_api.call_args.kwargs["filter_str"] == "clientConnectionType eq 'Wireless'"
    )


@pytest.mark.asyncio
async def test_get_clients_status_and_connection_type(tools):
    ctx = make_ctx()
    with patch(
        "tools.clients.Clients.get_clients",
        return_value=client_page(),
    ) as mock_api:
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
    with patch(
        "tools.clients.Clients.get_clients",
        return_value=client_page(),
    ) as mock_api:
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
        "tools.clients.Clients.get_clients",
        return_value=client_page(
            [RAW_CLIENT, RAW_CLIENT_2],
            total=25,
        ),
    ):
        result = await tools["central_get_clients"](ctx)
    assert isinstance(result, ClientEnvelope)
    assert result.total == 25
    assert result.meta.total_available == 25
    assert result.items[0].mac == "11:22:33:44:55:66"
    assert result.items[0].name == "laptop-01"
    assert not hasattr(result.items[0], "macAddress")


@pytest.mark.asyncio
async def test_get_clients_empty_is_empty_envelope(tools):
    ctx = make_ctx()
    with patch(
        "tools.clients.Clients.get_clients",
        return_value=client_page(),
    ):
        result = await tools["central_get_clients"](ctx)
    assert isinstance(result, ClientEnvelope)
    assert result.items == []
    assert result.meta.returned == 0


@pytest.mark.asyncio
async def test_get_clients_page_one_emits_resumable_cursor(tools):
    ctx = make_ctx()
    with patch(
        "tools.clients.Clients.get_clients",
        return_value=client_page([RAW_CLIENT], total=125, next_cursor="2"),
    ):
        result = await tools["central_get_clients"](ctx, site_id="site-A", limit=50)

    decoded = decode_cursor(
        result.next_cursor,
        expected_tool="central_get_clients",
        expected_query_hash=hash_query(
            {
                "site_id": "site-A",
                "site_name": None,
                "serial_number": None,
                "connection_type": None,
                "status": None,
                "wlan_name": None,
                "vlan_id": None,
                "tunnel_type": None,
                "start_query_time": None,
                "end_query_time": None,
            }
        ),
    )

    assert len(result.items) == 1
    assert decoded.page_size == 50
    assert decoded.position == {"upstream_next": "2"}
    assert result.total == 125
    assert result.meta.total_available == 125
    assert result.truncated is False


@pytest.mark.asyncio
async def test_get_clients_last_page_is_terminal_and_not_truncated(tools):
    ctx = make_ctx()
    with patch(
        "tools.clients.Clients.get_clients",
        return_value=client_page([RAW_CLIENT], total=101, next_cursor=None),
    ):
        result = await tools["central_get_clients"](ctx, limit=50)

    assert result.next_cursor is None
    assert result.truncated is False


@pytest.mark.asyncio
async def test_get_clients_cursor_replay_fetches_next_upstream_page(tools):
    ctx = make_ctx()
    with patch(
        "tools.clients.Clients.get_clients",
        side_effect=[
            client_page([RAW_CLIENT], total=75, next_cursor="2"),
            client_page([RAW_CLIENT_2], total=75, next_cursor=None),
        ],
    ) as mock_api:
        first_page = await tools["central_get_clients"](
            ctx,
            site_id="site-A",
            limit=50,
        )
        second_page = await tools["central_get_clients"](
            ctx,
            site_id="site-A",
            cursor=first_page.next_cursor,
        )

    second_call = mock_api.call_args_list[1].kwargs
    assert second_call["next_page"] == 2
    assert second_call["limit"] == 50
    assert [item.mac for item in second_page.items] == ["aa:bb:cc:dd:ee:ff"]


@pytest.mark.asyncio
async def test_get_clients_rejects_limit_conflicting_with_cursor_page_size(tools):
    ctx = make_ctx()
    with patch(
        "tools.clients.Clients.get_clients",
        return_value=client_page([RAW_CLIENT], total=75, next_cursor="2"),
    ) as mock_api:
        first_page = await tools["central_get_clients"](ctx, limit=50)
        with pytest.raises(ToolError) as exc_info:
            await tools["central_get_clients"](
                ctx,
                limit=25,
                cursor=first_page.next_cursor,
            )

    error = json.loads(str(exc_info.value))
    assert error["code"] == "validation_error"
    assert error["retryable"] is False
    assert mock_api.call_count == 1


@pytest.mark.asyncio
async def test_get_clients_rejects_cursor_replayed_with_different_query(tools):
    ctx = make_ctx()
    with patch(
        "tools.clients.Clients.get_clients",
        return_value=client_page([RAW_CLIENT], total=75, next_cursor="2"),
    ) as mock_api:
        first_page = await tools["central_get_clients"](
            ctx,
            site_id="site-A",
            limit=50,
        )
        with pytest.raises(ToolError) as exc_info:
            await tools["central_get_clients"](
                ctx,
                site_id="site-B",
                cursor=first_page.next_cursor,
            )

    error = json.loads(str(exc_info.value))
    assert error["code"] == "validation_error"
    assert "invalid or stale cursor" in error["message"]
    assert error["retryable"] is False
    assert mock_api.call_count == 1


@pytest.mark.asyncio
async def test_get_clients_exact_mac_returns_cleaned_envelope(tools):
    ctx = make_ctx()
    with patch("tools.clients.Clients.get_client_details", return_value=RAW_CLIENT):
        result = await tools["central_get_clients"](
            ctx, mac_address="11:22:33:44:55:66"
        )
    assert isinstance(result, ClientEnvelope)
    assert [item.mac for item in result.items] == ["11:22:33:44:55:66"]
    assert result.next_cursor is None
    assert result.truncated is False


@pytest.mark.asyncio
async def test_get_clients_exact_mac_ignores_cursor(tools):
    ctx = make_ctx()
    with patch("tools.clients.Clients.get_client_details", return_value=RAW_CLIENT):
        result = await tools["central_get_clients"](
            ctx,
            mac_address="11:22:33:44:55:66",
            cursor="not-valid-base64!",
        )

    assert [item.mac for item in result.items] == ["11:22:33:44:55:66"]
    assert result.next_cursor is None
    assert result.truncated is False


@pytest.mark.asyncio
async def test_get_clients_exact_mac_none_is_empty_envelope(tools):
    ctx = make_ctx()
    with patch("tools.clients.Clients.get_client_details", return_value=None):
        result = await tools["central_get_clients"](
            ctx, mac_address="de:ad:be:ef:00:00"
        )
    assert isinstance(result, ClientEnvelope)
    assert result.items == []


@pytest.mark.asyncio
async def test_get_clients_missing_mac_exception_is_empty_envelope(tools):
    ctx = make_ctx()
    with patch(
        "tools.clients.Clients.get_client_details",
        side_effect=Exception("Resource not found for the given input."),
    ):
        result = await tools["central_get_clients"](
            ctx, mac_address="de:ad:00:00:00:01"
        )
    assert result.items == []


@pytest.mark.asyncio
async def test_get_clients_exact_mac_multiple_matches_raise_tool_error(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.clients.Clients.get_client_details",
            return_value=[RAW_CLIENT, RAW_CLIENT_2],
        ),
        pytest.raises(ToolError, match="Multiple clients found"),
    ):
        await tools["central_get_clients"](ctx, mac_address="11:22:33:44:55:66")


@pytest.mark.asyncio
async def test_get_clients_exact_mac_rejects_list_filters_before_connection(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.clients.api_context",
            side_effect=AssertionError("connection opened"),
        ) as mock_context,
        pytest.raises(ToolError, match=r"site_id.*exact mac_address"),
    ):
        await tools["central_get_clients"](
            ctx,
            mac_address="11:22:33:44:55:66",
            site_id="site-1",
        )
    mock_context.assert_not_called()


@pytest.mark.asyncio
async def test_get_clients_api_error_raises_tool_error(tools):
    ctx = make_ctx()
    with (
        patch(
            "tools.clients.Clients.get_clients",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(ToolError, match="boom"),
    ):
        await tools["central_get_clients"](ctx)


# ---------------------------------------------------------------------------
# clean_client_data
# ---------------------------------------------------------------------------

_RAW_WIRELESS_CLIENT = {
    "macAddress": "f0:1a:a0:3d:00:af",
    "clientName": "MyLaptop",
    "ipv4": "10.0.0.1",
    "ipv6": None,
    "hostName": "laptop.local",
    "clientConnectionType": "Wireless",
    "status": "Connected",
    "connectedDeviceSerial": "SN456",
    "connectedTo": "AP-01",
    "vlanId": "10",
    "wlanName": "CorpWLAN",
    "wirelessBand": "5GHz",
    "wirelessChannel": "60",
    "wirelessSecurity": "WPA3",
    "keyManagement": "SAE",
    "bssid": "aa:bb:cc:dd:ee:01",
    "radioMacAddress": "aa:bb:cc:dd:ee:00",
    "siteId": "site-1",
    "siteName": "HQ",
}

_RAW_WIRED_CLIENT = {
    "macAddress": "00:11:22:33:44:55",
    "clientConnectionType": "Wired",
    "status": "Connected",
    "port": "GE0/0/1",
    "siteId": "site-1",
    "siteName": "HQ",
}


def test_clean_client_data_wireless_fields_mapped():
    c = clean_client_data([_RAW_WIRELESS_CLIENT])[0]
    assert isinstance(c, Client)
    assert c.mac == "f0:1a:a0:3d:00:af"
    assert c.connection_type == "Wireless"
    assert c.wlan_name == "CorpWLAN"
    assert c.wireless_band == "5GHz"
    assert c.bssid == "aa:bb:cc:dd:ee:01"


def test_clean_client_data_wireless_strips_port():
    c = clean_client_data([_RAW_WIRELESS_CLIENT])[0]
    assert c.port is None


def test_clean_client_data_wired_keeps_port():
    c = clean_client_data([_RAW_WIRED_CLIENT])[0]
    assert c.port == "GE0/0/1"


def test_clean_client_data_wired_strips_wireless_fields():
    c = clean_client_data([_RAW_WIRED_CLIENT])[0]
    assert c.wlan_name is None
    assert c.bssid is None
    assert c.wireless_band is None
    assert c.radio_mac is None
