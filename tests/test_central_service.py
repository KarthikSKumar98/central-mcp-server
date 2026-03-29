from unittest.mock import MagicMock

import pytest

from services.central_service import verify_connection


def test_verify_connection_success():
    conn = MagicMock()
    verify_connection(conn)  # should not raise


def test_verify_connection_failure_http_error():
    conn = MagicMock()
    conn.command.side_effect = Exception("Client error from central: {'code': 401}")
    with pytest.raises(RuntimeError) as exc_info:
        verify_connection(conn)
    assert "Central API connectivity check failed" in str(exc_info.value)
    assert ".env" in str(exc_info.value)


def test_verify_connection_transport_error():
    conn = MagicMock()
    conn.command.side_effect = Exception("Failed after 5 attempts")
    with pytest.raises(RuntimeError) as exc_info:
        verify_connection(conn)
    assert "Central API connectivity check failed" in str(exc_info.value)
