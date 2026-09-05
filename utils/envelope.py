import re
from typing import Any, Literal, NoReturn, TypeVar

from fastmcp.exceptions import ToolError

from constants import MAX_RESPONSE_ITEMS
from models import CentralEnvelope, CentralError, EnvelopeMeta

EnvelopeT = TypeVar("EnvelopeT", bound=CentralEnvelope)


def build_envelope(
    envelope_cls: type[EnvelopeT],
    items: list[Any],
    *,
    next_cursor: str | None = None,
    total: int | None = None,
    total_available: int | None = None,
    ceiling: int = MAX_RESPONSE_ITEMS,
    response_format: Literal["concise", "detailed"] = "concise",
) -> EnvelopeT:
    """Wrap items in a typed Central envelope with shared limit accounting."""
    if ceiling < 0:
        raise ValueError("ceiling must be non-negative")

    available = len(items)
    returned_items = items[:ceiling]
    return envelope_cls(
        items=returned_items,
        next_cursor=next_cursor,
        truncated=available > ceiling,
        total=total,
        meta=EnvelopeMeta(
            returned=len(returned_items),
            total_available=(available if total_available is None else total_available),
            response_format=response_format,
        ),
    )


def to_central_error(
    exc: Exception,
    *,
    operation: str | None = None,
) -> CentralError:
    """Map an exception to the shared Central tool error contract."""
    detail = str(exc) or exc.__class__.__name__
    message = f"{operation} failed: {detail}" if operation else detail

    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code == 429:
        return CentralError(
            code="rate_limited",
            message=message,
            retryable=True,
            suggestion=(
                "Respect Retry-After when present, then retry with exponential backoff."
            ),
        )
    if status_code == 408:
        return CentralError(
            code="upstream_timeout",
            message=message,
            retryable=True,
            suggestion="Retry after a short backoff; reduce request scope if timeouts persist.",
        )
    if isinstance(status_code, int) and 500 <= status_code < 600:
        return CentralError(
            code="upstream_server_error",
            message=message,
            retryable=True,
            suggestion="Retry after the upstream Central service recovers.",
        )
    if isinstance(status_code, int) and 400 <= status_code < 500:
        return CentralError(
            code="upstream_request_error",
            message=message,
            retryable=False,
            suggestion="Correct the request or credentials before retrying.",
        )

    if isinstance(exc, TimeoutError):
        return CentralError(
            code="timeout",
            message=message,
            retryable=True,
            suggestion="Retry the operation after a short delay.",
        )

    if isinstance(exc, ConnectionError):
        return CentralError(
            code="connection_error",
            message=message,
            retryable=True,
            suggestion="Retry after checking connectivity to the Central API.",
        )

    if isinstance(exc, ValueError):
        return CentralError(
            code="validation_error",
            message=message,
            retryable=False,
            suggestion="Correct the request parameters before retrying.",
        )

    exception_name = exc.__class__.__name__.lower()
    normalized_detail = detail.lower()
    if "timeout" in exception_name or "timed out" in normalized_detail:
        return CentralError(
            code="timeout",
            message=message,
            retryable=True,
            suggestion="Retry the operation after a short delay.",
        )
    if any(
        marker in f"{exception_name} {normalized_detail}"
        for marker in ("connection", "connect", "network", "socket", "dns")
    ):
        return CentralError(
            code="connection_error",
            message=message,
            retryable=True,
            suggestion="Retry after checking connectivity to the Central API.",
        )

    status_match = re.search(r"\b([45]\d{2})\b", detail)
    if status_match and status_match.group(1) == "429":
        return CentralError(
            code="rate_limited",
            message=message,
            retryable=True,
            suggestion=(
                "Respect Retry-After when present, then retry with exponential backoff."
            ),
        )
    if status_match and status_match.group(1) == "408":
        return CentralError(
            code="upstream_timeout",
            message=message,
            retryable=True,
            suggestion="Retry after a short backoff; reduce request scope if timeouts persist.",
        )
    if status_match and status_match.group(1).startswith("5"):
        return CentralError(
            code="upstream_server_error",
            message=message,
            retryable=True,
            suggestion="Retry after the upstream Central service recovers.",
        )
    if status_match:
        return CentralError(
            code="upstream_request_error",
            message=message,
            retryable=False,
            suggestion="Correct the request or credentials before retrying.",
        )

    return CentralError(
        code="unexpected_error",
        message=message,
        retryable=False,
        suggestion="Check the request and try again.",
    )


def raise_central_error(
    exc: Exception,
    operation: str | None = None,
) -> NoReturn:
    """Raise FastMCP 3.1.1's error escape hatch with CentralError JSON.

    The exact FastMCP API is ``raise fastmcp.exceptions.ToolError(message)``.
    FastMCP's MCP handler catches ``ToolError`` and emits a
    ``CallToolResult(isError=True)`` whose text content is ``str(error)``.
    Version 3.1.1 has no structured-content argument on ``ToolError``, so this
    helper passes ``CentralError.model_dump_json()`` as that message payload.
    """
    error = to_central_error(exc, operation=operation)
    raise ToolError(error.model_dump_json()) from exc
