import asyncio
from unittest.mock import MagicMock

import pytest

from constants import API_CONCURRENCY_LIMIT


@pytest.fixture(autouse=True)
def run_mocked_thread_calls_inline(monkeypatch: pytest.MonkeyPatch):
    """Avoid executor teardown delays for unit tests whose blocking APIs are mocks."""

    async def inline(func, /, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", inline)


class FakeMCP:
    def __init__(self):
        self._tools: dict = {}
        self._prompts: dict = {}

    def tool(self, fn=None, **kwargs):
        if fn is not None:
            # called as @mcp.tool directly
            self._tools[fn.__name__] = fn
            return fn

        # called as @mcp.tool(annotations=...) — return a decorator
        def decorator(func):
            self._tools[func.__name__] = func
            return func

        return decorator

    def prompt(self, fn=None, **kwargs):
        if fn is not None:
            # called as @mcp.prompt directly
            self._prompts[fn.__name__] = fn
            return fn

        # called as @mcp.prompt(...) — return a decorator
        def decorator(func):
            self._prompts[func.__name__] = func
            return func

        return decorator


def make_ctx():
    ctx = MagicMock()
    ctx.lifespan_context = {
        "conn": MagicMock(),
        "api_semaphore": asyncio.Semaphore(API_CONCURRENCY_LIMIT),
    }
    return ctx


def annotated_field(annotation):
    """Return the FieldInfo of an Annotated hint.

    Python 3.10's get_type_hints wraps None-default parameters in Optional;
    3.11+ does not. Unwrap so tests pass on both.
    """
    import typing

    if typing.get_origin(annotation) is typing.Union:
        annotation = next(
            a
            for a in typing.get_args(annotation)
            if typing.get_origin(a) is typing.Annotated
        )
    return annotation.__metadata__[0]
