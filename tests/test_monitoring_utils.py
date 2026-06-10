"""Tests for utils/monitoring.py — fetch_snapshot and fetch_trends helpers."""

from unittest.mock import MagicMock, patch

import pytest

from utils.monitoring import AP_INCLUDES, AP_TREND_SCOPES, fetch_snapshot, fetch_trends

# ---------------------------------------------------------------------------
# Fixtures / shared data
# ---------------------------------------------------------------------------

SERIAL = "USTWM5206L"

BASE_DETAIL = {
    "serialNumber": SERIAL,
    "deviceName": "AP-1",
    "status": "Up",
    "radios": [{"radioNumber": 0, "band": "5GHz"}],
    "ports": [{"portIndex": 0, "name": "eth0"}],
}

RADIOS_RESPONSE = {
    "count": 1,
    "total": 1,
    "items": [
        {
            "id": "radio-0",
            "radioNumber": 0,
            "band": "5GHz",
            "channelUtilization": 12,
            "noiseFloor": -90,
        }
    ],
}

PORTS_RESPONSE = {
    "count": 1,
    "total": 1,
    "items": [
        {
            "id": "port-0",
            "portIndex": 0,
            "name": "eth0",
            "type": "ethernet",
        }
    ],
}

CPU_TREND_SAMPLES = [
    {"timestamp": "2026-06-01T10:00:00Z", "cpu_utilization": 6},
    {"timestamp": "2026-06-01T10:05:00Z", "cpu_utilization": 8},
]

THROUGHPUT_SAMPLES = [
    {"timestamp": "2026-06-01T10:00:00Z", "tx": 4320, "rx": 4404},
]

RADIO_THROUGHPUT_SAMPLES = [
    {"timestamp": "2026-06-01T10:00:00Z", "tx": 1000, "rx": 1200},
]

WINDOW = ("2026-06-01T09:00:00.000Z", "2026-06-01T10:00:00.000Z")


def _fake_cls(**method_returns: object) -> MagicMock:
    """Build a mock class where each key becomes a MagicMock method."""
    cls = MagicMock()
    for name, rv in method_returns.items():
        getattr(cls, name).return_value = rv
    return cls


# ---------------------------------------------------------------------------
# fetch_snapshot — base only
# ---------------------------------------------------------------------------


def test_fetch_snapshot_base_only_returns_base_dict():
    cls = _fake_cls(get_ap_details=BASE_DETAIL)
    result = fetch_snapshot(conn=MagicMock(), serial_number=SERIAL, monitor_cls=cls)
    cls.get_ap_details.assert_called_once_with(
        central_conn=cls.get_ap_details.call_args.kwargs["central_conn"],
        serial_number=SERIAL,
    )
    cls.get_ap_radios.assert_not_called()
    cls.get_ap_ports.assert_not_called()
    assert result["serialNumber"] == SERIAL


def test_fetch_snapshot_no_includes_does_not_call_dedicated_methods():
    cls = _fake_cls(get_ap_details=BASE_DETAIL)
    fetch_snapshot(conn=MagicMock(), serial_number=SERIAL, includes=None, monitor_cls=cls)
    cls.get_ap_radios.assert_not_called()
    cls.get_ap_ports.assert_not_called()


# ---------------------------------------------------------------------------
# fetch_snapshot — includes=["radios"]
# ---------------------------------------------------------------------------


def test_fetch_snapshot_include_radios_overwrites_embedded_radios():
    cls = _fake_cls(get_ap_details=BASE_DETAIL, get_ap_radios=RADIOS_RESPONSE)
    result = fetch_snapshot(
        conn=MagicMock(),
        serial_number=SERIAL,
        includes=["radios"],
        monitor_cls=cls,
    )
    cls.get_ap_radios.assert_called_once()
    cls.get_ap_ports.assert_not_called()
    # Should be the dedicated items list, not the embedded summary
    assert result["radios"] == RADIOS_RESPONSE["items"]
    assert result["radios"][0]["id"] == "radio-0"


# ---------------------------------------------------------------------------
# fetch_snapshot — includes=["radios", "ports"]
# ---------------------------------------------------------------------------


def test_fetch_snapshot_include_radios_and_ports_both_overwritten():
    cls = _fake_cls(
        get_ap_details=BASE_DETAIL,
        get_ap_radios=RADIOS_RESPONSE,
        get_ap_ports=PORTS_RESPONSE,
    )
    result = fetch_snapshot(
        conn=MagicMock(),
        serial_number=SERIAL,
        includes=["radios", "ports"],
        monitor_cls=cls,
    )
    cls.get_ap_radios.assert_called_once()
    cls.get_ap_ports.assert_called_once()
    assert result["radios"] == RADIOS_RESPONSE["items"]
    assert result["ports"] == PORTS_RESPONSE["items"]
    assert result["ports"][0]["id"] == "port-0"


# ---------------------------------------------------------------------------
# fetch_snapshot — falsy base passthrough
# ---------------------------------------------------------------------------


def test_fetch_snapshot_falsy_base_returns_without_calling_dedicated_methods():
    cls = _fake_cls(get_ap_details=None)
    result = fetch_snapshot(conn=MagicMock(), serial_number=SERIAL, includes=["radios"], monitor_cls=cls)
    cls.get_ap_radios.assert_not_called()
    assert result is None


# ---------------------------------------------------------------------------
# fetch_trends — scope="ap" metric="cpu-utilization" (no interface_type)
# ---------------------------------------------------------------------------


def test_fetch_trends_ap_cpu_calls_get_ap_trends_without_interface_type():
    cls = _fake_cls(get_ap_trends=CPU_TREND_SAMPLES)
    result = fetch_trends(
        conn=MagicMock(),
        serial_number=SERIAL,
        scope="ap",
        metric="cpu-utilization",
        window=WINDOW,
        monitor_cls=cls,
    )
    cls.get_ap_trends.assert_called_once()
    call_kwargs = cls.get_ap_trends.call_args.kwargs
    assert call_kwargs["metric"] == "cpu-utilization"
    assert call_kwargs["start_time"] == WINDOW[0]
    assert call_kwargs["end_time"] == WINDOW[1]
    assert "interface_type" not in call_kwargs
    assert result == CPU_TREND_SAMPLES


# ---------------------------------------------------------------------------
# fetch_trends — scope="ap" metric="throughput" (interface_type passed)
# ---------------------------------------------------------------------------


def test_fetch_trends_ap_throughput_passes_interface_type():
    cls = _fake_cls(get_ap_trends=THROUGHPUT_SAMPLES)
    fetch_trends(
        conn=MagicMock(),
        serial_number=SERIAL,
        scope="ap",
        metric="throughput",
        window=WINDOW,
        interface_type="WIRED",
        monitor_cls=cls,
    )
    call_kwargs = cls.get_ap_trends.call_args.kwargs
    assert call_kwargs["interface_type"] == "WIRED"


def test_fetch_trends_ap_throughput_default_interface_type_is_wireless():
    cls = _fake_cls(get_ap_trends=THROUGHPUT_SAMPLES)
    fetch_trends(
        conn=MagicMock(),
        serial_number=SERIAL,
        scope="ap",
        metric="throughput",
        window=WINDOW,
        monitor_cls=cls,
    )
    call_kwargs = cls.get_ap_trends.call_args.kwargs
    assert call_kwargs["interface_type"] == "WIRELESS"


# ---------------------------------------------------------------------------
# fetch_trends — scope="radio" with radio_number
# ---------------------------------------------------------------------------


def test_fetch_trends_radio_scope_calls_get_ap_radio_trends():
    cls = _fake_cls(get_ap_radio_trends=RADIO_THROUGHPUT_SAMPLES)
    result = fetch_trends(
        conn=MagicMock(),
        serial_number=SERIAL,
        scope="radio",
        metric="throughput",
        window=WINDOW,
        radio_number=0,
        monitor_cls=cls,
    )
    cls.get_ap_radio_trends.assert_called_once()
    call_kwargs = cls.get_ap_radio_trends.call_args.kwargs
    assert call_kwargs["radio_number"] == 0
    assert call_kwargs["metric"] == "throughput"
    assert result == RADIO_THROUGHPUT_SAMPLES


# ---------------------------------------------------------------------------
# fetch_trends — scope="radio" without radio_number → ValueError
# ---------------------------------------------------------------------------


def test_fetch_trends_radio_scope_without_radio_number_raises():
    cls = _fake_cls(get_ap_radio_trends=[])
    with pytest.raises(ValueError, match="radio_number"):
        fetch_trends(
            conn=MagicMock(),
            serial_number=SERIAL,
            scope="radio",
            metric="throughput",
            window=WINDOW,
            monitor_cls=cls,
        )


# ---------------------------------------------------------------------------
# fetch_trends — scope="port" without port_index → ValueError
# ---------------------------------------------------------------------------


def test_fetch_trends_port_scope_without_port_index_raises():
    cls = _fake_cls(get_ap_port_trends=[])
    with pytest.raises(ValueError, match="port_index"):
        fetch_trends(
            conn=MagicMock(),
            serial_number=SERIAL,
            scope="port",
            metric="throughput",
            window=WINDOW,
            monitor_cls=cls,
        )


# ---------------------------------------------------------------------------
# fetch_trends — invalid metric for scope → ValueError with valid metric name
# ---------------------------------------------------------------------------


def test_fetch_trends_invalid_metric_for_radio_scope_raises_with_valid_metric_in_message():
    cls = _fake_cls(get_ap_radio_trends=[])
    with pytest.raises(ValueError) as exc_info:
        fetch_trends(
            conn=MagicMock(),
            serial_number=SERIAL,
            scope="radio",
            metric="power-consumption",  # ap-only metric
            window=WINDOW,
            radio_number=0,
            monitor_cls=cls,
        )
    assert "channel-utilization" in str(exc_info.value)


def test_fetch_trends_invalid_metric_for_port_scope_raises_with_valid_metric_in_message():
    cls = _fake_cls(get_ap_port_trends=[])
    with pytest.raises(ValueError) as exc_info:
        fetch_trends(
            conn=MagicMock(),
            serial_number=SERIAL,
            scope="port",
            metric="cpu-utilization",  # ap-only metric
            window=WINDOW,
            port_index=0,
            monitor_cls=cls,
        )
    assert "crc" in str(exc_info.value)


# ---------------------------------------------------------------------------
# fetch_trends — invalid scope → ValueError
# ---------------------------------------------------------------------------


def test_fetch_trends_invalid_scope_raises():
    with pytest.raises(ValueError, match="Invalid scope"):
        fetch_trends(
            conn=MagicMock(),
            serial_number=SERIAL,
            scope="switch",
            metric="throughput",
            window=WINDOW,
        )


# ---------------------------------------------------------------------------
# fetch_trends — generic paths (multi-metric scopes, sub_id, epoch window)
# ---------------------------------------------------------------------------

MULTI_METRIC_SCOPES = {
    "hardware": ("get_switch_hardware_trends", None, None),
    "interface": ("get_switch_interface_trends", None, None),
}

GENERIC_SUB_ID_SCOPES = {
    "tunnel": ("get_gateway_tunnel_trends", ("throughput", "status"), "tunnel_name"),
}

HARDWARE_SAMPLES = [
    {"timestamp": "2026-06-01T10:00:00Z", "cpu_utilization": 4, "memory_utilization": 31},
]


def test_fetch_trends_multi_metric_scope_omits_metric_kwarg():
    cls = _fake_cls(get_switch_hardware_trends=HARDWARE_SAMPLES)
    result = fetch_trends(
        conn=MagicMock(),
        serial_number=SERIAL,
        scope="hardware",
        metric=None,
        window=WINDOW,
        monitor_cls=cls,
        scopes=MULTI_METRIC_SCOPES,
    )
    call_kwargs = cls.get_switch_hardware_trends.call_args.kwargs
    assert "metric" not in call_kwargs
    assert result == HARDWARE_SAMPLES


def test_fetch_trends_multi_metric_scope_rejects_explicit_metric():
    cls = _fake_cls(get_switch_hardware_trends=[])
    with pytest.raises(ValueError, match="does not take a metric"):
        fetch_trends(
            conn=MagicMock(),
            serial_number=SERIAL,
            scope="hardware",
            metric="cpu-utilization",
            window=WINDOW,
            monitor_cls=cls,
            scopes=MULTI_METRIC_SCOPES,
        )


def test_fetch_trends_generic_sub_id_passed_under_required_kwarg_name():
    cls = _fake_cls(get_gateway_tunnel_trends=[])
    fetch_trends(
        conn=MagicMock(),
        serial_number=SERIAL,
        scope="tunnel",
        metric="throughput",
        window=WINDOW,
        sub_id="tunnel-1",
        monitor_cls=cls,
        scopes=GENERIC_SUB_ID_SCOPES,
    )
    call_kwargs = cls.get_gateway_tunnel_trends.call_args.kwargs
    assert call_kwargs["tunnel_name"] == "tunnel-1"


def test_fetch_trends_generic_required_kwarg_missing_raises():
    cls = _fake_cls(get_gateway_tunnel_trends=[])
    with pytest.raises(ValueError, match="tunnel_name"):
        fetch_trends(
            conn=MagicMock(),
            serial_number=SERIAL,
            scope="tunnel",
            metric="throughput",
            window=WINDOW,
            monitor_cls=cls,
            scopes=GENERIC_SUB_ID_SCOPES,
        )


def test_fetch_trends_epoch_window_converts_rfc3339_to_epoch_seconds():
    cls = _fake_cls(get_switch_hardware_trends=[])
    fetch_trends(
        conn=MagicMock(),
        serial_number=SERIAL,
        scope="hardware",
        metric=None,
        window=WINDOW,
        epoch_window=True,
        monitor_cls=cls,
        scopes=MULTI_METRIC_SCOPES,
    )
    call_kwargs = cls.get_switch_hardware_trends.call_args.kwargs
    # 2026-06-01T09:00:00Z / 10:00:00Z UTC as epoch seconds
    assert call_kwargs["start_time"] == 1780304400
    assert call_kwargs["end_time"] == 1780308000
    assert isinstance(call_kwargs["start_time"], int)


def test_fetch_trends_extra_params_forwarded_and_none_values_dropped():
    cls = _fake_cls(get_switch_interface_trends=[])
    fetch_trends(
        conn=MagicMock(),
        serial_number=SERIAL,
        scope="interface",
        metric=None,
        window=WINDOW,
        extra_params={"interface_id": "1/1/1", "uplink": None},
        monitor_cls=cls,
        scopes=MULTI_METRIC_SCOPES,
    )
    call_kwargs = cls.get_switch_interface_trends.call_args.kwargs
    assert call_kwargs["interface_id"] == "1/1/1"
    assert "uplink" not in call_kwargs


# ---------------------------------------------------------------------------
# Lazy-resolution proof — patch on the real class is picked up at call time
# ---------------------------------------------------------------------------


def test_fetch_trends_lazy_resolution_patch_on_real_class_is_used():
    """Prove method name strings are resolved via getattr at call time.

    Patching ``utils.monitoring.MonitoringAPs.get_ap_trends`` replaces the
    attribute on the class object.  Because ``fetch_trends`` resolves the name
    with ``getattr(monitor_cls, method_name)`` at call time (not at import
    time), the patch is always picked up — this is the key correctness property.
    """
    with patch(
        "utils.monitoring.MonitoringAPs.get_ap_trends",
        return_value=CPU_TREND_SAMPLES,
    ) as mock_method:
        result = fetch_trends(
            conn=MagicMock(),
            serial_number=SERIAL,
            scope="ap",
            metric="cpu-utilization",
            window=WINDOW,
            # no monitor_cls override — uses real MonitoringAPs
        )
    mock_method.assert_called_once()
    assert result == CPU_TREND_SAMPLES
