import ast
from pathlib import Path
from typing import get_args

from models import CentralError


ERROR_CODES = {
    "rate_limited",
    "upstream_timeout",
    "upstream_server_error",
    "upstream_request_error",
    "timeout",
    "connection_error",
    "validation_error",
    "unexpected_error",
}


def test_central_error_code_literal_is_locked() -> None:
    annotation = CentralError.model_fields["code"].annotation
    assert set(get_args(annotation)) == ERROR_CODES
    assert len(get_args(annotation)) == 8


def test_every_emitted_error_code_is_in_locked_taxonomy() -> None:
    root = Path(__file__).resolve().parents[1]
    emitted: set[str] = set()
    for directory in (root / "utils", root / "tools"):
        for path in directory.glob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
                for keyword in call.keywords:
                    if keyword.arg == "code" and isinstance(keyword.value, ast.Constant):
                        emitted.add(keyword.value.value)
    assert emitted
    assert emitted <= ERROR_CODES
