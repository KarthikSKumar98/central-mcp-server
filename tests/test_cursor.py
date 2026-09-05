import base64
import json

import pytest

from utils.cursor import decode_cursor, encode_cursor

TOOL = "central_get_clients"
QUERY_HASH = "sha256:" + ("a" * 64)


def _encode_payload(payload: dict[str, object]) -> str:
    raw = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _tamper(cursor: str) -> str:
    replacement = "A" if cursor[-1] != "A" else "B"
    return cursor[:-1] + replacement


@pytest.mark.parametrize(
    ("position", "expected_position"),
    [
        ({"upstream_next": "2"}, {"upstream_next": "2"}),
        ({"upstream_offset": 50}, {"upstream_offset": 50}),
    ],
)
def test_cursor_round_trip_preserves_supported_position_shapes(
    position,
    expected_position,
):
    cursor = encode_cursor(TOOL, 50, position, QUERY_HASH)

    decoded = decode_cursor(
        cursor,
        expected_tool=TOOL,
        expected_query_hash=QUERY_HASH,
    )

    assert decoded.page_size == 50
    assert decoded.position == expected_position
    assert "=" not in cursor


@pytest.mark.parametrize(
    ("cursor", "expected_tool", "expected_query_hash"),
    [
        (
            encode_cursor(TOOL, 50, {"upstream_next": "2"}, QUERY_HASH),
            "central_get_devices",
            QUERY_HASH,
        ),
        (
            encode_cursor(TOOL, 50, {"upstream_next": "2"}, QUERY_HASH),
            TOOL,
            "sha256:" + ("b" * 64),
        ),
        (
            _tamper(
                encode_cursor(TOOL, 50, {"upstream_next": "2"}, QUERY_HASH)
            ),
            TOOL,
            QUERY_HASH,
        ),
        ("not-valid-base64!", TOOL, QUERY_HASH),
        (
            _encode_payload(
                {
                    "v": 2,
                    "tool": TOOL,
                    "page_size": 50,
                    "upstream_next": "2",
                    "query_hash": QUERY_HASH,
                }
            ),
            TOOL,
            QUERY_HASH,
        ),
    ],
    ids=[
        "wrong-tool",
        "wrong-query-hash",
        "tampered",
        "garbage",
        "wrong-version",
    ],
)
def test_decode_cursor_rejects_invalid_or_stale_payloads(
    cursor,
    expected_tool,
    expected_query_hash,
):
    with pytest.raises(ValueError, match="invalid or stale cursor"):
        decode_cursor(
            cursor,
            expected_tool=expected_tool,
            expected_query_hash=expected_query_hash,
        )
