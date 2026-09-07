import ast
import asyncio
import importlib
from pathlib import Path

import pytest

import config
import server

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"

SURVIVING_TOOLS = {
    "central_get_devices",
    "central_get_device_details",
    "central_get_device_trends",
    "central_get_clients",
    "central_get_client_analytics",
    "central_get_sites",
    "central_get_wlans",
    "central_get_gateway_cluster",
    "central_get_events",
    "central_get_alerts",
    "central_run_network_test",
    "central_run_show_commands",
    "central_bounce_port",
}

REMOVED_TOOLS = {
    "central_get_aps",
    "central_get_switches",
    "central_get_gateways",
    "central_find_device",
    "central_get_switch_details",
    "central_get_gateway_details",
    "central_get_switch_trends",
    "central_get_gateway_trends",
    "central_find_client",
    "central_get_summary",
    "central_get_wlan_stats",
    "central_get_cluster_capacity_trends",
    "central_get_events_count",
}

REMOVED_TOOL_REFERENCE_FILES = (
    Path(__file__).resolve().parents[1] / "prompts.py",
    Path(__file__).resolve().parents[1] / "server.py",
    Path(__file__).resolve().parents[1] / "INSTRUCTIONS.md",
)


def _find_nested_try_blocks(path: Path) -> list[tuple[int, int]]:
    tree = ast.parse(path.read_text())
    parents: dict[ast.AST, ast.AST] = {}

    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    nested_blocks: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue

        parent = parents.get(node)
        while parent is not None:
            if isinstance(parent, ast.Try):
                nested_blocks.append((node.lineno, parent.lineno))
                break
            parent = parents.get(parent)

    return nested_blocks


def test_tools_do_not_use_nested_try_except_blocks() -> None:
    """Tools keep one flat exception boundary per operation."""
    violations: list[str] = []

    for path in sorted(TOOLS_DIR.glob("*.py")):
        for line, parent_line in _find_nested_try_blocks(path):
            violations.append(
                f"{path.name}:{line} nested inside try block at line {parent_line}"
            )

    assert not violations, "Nested try/except blocks found in tools:\n" + "\n".join(
        violations
    )


def test_server_registers_exact_folded_tool_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 0.2.0 server exposes exactly the 13 folded tools, with no aliases."""
    monkeypatch.setenv("DYNAMIC_TOOLS", "false")
    importlib.reload(config)
    static_server = importlib.reload(server)
    registered = {
        tool.name
        for tool in asyncio.run(static_server.mcp.list_tools(run_middleware=False))
    }

    assert registered == SURVIVING_TOOLS
    assert registered.isdisjoint(REMOVED_TOOLS)


def test_removed_tools_are_not_referenced_by_server_guidance() -> None:
    """Server guidance names only tools from the folded surface."""
    violations: list[str] = []

    for path in REMOVED_TOOL_REFERENCE_FILES:
        content = path.read_text()
        for tool_name in sorted(REMOVED_TOOLS):
            if tool_name in content:
                violations.append(f"{path.name}: {tool_name}")

    assert not violations, "Removed tool references found:\n" + "\n".join(violations)
