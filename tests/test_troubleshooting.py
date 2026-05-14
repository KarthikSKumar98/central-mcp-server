from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.server.elicitation import AcceptedElicitation
from mcp import McpError
from mcp.server.elicitation import CancelledElicitation, DeclinedElicitation
from mcp.types import ErrorData

import tools.troubleshooting as mod
from models import TroubleshootingResult
from tests.conftest import FakeMCP, make_ctx

# ---------------------------------------------------------------------------
# Shared fixtures / raw data
# ---------------------------------------------------------------------------

RAW_AP = {
    "serialNumber": "AP001",
    "macAddress": "aa:bb:cc:00:00:01",
    "deviceType": "ACCESS_POINT",
    "model": "AP-555",
    "deviceName": "ap-01",
    "isProvisioned": "Yes",
    "status": "ONLINE",
    "siteId": "site-1",
    "siteName": "HQ",
    "partNumber": "PN1",
    "deviceFunction": None,
    "role": None,
    "deployment": None,
    "tier": None,
    "firmwareVersion": "10.0",
    "deviceGroupName": "APs",
    "scopeId": None,
    "ipv4": "10.0.0.10",
    "stackId": None,
}

RAW_CX = {**RAW_AP, "serialNumber": "SW001", "deviceType": "SWITCH", "model": "6300M", "deviceName": "cx-01"}
RAW_AOSS = {**RAW_AP, "serialNumber": "SW002", "deviceType": "SWITCH", "model": "2930F", "deviceName": "aoss-01"}
RAW_GW = {**RAW_AP, "serialNumber": "GW001", "deviceType": "GATEWAY", "model": "9004", "deviceName": "gw-01"}

COMPLETED_TASK = {"status": "COMPLETED", "result": {"output": "ping OK"}, "location": "/tasks/T001"}
RUNNING_TASK = {"status": "RUNNING", "result": None, "location": "/tasks/T002"}
FAILED_TASK = {"status": "FAILED", "result": None, "error": "Timeout", "location": "/tasks/T003"}


@pytest.fixture
def tools():
    fake = FakeMCP()
    mod.register(fake)
    return fake._tools


# ---------------------------------------------------------------------------
# Helper: patch inventory + initiate + get_result
# ---------------------------------------------------------------------------

def _patch_inventory(raw_device):
    return patch(
        "utils.troubleshooting.MonitoringDevices.get_all_device_inventory",
        return_value=[raw_device],
    )


# ---------------------------------------------------------------------------
# central_run_network_test — parameter validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_network_test_invalid_max_attempts(tools):
    ctx = make_ctx()
    result = await tools["central_run_network_test"](
        ctx, test_type="ping", serial_number="AP001", destination="8.8.8.8", max_attempts=0
    )
    assert result.startswith("Error validating parameters:")


@pytest.mark.asyncio
async def test_network_test_invalid_poll_interval(tools):
    ctx = make_ctx()
    result = await tools["central_run_network_test"](
        ctx, test_type="ping", serial_number="AP001", destination="8.8.8.8", poll_interval=0
    )
    assert result.startswith("Error validating parameters:")


@pytest.mark.asyncio
async def test_network_test_tcp_requires_port(tools):
    ctx = make_ctx()
    with _patch_inventory(RAW_AP):
        result = await tools["central_run_network_test"](
            ctx, test_type="tcp", serial_number="AP001", destination="10.0.0.1"
        )
    assert result.startswith("Error validating parameters:")


# ---------------------------------------------------------------------------
# central_run_network_test — device not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_network_test_serial_not_found(tools):
    ctx = make_ctx()
    with patch(
        "utils.troubleshooting.MonitoringDevices.get_all_device_inventory",
        return_value=[],
    ):
        result = await tools["central_run_network_test"](
            ctx, test_type="ping", serial_number="UNKNOWN", destination="8.8.8.8"
        )
    assert result.startswith("Error resolving device family:")


# ---------------------------------------------------------------------------
# central_run_network_test — unsupported device/test pairing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_network_test_unsupported_pairing_tcp_on_switch(tools):
    """Tcp tests are only supported on APs; should return a clear error for a switch."""
    ctx = make_ctx()
    with _patch_inventory(RAW_CX):
        result = await tools["central_run_network_test"](
            ctx, test_type="tcp", serial_number="SW001", destination="10.0.0.1", port=443
        )
    assert result.startswith("Error running tcp test:")
    assert "aps" in result


# ---------------------------------------------------------------------------
# central_run_network_test — ping success paths per device family
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ping_ap_success(tools):
    ctx = make_ctx()
    with _patch_inventory(RAW_AP), \
         patch("utils.troubleshooting.Troubleshooting.initiate_ping_aps_test", return_value={"location": "/tasks/T001"}) as mock_init, \
         patch("utils.troubleshooting.Troubleshooting.get_ping_test_result", return_value={"status": "COMPLETED", "result": {"output": "ping OK"}, "rawOutput": "PING 8.8.8.8: 5 data bytes\n5 packets received"}), \
         patch("asyncio.sleep"):
        result = await tools["central_run_network_test"](
            ctx, test_type="ping", serial_number="AP001", destination="8.8.8.8", max_attempts=1, poll_interval=1
        )
    assert isinstance(result, TroubleshootingResult)
    assert result.status == "COMPLETED"
    assert result.device_type == "aps"
    assert result.raw_output == "PING 8.8.8.8: 5 data bytes\n5 packets received"
    mock_init.assert_called_once()
    assert mock_init.call_args.kwargs["destination"] == "8.8.8.8"
    assert mock_init.call_args.kwargs.get("include_raw_output") is True


@pytest.mark.asyncio
async def test_ping_cx_success(tools):
    ctx = make_ctx()
    with _patch_inventory(RAW_CX), \
         patch("utils.troubleshooting.Troubleshooting.initiate_ping_cx_test", return_value={"location": "/tasks/T001"}) as mock_init, \
         patch("utils.troubleshooting.Troubleshooting.get_ping_test_result", return_value={"status": "COMPLETED", "result": {}}), \
         patch("asyncio.sleep"):
        result = await tools["central_run_network_test"](
            ctx, test_type="ping", serial_number="SW001", destination="8.8.8.8", vrf="MGMT",
            max_attempts=1, poll_interval=1
        )
    assert isinstance(result, TroubleshootingResult)
    assert result.device_type == "cx"
    assert mock_init.call_args.kwargs.get("vrf_name") == "MGMT"


@pytest.mark.asyncio
async def test_ping_aoss_success(tools):
    ctx = make_ctx()
    with _patch_inventory(RAW_AOSS), \
         patch("utils.troubleshooting.Troubleshooting.initiate_ping_aoss_test", return_value={"location": "/tasks/T001"}) as mock_init, \
         patch("utils.troubleshooting.Troubleshooting.get_ping_test_result", return_value={"status": "COMPLETED", "result": {}}), \
         patch("asyncio.sleep"):
        result = await tools["central_run_network_test"](
            ctx, test_type="ping", serial_number="SW002", destination="8.8.8.8",
            max_attempts=1, poll_interval=1
        )
    assert isinstance(result, TroubleshootingResult)
    assert result.device_type == "aos-s"
    mock_init.assert_called_once()


@pytest.mark.asyncio
async def test_ping_gateway_success(tools):
    ctx = make_ctx()
    with _patch_inventory(RAW_GW), \
         patch("utils.troubleshooting.Troubleshooting.initiate_ping_gateways_test", return_value={"location": "/tasks/T001"}) as mock_init, \
         patch("utils.troubleshooting.Troubleshooting.get_ping_test_result", return_value={"status": "COMPLETED", "result": {}}), \
         patch("asyncio.sleep"):
        result = await tools["central_run_network_test"](
            ctx, test_type="ping", serial_number="GW001", destination="8.8.8.8",
            max_attempts=1, poll_interval=1
        )
    assert isinstance(result, TroubleshootingResult)
    assert result.device_type == "gateways"
    mock_init.assert_called_once()


# ---------------------------------------------------------------------------
# central_run_network_test — other test types
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_traceroute_ap_success(tools):
    ctx = make_ctx()
    with _patch_inventory(RAW_AP), \
         patch("utils.troubleshooting.Troubleshooting.initiate_traceroute_aps_test", return_value={"location": "/tasks/T001"}) as mock_tr_init, \
         patch("utils.troubleshooting.Troubleshooting.get_traceroute_test_result", return_value={"status": "COMPLETED", "result": {}, "rawOutput": "traceroute to 8.8.8.8\n 1  10.0.0.1  1.234 ms"}), \
         patch("asyncio.sleep"):
        result = await tools["central_run_network_test"](
            ctx, test_type="traceroute", serial_number="AP001", destination="8.8.8.8",
            max_attempts=1, poll_interval=1
        )
    assert isinstance(result, TroubleshootingResult)
    assert result.status == "COMPLETED"
    assert result.raw_output == "traceroute to 8.8.8.8\n 1  10.0.0.1  1.234 ms"
    assert mock_tr_init.call_args.kwargs.get("include_raw_output") is True


@pytest.mark.asyncio
async def test_http_test_cx_success(tools):
    ctx = make_ctx()
    with _patch_inventory(RAW_CX), \
         patch("utils.troubleshooting.Troubleshooting.initiate_http_test", return_value={"location": "/tasks/T001"}) as mock_init, \
         patch("utils.troubleshooting.Troubleshooting.get_http_test_result", return_value={"status": "COMPLETED", "result": {}}), \
         patch("asyncio.sleep"):
        result = await tools["central_run_network_test"](
            ctx, test_type="http", serial_number="SW001", destination="http://example.com",
            max_attempts=1, poll_interval=1
        )
    assert isinstance(result, TroubleshootingResult)
    assert mock_init.call_args.kwargs["device_type"] == "cx"


@pytest.mark.asyncio
async def test_https_test_cx_uses_http_result_endpoint(tools):
    """CX HTTPS initiate posts to /http with protocol=HTTPS; result must be polled from /http/async-operations/."""
    ctx = make_ctx()
    with _patch_inventory(RAW_CX), \
         patch("utils.troubleshooting.Troubleshooting.initiate_https_cx_test", return_value={"location": "/tasks/T001"}) as mock_init, \
         patch("utils.troubleshooting.Troubleshooting.get_http_test_result", return_value={"status": "COMPLETED", "result": {}}) as mock_get, \
         patch("asyncio.sleep"):
        result = await tools["central_run_network_test"](
            ctx, test_type="https", serial_number="SW001", destination="https://example.com",
            max_attempts=1, poll_interval=1
        )
    assert isinstance(result, TroubleshootingResult)
    mock_init.assert_called_once()
    mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_tcp_ap_success(tools):
    ctx = make_ctx()
    with _patch_inventory(RAW_AP), \
         patch("utils.troubleshooting.Troubleshooting.initiate_tcp_test", return_value={"location": "/tasks/T001"}) as mock_init, \
         patch("utils.troubleshooting.Troubleshooting.get_tcp_test_result", return_value={"status": "COMPLETED", "result": {}}), \
         patch("asyncio.sleep"):
        result = await tools["central_run_network_test"](
            ctx, test_type="tcp", serial_number="AP001", destination="10.0.0.1", port=443,
            max_attempts=1, poll_interval=1
        )
    assert isinstance(result, TroubleshootingResult)
    assert mock_init.call_args.kwargs["port"] == 443
    assert mock_init.call_args.kwargs["host"] == "10.0.0.1"


@pytest.mark.asyncio
async def test_nslookup_ap_success(tools):
    ctx = make_ctx()
    with _patch_inventory(RAW_AP), \
         patch("utils.troubleshooting.Troubleshooting.initiate_nslookup_test", return_value={"location": "/tasks/T001"}) as mock_init, \
         patch("utils.troubleshooting.Troubleshooting.get_nslookup_test_result", return_value={"status": "COMPLETED", "result": {}}), \
         patch("asyncio.sleep"):
        result = await tools["central_run_network_test"](
            ctx, test_type="nslookup", serial_number="AP001", destination="example.com",
            name_server="8.8.8.8", max_attempts=1, poll_interval=1
        )
    assert isinstance(result, TroubleshootingResult)
    assert mock_init.call_args.kwargs["host"] == "example.com"
    assert mock_init.call_args.kwargs["dns_server"] == "8.8.8.8"


# ---------------------------------------------------------------------------
# central_run_network_test — FAILED task result
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_network_test_failed_task(tools):
    ctx = make_ctx()
    with _patch_inventory(RAW_AP), \
         patch("utils.troubleshooting.Troubleshooting.initiate_ping_aps_test", return_value={"location": "/tasks/T003"}), \
         patch("utils.troubleshooting.Troubleshooting.get_ping_test_result", return_value={"status": "FAILED", "error": "Timeout"}), \
         patch("asyncio.sleep"):
        result = await tools["central_run_network_test"](
            ctx, test_type="ping", serial_number="AP001", destination="8.8.8.8",
            max_attempts=1, poll_interval=1
        )
    assert isinstance(result, TroubleshootingResult)
    assert result.status == "FAILED"
    assert result.error == "Timeout"


# ---------------------------------------------------------------------------
# central_run_network_test — extra wait on still-running task
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_network_test_extra_wait_on_running(tools):
    """If task is still RUNNING after max_attempts, one extra wait+fetch is performed."""
    ctx = make_ctx()
    get_results = [
        {"status": "RUNNING", "result": None},  # first poll — still running
        {"status": "COMPLETED", "result": {"output": "done"}},  # extra wait poll
    ]
    call_count = {"n": 0}

    def fake_get_result(**_kwargs):
        resp = get_results[min(call_count["n"], len(get_results) - 1)]
        call_count["n"] += 1
        return resp

    with _patch_inventory(RAW_AP), \
         patch("utils.troubleshooting.Troubleshooting.initiate_ping_aps_test", return_value={"location": "/tasks/T002"}), \
         patch("utils.troubleshooting.Troubleshooting.get_ping_test_result", side_effect=fake_get_result), \
         patch("asyncio.sleep"):
        result = await tools["central_run_network_test"](
            ctx, test_type="ping", serial_number="AP001", destination="8.8.8.8",
            max_attempts=1, poll_interval=1
        )
    assert isinstance(result, TroubleshootingResult)
    assert result.status == "COMPLETED"
    assert call_count["n"] == 2  # initial poll + extra wait poll


# ---------------------------------------------------------------------------
# central_run_network_test — initiate fails with exception
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_network_test_initiate_exception(tools):
    ctx = make_ctx()
    with _patch_inventory(RAW_AP), \
         patch("utils.troubleshooting.Troubleshooting.initiate_ping_aps_test", side_effect=Exception("API error")):
        result = await tools["central_run_network_test"](
            ctx, test_type="ping", serial_number="AP001", destination="8.8.8.8"
        )
    assert isinstance(result, str)
    assert result.startswith("Error running ping test:")


# ---------------------------------------------------------------------------
# central_run_show_commands — parameter validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_show_commands_empty_list(tools):
    ctx = make_ctx()
    result = await tools["central_run_show_commands"](ctx, serial_number="AP001", commands=[])
    assert result.startswith("Error validating parameters:")


@pytest.mark.asyncio
async def test_show_commands_exceeds_max(tools):
    ctx = make_ctx()
    result = await tools["central_run_show_commands"](
        ctx, serial_number="AP001", commands=[f"show vlan {i}" for i in range(6)]
    )
    assert result.startswith("Error validating parameters:")


@pytest.mark.asyncio
async def test_show_commands_invalid_prefix(tools):
    ctx = make_ctx()
    result = await tools["central_run_show_commands"](
        ctx, serial_number="AP001", commands=["reboot now"]
    )
    assert result.startswith("Error validating parameters:")
    assert "reboot now" in result


# ---------------------------------------------------------------------------
# central_run_show_commands — catalog validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_show_commands_unmatched_returns_catalog(tools):
    """Unmatched command returns error with catalog included in the message."""
    ctx = make_ctx()
    catalog = ["show version", "show arp", "show interfaces"]
    with _patch_inventory(RAW_AP), \
         patch("utils.troubleshooting.Troubleshooting.list_show_commands", return_value=catalog):
        result = await tools["central_run_show_commands"](
            ctx, serial_number="AP001", commands=["show nonsense"]
        )
    assert result.startswith("Error validating show commands:")
    assert "show nonsense" in result
    assert "show version" in result


# ---------------------------------------------------------------------------
# central_run_show_commands — success path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_show_commands_success(tools):
    ctx = make_ctx()
    catalog = ["show version", "show arp"]
    with _patch_inventory(RAW_AP), \
         patch("utils.troubleshooting.Troubleshooting.list_show_commands", return_value=catalog), \
         patch("utils.troubleshooting.Troubleshooting.initiate_show_commands", return_value={"location": "/tasks/T001"}) as mock_init, \
         patch("utils.troubleshooting.Troubleshooting.get_show_commands_result", return_value={"status": "COMPLETED", "result": {"output": "Version 10.0"}}), \
         patch("asyncio.sleep"):
        result = await tools["central_run_show_commands"](
            ctx, serial_number="AP001", commands=["show version"], max_attempts=1, poll_interval=1
        )
    assert isinstance(result, TroubleshootingResult)
    assert result.status == "COMPLETED"
    assert mock_init.call_args.kwargs["commands"] == ["show version"]
    assert mock_init.call_args.kwargs["device_type"] == "aps"


# ---------------------------------------------------------------------------
# central_run_show_commands — show commands exception
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_show_commands_run_exception(tools):
    ctx = make_ctx()
    catalog = ["show version"]
    with _patch_inventory(RAW_AP), \
         patch("utils.troubleshooting.Troubleshooting.list_show_commands", return_value=catalog), \
         patch("utils.troubleshooting.Troubleshooting.initiate_show_commands", side_effect=Exception("Central error")):
        result = await tools["central_run_show_commands"](
            ctx, serial_number="AP001", commands=["show version"]
        )
    assert isinstance(result, str)
    assert result.startswith("Error running show commands:")


# ---------------------------------------------------------------------------
# central_bounce_port
# ---------------------------------------------------------------------------

_IFACE_RESPONSE = {"items": [{"name": "1/1/1", "operStatus": "UP", "speed": "1G", "description": "uplink"}]}
_BOUNCE_COMPLETED = {"status": "COMPLETED", "result": {"output": "bounce OK"}, "location": "/tasks/T001"}


# --- Parameter validation ---

@pytest.mark.asyncio
async def test_bounce_invalid_max_attempts(tools):
    ctx = make_ctx()
    result = await tools["central_bounce_port"](
        ctx, serial_number="SW001", ports=["1/1/1"], bounce_type="port", max_attempts=0
    )
    assert result.startswith("Error validating parameters:")


@pytest.mark.asyncio
async def test_bounce_invalid_poll_interval(tools):
    ctx = make_ctx()
    result = await tools["central_bounce_port"](
        ctx, serial_number="SW001", ports=["1/1/1"], bounce_type="port", poll_interval=0
    )
    assert result.startswith("Error validating parameters:")


@pytest.mark.asyncio
async def test_bounce_empty_ports(tools):
    ctx = make_ctx()
    result = await tools["central_bounce_port"](
        ctx, serial_number="SW001", ports=[], bounce_type="port"
    )
    assert result.startswith("Error validating parameters:")


@pytest.mark.asyncio
async def test_bounce_too_many_ports(tools):
    ctx = make_ctx()
    result = await tools["central_bounce_port"](
        ctx, serial_number="SW001", ports=[f"1/1/{i}" for i in range(6)], bounce_type="port"
    )
    assert result.startswith("Error validating parameters:")


# --- Family rejection ---

@pytest.mark.asyncio
async def test_bounce_unsupported_family_ap(tools):
    ctx = make_ctx()
    with _patch_inventory(RAW_AP):
        result = await tools["central_bounce_port"](
            ctx, serial_number="AP001", ports=["1/1/1"], bounce_type="port"
        )
    assert result.startswith("Error running port bounce:")


# --- Unknown port ---

@pytest.mark.asyncio
async def test_bounce_unknown_port(tools):
    ctx = make_ctx()
    ctx.elicit = AsyncMock()
    with _patch_inventory(RAW_CX), \
         patch("utils.troubleshooting.MonitoringSwitches.get_switch_interfaces", return_value=_IFACE_RESPONSE):
        result = await tools["central_bounce_port"](
            ctx, serial_number="SW001", ports=["1/1/99"], bounce_type="port"
        )
    assert result.startswith("Error validating ports:")
    ctx.elicit.assert_not_called()


# --- Decline / cancel ---

@pytest.mark.asyncio
async def test_bounce_declined(tools):
    ctx = make_ctx()
    ctx.elicit = AsyncMock(return_value=DeclinedElicitation())
    with _patch_inventory(RAW_CX), \
         patch("utils.troubleshooting.MonitoringSwitches.get_switch_interfaces", return_value=_IFACE_RESPONSE), \
         patch("utils.troubleshooting.Troubleshooting.initiate_port_bounce_test") as mock_init:
        result = await tools["central_bounce_port"](
            ctx, serial_number="SW001", ports=["1/1/1"], bounce_type="port"
        )
    assert isinstance(result, str)
    assert "bounce" in result.lower()
    mock_init.assert_not_called()


@pytest.mark.asyncio
async def test_bounce_cancelled(tools):
    ctx = make_ctx()
    ctx.elicit = AsyncMock(return_value=CancelledElicitation())
    with _patch_inventory(RAW_CX), \
         patch("utils.troubleshooting.MonitoringSwitches.get_switch_interfaces", return_value=_IFACE_RESPONSE), \
         patch("utils.troubleshooting.Troubleshooting.initiate_port_bounce_test") as mock_init:
        result = await tools["central_bounce_port"](
            ctx, serial_number="SW001", ports=["1/1/1"], bounce_type="port"
        )
    assert isinstance(result, str)
    mock_init.assert_not_called()


# --- Happy paths ---

@pytest.mark.asyncio
async def test_bounce_port_cx_success(tools):
    ctx = make_ctx()
    ctx.elicit = AsyncMock(return_value=AcceptedElicitation(data={}))
    with _patch_inventory(RAW_CX), \
         patch("utils.troubleshooting.MonitoringSwitches.get_switch_interfaces", return_value=_IFACE_RESPONSE), \
         patch("utils.troubleshooting.Troubleshooting.initiate_port_bounce_test", return_value={"location": "/tasks/T001"}) as mock_init, \
         patch("utils.troubleshooting.Troubleshooting.get_port_bounce_test_result", return_value=_BOUNCE_COMPLETED), \
         patch("asyncio.sleep"):
        result = await tools["central_bounce_port"](
            ctx, serial_number="SW001", ports=["1/1/1"], bounce_type="port",
            max_attempts=1, poll_interval=1
        )
    assert isinstance(result, TroubleshootingResult)
    assert result.status == "COMPLETED"
    mock_init.assert_called_once()
    assert mock_init.call_args.kwargs["ports"] == ["1/1/1"]
    assert mock_init.call_args.kwargs["device_type"] == "cx"


@pytest.mark.asyncio
async def test_bounce_poe_aoss_success(tools):
    ctx = make_ctx()
    ctx.elicit = AsyncMock(return_value=AcceptedElicitation(data={}))
    with _patch_inventory(RAW_AOSS), \
         patch("utils.troubleshooting.MonitoringSwitches.get_switch_interfaces", return_value=_IFACE_RESPONSE), \
         patch("utils.troubleshooting.Troubleshooting.initiate_poe_bounce_test", return_value={"location": "/tasks/T001"}) as mock_init, \
         patch("utils.troubleshooting.Troubleshooting.get_poe_bounce_test_result", return_value=_BOUNCE_COMPLETED), \
         patch("asyncio.sleep"):
        result = await tools["central_bounce_port"](
            ctx, serial_number="SW002", ports=["1/1/1"], bounce_type="poe",
            max_attempts=1, poll_interval=1
        )
    assert isinstance(result, TroubleshootingResult)
    assert result.status == "COMPLETED"
    mock_init.assert_called_once()


@pytest.mark.asyncio
async def test_bounce_port_gateway_success(tools):
    ctx = make_ctx()
    ctx.elicit = AsyncMock(return_value=AcceptedElicitation(data={}))
    with _patch_inventory(RAW_GW), \
         patch("utils.troubleshooting.MonitoringGateways.get_gateway_interfaces", return_value=_IFACE_RESPONSE), \
         patch("utils.troubleshooting.Troubleshooting.initiate_port_bounce_test", return_value={"location": "/tasks/T001"}) as mock_init, \
         patch("utils.troubleshooting.Troubleshooting.get_port_bounce_test_result", return_value=_BOUNCE_COMPLETED), \
         patch("asyncio.sleep"):
        result = await tools["central_bounce_port"](
            ctx, serial_number="GW001", ports=["1/1/1"], bounce_type="port",
            max_attempts=1, poll_interval=1
        )
    assert isinstance(result, TroubleshootingResult)
    assert result.status == "COMPLETED"
    mock_init.assert_called_once()
    assert mock_init.call_args.kwargs["device_type"] == "gateways"


# --- PoE fields in approval message ---

@pytest.mark.asyncio
async def test_bounce_poe_shows_poe_fields_in_elicit_message(tools):
    ctx = make_ctx()
    ctx.elicit = AsyncMock(return_value=DeclinedElicitation())
    poe_iface_response = {
        "items": [{
            "name": "1/1/1", "operStatus": "Up", "speed": 2500,
            "poeClass": "802.3at (PoE+)", "poeStatus": "Drawing Watts",
            "description": "Campus-AP",
            "neighbour": "CP-DFW-AP07", "neighbourType": "Access Point",
            "neighbourHealth": "Good",
        }]
    }
    with _patch_inventory(RAW_AOSS), \
         patch("utils.troubleshooting.MonitoringSwitches.get_switch_interfaces", return_value=poe_iface_response):
        await tools["central_bounce_port"](
            ctx, serial_number="SW002", ports=["1/1/1"], bounce_type="poe"
        )
    ctx.elicit.assert_called_once()
    approval_msg = ctx.elicit.call_args.args[0]
    assert "WARNING:" in approval_msg
    assert "PoE power" in approval_msg
    assert "poeStatus=Drawing Watts" in approval_msg
    assert "poeClass=802.3at (PoE+)" in approval_msg
    assert "speed=2.5G" in approval_msg
    assert "connected: CP-DFW-AP07 (Access Point, health=Good)" in approval_msg
    assert "poeDraw" not in approval_msg


@pytest.mark.asyncio
async def test_bounce_port_shows_warning_and_neighbour(tools):
    ctx = make_ctx()
    ctx.elicit = AsyncMock(return_value=DeclinedElicitation())
    iface_response = {
        "items": [{
            "name": "1/1/2", "operStatus": "Up", "speed": 1000,
            "description": "Uplink",
            "neighbour": "SW-CORE-01", "neighbourType": "Switch",
            "neighbourHealth": "Good",
        }]
    }
    with _patch_inventory(RAW_AOSS), \
         patch("utils.troubleshooting.MonitoringSwitches.get_switch_interfaces", return_value=iface_response):
        await tools["central_bounce_port"](
            ctx, serial_number="SW002", ports=["1/1/2"], bounce_type="port"
        )
    ctx.elicit.assert_called_once()
    approval_msg = ctx.elicit.call_args.args[0]
    assert "WARNING:" in approval_msg
    assert "drop the link" in approval_msg
    assert "connected: SW-CORE-01 (Switch, health=Good)" in approval_msg
    assert "speed=1G" in approval_msg
    assert "poeStatus" not in approval_msg
    assert "poeClass" not in approval_msg


@pytest.mark.asyncio
async def test_bounce_port_omits_neighbour_line_when_no_neighbour(tools):
    ctx = make_ctx()
    ctx.elicit = AsyncMock(return_value=DeclinedElicitation())
    iface_response = {
        "items": [{"name": "1/1/3", "operStatus": "Down", "speed": 100, "neighbour": None}]
    }
    with _patch_inventory(RAW_AOSS), \
         patch("utils.troubleshooting.MonitoringSwitches.get_switch_interfaces", return_value=iface_response):
        await tools["central_bounce_port"](
            ctx, serial_number="SW002", ports=["1/1/3"], bounce_type="port"
        )
    ctx.elicit.assert_called_once()
    approval_msg = ctx.elicit.call_args.args[0]
    assert "connected:" not in approval_msg
    assert "speed=100M" in approval_msg


@pytest.mark.parametrize("value,expected", [
    (2500, "2.5G"),
    (1000, "1G"),
    (10000, "10G"),
    (100, "100M"),
    (10, "10M"),
    (None, "unknown"),
    ("foo", "foo"),
    ("Auto", "Auto"),
    ("10000", "10G"),
])
def test_format_port_speed(value, expected):
    from utils.troubleshooting import format_port_speed
    assert format_port_speed(value) == expected


# ---------------------------------------------------------------------------
# central_bounce_port — gateway port approval message
# ---------------------------------------------------------------------------

_GW_IFACE_UP = {
    "name": "GE 0/0/1",
    "operState": "Up",
    "speed": "10000",
    "health": "Good",
    "portType": "Access",
    "duplex": "Full",
    "adminState": "Enabled",
    "vlan": "101,201,3002",
}

_GW_IFACE_DOWN = {
    "name": "GE 0/0/0",
    "operState": "Down",
    "speed": "Auto",
    "health": "Unknown",
    "portType": "Access",
    "duplex": "Auto",
    "adminState": "Enabled",
}


@pytest.mark.asyncio
async def test_gateway_approval_shows_operState_and_health(tools):
    ctx = make_ctx()
    ctx.elicit = AsyncMock(return_value=DeclinedElicitation())
    gw_response = {"ports": [_GW_IFACE_UP]}
    with _patch_inventory(RAW_GW), \
         patch("utils.troubleshooting.MonitoringGateways.get_gateway_interfaces", return_value=gw_response):
        await tools["central_bounce_port"](
            ctx, serial_number="GW001", ports=["GE 0/0/1"], bounce_type="port"
        )
    approval_msg = ctx.elicit.call_args.args[0]
    assert "status=Up" in approval_msg
    assert "health=Good" in approval_msg
    assert "operStatus" not in approval_msg


@pytest.mark.asyncio
async def test_gateway_approval_speed_auto_passes_through(tools):
    ctx = make_ctx()
    ctx.elicit = AsyncMock(return_value=DeclinedElicitation())
    gw_response = {"ports": [_GW_IFACE_DOWN]}
    with _patch_inventory(RAW_GW), \
         patch("utils.troubleshooting.MonitoringGateways.get_gateway_interfaces", return_value=gw_response):
        await tools["central_bounce_port"](
            ctx, serial_number="GW001", ports=["GE 0/0/0"], bounce_type="port"
        )
    approval_msg = ctx.elicit.call_args.args[0]
    assert "speed=Auto" in approval_msg


@pytest.mark.asyncio
async def test_gateway_approval_omits_neighbour_section(tools):
    ctx = make_ctx()
    ctx.elicit = AsyncMock(return_value=DeclinedElicitation())
    gw_response = {"ports": [_GW_IFACE_UP]}
    with _patch_inventory(RAW_GW), \
         patch("utils.troubleshooting.MonitoringGateways.get_gateway_interfaces", return_value=gw_response):
        await tools["central_bounce_port"](
            ctx, serial_number="GW001", ports=["GE 0/0/1"], bounce_type="port"
        )
    approval_msg = ctx.elicit.call_args.args[0]
    assert "connected:" not in approval_msg


@pytest.mark.asyncio
async def test_gateway_approval_omits_poe_fields_for_poe_bounce(tools):
    ctx = make_ctx()
    ctx.elicit = AsyncMock(return_value=DeclinedElicitation())
    gw_response = {"ports": [_GW_IFACE_UP]}
    with _patch_inventory(RAW_GW), \
         patch("utils.troubleshooting.MonitoringGateways.get_gateway_interfaces", return_value=gw_response):
        await tools["central_bounce_port"](
            ctx, serial_number="GW001", ports=["GE 0/0/1"], bounce_type="poe"
        )
    approval_msg = ctx.elicit.call_args.args[0]
    assert "poeStatus" not in approval_msg
    assert "poeClass" not in approval_msg


# ---------------------------------------------------------------------------
# central_bounce_port — elicitation unsupported (McpError)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bounce_port_elicitation_unsupported(tools):
    """ctx.elicit() raising McpError returns a graceful error message."""
    ctx = make_ctx()
    ctx.elicit = AsyncMock(side_effect=McpError(ErrorData(code=-32601, message="Method not found")))
    with _patch_inventory(RAW_CX), \
         patch("utils.troubleshooting.MonitoringSwitches.get_switch_interfaces", return_value=_IFACE_RESPONSE):
        result = await tools["central_bounce_port"](
            ctx, serial_number="SW001", ports=["1/1/1"], bounce_type="port"
        )
    assert isinstance(result, str)
    assert "elicitation" in result.lower()
    assert "Error running port bounce:" in result


# ---------------------------------------------------------------------------
# central_get_port_details
# ---------------------------------------------------------------------------

_CX_IFACE_RESPONSE = {
    "items": [
        {
            "name": "1/1/1",
            "operStatus": "Up",
            "speed": 1000,
            "description": "uplink",
            "neighbour": "CORE-SW",
            "neighbourType": "Switch",
            "neighbourHealth": "Good",
        },
        {
            "name": "1/1/2",
            "operStatus": "Down",
            "speed": 100,
            "description": "",
            "neighbour": None,
        },
    ]
}


# @pytest.mark.asyncio
# async def test_get_port_details_cx(tools):
#     """Happy path for CX switch: returns formatted port details."""
#     ctx = make_ctx()
#     with _patch_inventory(RAW_CX), \
#          patch("utils.troubleshooting.MonitoringSwitches.get_switch_interfaces", return_value=_CX_IFACE_RESPONSE):
#         result = await tools["central_get_port_details"](
#             ctx, serial_number="SW001", ports=["1/1/1"]
#         )
#     assert isinstance(result, str)
#     assert "1/1/1" in result
#     assert "status=Up" in result
#     assert "speed=1G" in result
#     assert "connected: CORE-SW (Switch, health=Good)" in result


# @pytest.mark.asyncio
# async def test_get_port_details_gateway(tools):
#     """Happy path for gateway: returns operState and health fields."""
#     ctx = make_ctx()
#     gw_response = {"ports": [_GW_IFACE_UP]}
#     with _patch_inventory(RAW_GW), \
#          patch("utils.troubleshooting.MonitoringGateways.get_gateway_interfaces", return_value=gw_response):
#         result = await tools["central_get_port_details"](
#             ctx, serial_number="GW001", ports=["GE 0/0/1"]
#         )
#     assert isinstance(result, str)
#     assert "GE 0/0/1" in result
#     assert "status=Up" in result
#     assert "health=Good" in result
#     assert "speed=10G" in result


# @pytest.mark.asyncio
# async def test_get_port_details_unknown_ports(tools):
#     """Unknown ports produce an error listing available ports."""
#     ctx = make_ctx()
#     with _patch_inventory(RAW_CX), \
#          patch("utils.troubleshooting.MonitoringSwitches.get_switch_interfaces", return_value=_CX_IFACE_RESPONSE):
#         result = await tools["central_get_port_details"](
#             ctx, serial_number="SW001", ports=["9/9/9"]
#         )
#     assert result.startswith("Error fetching port details:")
#     assert "9/9/9" in result
#     assert "1/1/1" in result  # available ports listed


# @pytest.mark.asyncio
# async def test_get_port_details_unsupported_family(tools):
#     """Access points are not supported; returns clear error."""
#     ctx = make_ctx()
#     with _patch_inventory(RAW_AP):
#         result = await tools["central_get_port_details"](
#             ctx, serial_number="AP001", ports=["eth0"]
#         )
#     assert result.startswith("Error fetching port details:")


# @pytest.mark.asyncio
# async def test_get_port_details_includes_poe_fields_when_present(tools):
#     """central_get_port_details emits poeStatus/poeClass when the interface reports them."""
#     ctx = make_ctx()
#     poe_iface_response = {
#         "items": [
#             {
#                 "name": "1/1/3",
#                 "operStatus": "Up",
#                 "speed": 2500,
#                 "description": "AP uplink",
#                 "poeStatus": "Drawing Watts",
#                 "poeClass": "802.3at (PoE+)",
#                 "neighbour": None,
#             }
#         ]
#     }
#     with _patch_inventory(RAW_CX), \
#          patch("utils.troubleshooting.MonitoringSwitches.get_switch_interfaces", return_value=poe_iface_response):
#         result = await tools["central_get_port_details"](
#             ctx, serial_number="SW001", ports=["1/1/3"]
#         )
#     assert isinstance(result, str)
#     assert "1/1/3" in result
#     assert "poeStatus=Drawing Watts" in result
#     assert "poeClass=802.3at (PoE+)" in result


# ---------------------------------------------------------------------------
# select_interfaces_for_ports — unit tests for normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("user_port", [
    "0/0/0",        # numeric only
    "GE 0/0/0",    # exact match with space
    "ge 0/0/0",    # lower with space
    "GE0/0/0",     # no space, uppercase prefix
    "ge0/0/0",     # no space, lowercase prefix
    "GE 0/0/0 ",   # trailing whitespace
])
def test_select_interfaces_gateway_port_name_variants(user_port):
    """Gateway iface 'GE 0/0/0' matches all common user-supplied forms."""
    from utils.troubleshooting import select_interfaces_for_ports

    iface = {"name": "GE 0/0/0", "operState": "Up"}
    matched, unknown = select_interfaces_for_ports([iface], [user_port])
    assert matched == [iface], f"Expected match for port {user_port!r}"
    assert unknown == []


def test_select_interfaces_switch_exact_match():
    """Switch iface '1/1/1' matches exact and whitespace-padded forms."""
    from utils.troubleshooting import select_interfaces_for_ports

    iface = {"name": "1/1/1", "operStatus": "Up"}
    for user_port in ("1/1/1", "1/1/1 ", " 1/1/1"):
        matched, unknown = select_interfaces_for_ports([iface], [user_port])
        assert matched == [iface], f"Expected match for port {user_port!r}"
        assert unknown == []


def test_select_interfaces_switch_no_false_positive():
    """Switch iface '1/1/1' does NOT match random unrelated strings."""
    from utils.troubleshooting import select_interfaces_for_ports

    iface = {"name": "1/1/1", "operStatus": "Up"}
    matched, unknown = select_interfaces_for_ports([iface], ["2/2/2"])
    assert matched == []
    assert unknown == ["2/2/2"]


def test_select_interfaces_truly_unknown_port():
    """A port that doesn't match any interface is returned as unknown."""
    from utils.troubleshooting import select_interfaces_for_ports

    ifaces = [
        {"name": "GE 0/0/0", "operState": "Down"},
        {"name": "GE 0/0/1", "operState": "Up"},
    ]
    matched, unknown = select_interfaces_for_ports(ifaces, ["0/0/99"])
    assert matched == []
    assert unknown == ["0/0/99"]


def test_normalize_port_name_edge_case_all_letters():
    """A name consisting entirely of letters returns itself (no empty string)."""
    from utils.troubleshooting import _normalize_port_name

    result = _normalize_port_name("GigabitEthernet")
    assert result == "gigabitethernet"  # all-letters: fall back to lowercased original


# ---------------------------------------------------------------------------
# test_get_port_details_gateway — normalized port name lookup
# ---------------------------------------------------------------------------

# @pytest.mark.asyncio
# async def test_get_port_details_gateway_normalized_port(tools):
#     """central_get_port_details finds a gateway port when user passes '0/0/1' instead of 'GE 0/0/1'."""
#     ctx = make_ctx()
#     gw_response = {"ports": [_GW_IFACE_UP]}  # _GW_IFACE_UP has name "GE 0/0/1"
#     with _patch_inventory(RAW_GW), \
#          patch("utils.troubleshooting.MonitoringGateways.get_gateway_interfaces", return_value=gw_response):
#         result = await tools["central_get_port_details"](
#             ctx, serial_number="GW001", ports=["0/0/1"]
#         )
#     assert isinstance(result, str)
#     assert "GE 0/0/1" in result
#     assert "status=Up" in result
