import importlib

import pytest
from fastmcp.experimental.transforms.code_mode import CodeMode

import config
import server

pytestmark = pytest.mark.integration


def _reload_config_and_server():
    importlib.reload(config)
    return importlib.reload(server)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dynamic_tools", "expect_codemode"),
    [(None, False), ("true", True)],
)
async def test_server_prompt_resolution_with_dynamic_tool_modes(
    monkeypatch, dynamic_tools, expect_codemode
):
    if dynamic_tools is None:
        monkeypatch.delenv("DYNAMIC_TOOLS", raising=False)
    else:
        monkeypatch.setenv("DYNAMIC_TOOLS", dynamic_tools)

    srv = _reload_config_and_server()

    transforms = srv.mcp.transforms
    assert all(transform is not None for transform in transforms)

    has_codemode = any(isinstance(transform, CodeMode) for transform in transforms)
    assert has_codemode is expect_codemode

    prompts = await srv.mcp.list_prompts(run_middleware=False)
    assert prompts is not None
    assert len(prompts) > 0

    resolved_prompt = await srv.mcp.get_prompt(prompts[0].name)
    assert resolved_prompt is not None
