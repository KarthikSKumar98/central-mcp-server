from unittest.mock import MagicMock, patch

import pytest

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

RAW_CX = {**RAW_AP, "serialNumber": "SW001", "deviceType": "SWITCH", "model": "CX 6300M", "deviceName": "cx-01"}
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
         patch("utils.troubleshooting.Troubleshooting.get_ping_test_result", return_value={"status": "COMPLETED", "result": {"output": "ping OK"}}), \
         patch("asyncio.sleep"):
        result = await tools["central_run_network_test"](
            ctx, test_type="ping", serial_number="AP001", destination="8.8.8.8", max_attempts=1, poll_interval=1
        )
    assert isinstance(result, TroubleshootingResult)
    assert result.status == "COMPLETED"
    assert result.device_type == "aps"
    mock_init.assert_called_once()
    assert mock_init.call_args.kwargs["destination"] == "8.8.8.8"


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
         patch("utils.troubleshooting.Troubleshooting.initiate_traceroute_aps_test", return_value={"location": "/tasks/T001"}), \
         patch("utils.troubleshooting.Troubleshooting.get_traceroute_test_result", return_value={"status": "COMPLETED", "result": {}}), \
         patch("asyncio.sleep"):
        result = await tools["central_run_network_test"](
            ctx, test_type="traceroute", serial_number="AP001", destination="8.8.8.8",
            max_attempts=1, poll_interval=1
        )
    assert isinstance(result, TroubleshootingResult)
    assert result.status == "COMPLETED"


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
        ctx, serial_number="AP001", commands=[f"show vlan {i}" for i in range(21)]
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
