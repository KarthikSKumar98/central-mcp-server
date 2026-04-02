import importlib

import config


def _reload_config():
    return importlib.reload(config)


def test_dynamic_tools_true_enabled(monkeypatch):
    monkeypatch.setenv("DYNAMIC_TOOLS", "true")
    cfg = _reload_config()
    assert cfg.DYNAMIC_TOOLS is True


def test_dynamic_tools_true_case_insensitive(monkeypatch):
    monkeypatch.setenv("DYNAMIC_TOOLS", "TRUE")
    cfg = _reload_config()
    assert cfg.DYNAMIC_TOOLS is True


def test_dynamic_tools_false_when_unset(monkeypatch):
    monkeypatch.delenv("DYNAMIC_TOOLS", raising=False)
    cfg = _reload_config()
    assert cfg.DYNAMIC_TOOLS is False


def test_dynamic_tools_false_for_yes_and_one(monkeypatch):
    monkeypatch.setenv("DYNAMIC_TOOLS", "yes")
    cfg = _reload_config()
    assert cfg.DYNAMIC_TOOLS is False

    monkeypatch.setenv("DYNAMIC_TOOLS", "1")
    cfg = _reload_config()
    assert cfg.DYNAMIC_TOOLS is False


def test_dynamic_tools_false_when_only_dynamic_tool_set(monkeypatch):
    monkeypatch.delenv("DYNAMIC_TOOLS", raising=False)
    monkeypatch.setenv("DYNAMIC_TOOL", "true")
    cfg = _reload_config()
    assert cfg.DYNAMIC_TOOLS is False
