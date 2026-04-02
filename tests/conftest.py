import asyncio
from unittest.mock import MagicMock

from constants import API_CONCURRENCY_LIMIT


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
