import base64
import binascii
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeAlias

CURSOR_VERSION = 1
INVALID_CURSOR_MESSAGE = "invalid or stale cursor"

CursorPosition: TypeAlias = dict[str, str | int]


@dataclass(frozen=True)
class DecodedCursor:
    """Validated pagination state recovered from a public opaque cursor."""

    page_size: int
    position: CursorPosition


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _validate_query_hash(query_hash: str) -> None:
    prefix = "sha256:"
    digest = query_hash.removeprefix(prefix)
    if (
        not query_hash.startswith(prefix)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("query_hash must be a lowercase sha256 digest")


def _validate_position(position: Mapping[str, object]) -> CursorPosition:
    if set(position) == {"upstream_next"}:
        upstream_next = position["upstream_next"]
        if not isinstance(upstream_next, str) or not upstream_next:
            raise ValueError("upstream_next must be a non-empty string")
        return {"upstream_next": upstream_next}

    if set(position) == {"upstream_offset"}:
        upstream_offset = position["upstream_offset"]
        if (
            isinstance(upstream_offset, bool)
            or not isinstance(upstream_offset, int)
            or upstream_offset < 0
        ):
            raise ValueError("upstream_offset must be a non-negative integer")
        return {"upstream_offset": upstream_offset}

    raise ValueError("cursor must contain exactly one supported position")


def hash_query(filters: Mapping[str, object]) -> str:
    """Hash the canonical non-pagination filter set for cursor query binding."""
    digest = hashlib.sha256(_canonical_json(dict(filters))).hexdigest()
    return f"sha256:{digest}"


def decode_next_page(position: CursorPosition) -> int:
    """Convert an opaque upstream next token only at the SDK call boundary."""
    upstream_next = position.get("upstream_next")
    if not isinstance(upstream_next, str):
        raise ValueError(INVALID_CURSOR_MESSAGE)
    try:
        next_page = int(upstream_next)
    except ValueError:
        raise ValueError(INVALID_CURSOR_MESSAGE) from None
    if next_page < 1:
        raise ValueError(INVALID_CURSOR_MESSAGE)
    return next_page


def encode_cursor(
    tool: str,
    page_size: int,
    position: Mapping[str, object],
    query_hash: str,
) -> str:
    """Encode validated pagination state as unpadded canonical base64url JSON."""
    if not tool:
        raise ValueError("tool must be a non-empty string")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
        raise ValueError("page_size must be a positive integer")
    _validate_query_hash(query_hash)
    validated_position = _validate_position(position)
    payload = {
        "v": CURSOR_VERSION,
        "tool": tool,
        "page_size": page_size,
        **validated_position,
        "query_hash": query_hash,
    }
    return base64.urlsafe_b64encode(_canonical_json(payload)).decode().rstrip("=")


def decode_cursor(
    cursor: str,
    *,
    expected_tool: str,
    expected_query_hash: str,
) -> DecodedCursor:
    """Decode and validate a cursor, rejecting malformed or stale state."""
    try:
        if not cursor or "=" in cursor:
            raise ValueError
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(
            cursor + padding,
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError
        if (
            type(payload.get("v")) is not int
            or payload["v"] != CURSOR_VERSION
            or payload.get("tool") != expected_tool
            or payload.get("query_hash") != expected_query_hash
        ):
            raise ValueError

        page_size = payload.get("page_size")
        if type(page_size) is not int or page_size < 1:
            raise ValueError

        position_keys = {"upstream_next", "upstream_offset"} & payload.keys()
        expected_keys = {
            "v",
            "tool",
            "page_size",
            "query_hash",
            *position_keys,
        }
        if set(payload) != expected_keys:
            raise ValueError
        position = _validate_position({key: payload[key] for key in position_keys})

        canonical_cursor = (
            base64.urlsafe_b64encode(_canonical_json(payload)).decode().rstrip("=")
        )
        if canonical_cursor != cursor:
            raise ValueError
        return DecodedCursor(page_size=page_size, position=position)
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
    ):
        raise ValueError(INVALID_CURSOR_MESSAGE) from None
