import importlib

import pytest
from fastmcp.experimental.transforms.code_mode import CodeMode

import config
import server


def _reload_config_and_server():
    importlib.reload(config)
    return importlib.reload(server)


def test_server_transforms_excludes_none_when_dynamic_tools_disabled(monkeypatch):
    monkeypatch.delenv("DYNAMIC_TOOLS", raising=False)
    srv = _reload_config_and_server()

    assert all(transform is not None for transform in srv.mcp.transforms)


@pytest.mark.asyncio
async def test_server_list_prompts_works_when_dynamic_tools_disabled(monkeypatch):
    monkeypatch.delenv("DYNAMIC_TOOLS", raising=False)
    srv = _reload_config_and_server()

    prompts = await srv.mcp.list_prompts(run_middleware=False)
    assert prompts is not None
    assert len(prompts) > 0


def test_server_transforms_include_codemode_when_dynamic_tools_enabled(monkeypatch):
    monkeypatch.setenv("DYNAMIC_TOOLS", "true")
    srv = _reload_config_and_server()

    assert len(srv.mcp.transforms) == 1
    assert isinstance(srv.mcp.transforms[0], CodeMode)


@pytest.mark.asyncio
async def test_server_list_prompts_works_when_dynamic_tools_enabled(monkeypatch):
    monkeypatch.setenv("DYNAMIC_TOOLS", "true")
    srv = _reload_config_and_server()

    prompts = await srv.mcp.list_prompts(run_middleware=False)
    assert prompts is not None
    assert len(prompts) > 0
