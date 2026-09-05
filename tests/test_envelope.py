import json
from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError

from models import CentralEnvelope
from utils.envelope import build_envelope, raise_central_error, to_central_error


class StringEnvelope(CentralEnvelope):
    items: list[str]


class FakeHttpError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"HTTP {status_code}")
        self.response = SimpleNamespace(status_code=status_code)


class FakeTransportTimeoutError(Exception):
    pass


class FakeConnectError(Exception):
    pass


def test_build_envelope_preserves_empty_items():
    envelope = build_envelope(StringEnvelope, [])

    assert envelope.items == []
    assert envelope.meta.returned == 0


def test_build_envelope_truncates_items_and_records_accounting():
    envelope = build_envelope(StringEnvelope, ["a", "b", "c"], ceiling=2)

    assert envelope.items == ["a", "b"]
    assert envelope.truncated is True
    assert envelope.meta.returned == 2
    assert envelope.meta.total_available == 3


def test_build_envelope_passes_through_pagination_fields():
    envelope = build_envelope(
        StringEnvelope,
        ["a"],
        next_cursor="cursor-2",
        total=12,
    )

    assert envelope.next_cursor == "cursor-2"
    assert envelope.total == 12
    assert envelope.meta.returned == 1


def test_build_envelope_accepts_authoritative_total_available():
    envelope = build_envelope(
        StringEnvelope,
        ["page-item"],
        total=125,
        total_available=125,
    )

    assert envelope.total == 125
    assert envelope.meta.total_available == 125


def test_to_central_error_marks_connection_failures_retryable():
    error = to_central_error(
        ConnectionError("connection refused"), operation="fetch devices"
    )

    assert error.code == "connection_error"
    assert error.message == "fetch devices failed: connection refused"
    assert error.retryable is True
    assert error.suggestion


def test_to_central_error_marks_value_errors_non_retryable():
    error = to_central_error(ValueError("limit must be positive"))

    assert error.code == "validation_error"
    assert error.message == "limit must be positive"
    assert error.retryable is False
    assert error.suggestion


def test_to_central_error_marks_timeouts_retryable():
    error = to_central_error(TimeoutError("request timed out"))

    assert error.code == "timeout"
    assert error.retryable is True


def test_to_central_error_classifies_http_status_family():
    server_error = to_central_error(FakeHttpError(503))
    client_error = to_central_error(FakeHttpError(404))

    assert server_error.code == "upstream_server_error"
    assert server_error.retryable is True
    assert client_error.code == "upstream_request_error"
    assert client_error.retryable is False


@pytest.mark.parametrize("status_code", [408, 429])
def test_to_central_error_marks_retryable_http_client_statuses(status_code):
    error = to_central_error(FakeHttpError(status_code))

    assert error.retryable is True
    assert "retry" in error.suggestion.lower()
    assert "backoff" in error.suggestion.lower()


def test_to_central_error_classifies_status_codes_in_plain_error_messages():
    server_error = to_central_error(Exception("API error 503: unavailable"))
    client_error = to_central_error(Exception("API error 400: invalid filter"))

    assert server_error.code == "upstream_server_error"
    assert server_error.retryable is True
    assert client_error.code == "upstream_request_error"
    assert client_error.retryable is False


def test_to_central_error_classifies_network_library_exception_names():
    timeout = to_central_error(FakeTransportTimeoutError("read failed"))
    connection = to_central_error(FakeConnectError("socket failed"))

    assert timeout.code == "timeout"
    assert timeout.retryable is True
    assert connection.code == "connection_error"
    assert connection.retryable is True


def test_raise_central_error_raises_tool_error_with_structured_payload():
    source_error = TimeoutError("request timed out")

    with pytest.raises(ToolError) as exc_info:
        raise_central_error(source_error, "fetch sites")

    assert type(exc_info.value) is ToolError
    assert json.loads(str(exc_info.value)) == {
        "code": "timeout",
        "message": "fetch sites failed: request timed out",
        "retryable": True,
        "suggestion": "Retry the operation after a short delay.",
    }
