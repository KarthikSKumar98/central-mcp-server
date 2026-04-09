import ast
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"


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


def test_tools_do_not_use_nested_try_except_blocks():
    violations: list[str] = []

    for path in sorted(TOOLS_DIR.glob("*.py")):
        for line, parent_line in _find_nested_try_blocks(path):
            violations.append(
                f"{path.name}:{line} nested inside try block at line {parent_line}"
            )

    assert not violations, "Nested try/except blocks found in tools:\n" + "\n".join(
        violations
    )
