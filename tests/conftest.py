from unittest.mock import MagicMock


class FakeMCP:
    def __init__(self):
        self._tools: dict = {}

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


def make_ctx():
    ctx = MagicMock()
    ctx.lifespan_context = {"conn": MagicMock()}
    return ctx
