#!/usr/bin/env python3
"""Statically estimate registered-tool prompt cost without importing the server.

The script finds functions decorated with ``@mcp.tool`` in ``tools/*.py``.  It
counts each function docstring as its tool description and renders its public
parameters as a compact JSON-Schema-like text.  Tokens are approximated as
characters divided by four; this is deliberately deterministic and suitable
for comparing tools, rather than a tokenizer-accurate bill estimate.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"


@dataclass(frozen=True)
class ToolCost:
    name: str
    description_chars: int
    schema_chars: int

    @property
    def description_tokens(self) -> int:
        """Return the approximate description token count."""
        return round(self.description_chars / 4)

    @property
    def schema_tokens(self) -> int:
        """Return the approximate schema token count."""
        return round(self.schema_chars / 4)

    @property
    def total_tokens(self) -> int:
        """Return the combined approximate token count."""
        return self.description_tokens + self.schema_tokens


def is_tool(function: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    """Return whether a function has an ``@mcp.tool`` decorator."""
    for decorator in function.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr == "tool":
            return isinstance(target.value, ast.Name) and target.value.id == "mcp"
    return False


def render_input_schema(function: ast.AsyncFunctionDef | ast.FunctionDef) -> str:
    """Render public arguments in a stable, schema-like representation."""
    args = function.args
    positional = [*args.posonlyargs, *args.args]
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    properties: list[str] = []
    required: list[str] = []

    for argument, default in zip(positional, defaults, strict=True):
        if argument.arg == "ctx":
            continue
        annotation = ast.unparse(argument.annotation) if argument.annotation else "Any"
        entry = f'"{argument.arg}":{{"annotation":"{annotation}"'
        if default is None:
            required.append(argument.arg)
        else:
            entry += f',"default":"{ast.unparse(default)}"'
        properties.append(entry + "}")

    return (
        "{"
        + f'"type":"object","properties":{{{",".join(properties)}}},'
        + (f'"required":{required}' if required else '"required":[]')
        + "}"
    )


def measure() -> list[ToolCost]:
    """Return costs for every registered tool in lexical filename/name order."""
    costs: list[ToolCost] = []
    for path in sorted(TOOLS.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and is_tool(
                node
            ):
                description = ast.get_docstring(node, clean=True) or ""
                schema = render_input_schema(node)
                costs.append(ToolCost(node.name, len(description), len(schema)))
    return sorted(costs, key=lambda cost: cost.name)


def main() -> None:
    """Print a Markdown table and totals for inclusion in the research note."""
    costs = measure()
    print(
        "| Tool | Description chars / tokens | Schema chars / tokens | Total tokens |"
    )
    print("|---|---:|---:|---:|")
    for cost in costs:
        print(
            f"| `{cost.name}` | {cost.description_chars} / {cost.description_tokens} "
            f"| {cost.schema_chars} / {cost.schema_tokens} | {cost.total_tokens} |"
        )
    description_chars = sum(cost.description_chars for cost in costs)
    schema_chars = sum(cost.schema_chars for cost in costs)
    description_tokens = sum(cost.description_tokens for cost in costs)
    schema_tokens = sum(cost.schema_tokens for cost in costs)
    print(
        f"| **Total ({len(costs)} tools)** | **{description_chars:,} / {description_tokens:,}** "
        f"| **{schema_chars:,} / {schema_tokens:,}** | **{description_tokens + schema_tokens:,}** |"
    )


if __name__ == "__main__":
    main()
