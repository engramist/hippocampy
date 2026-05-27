"""Boundary checks for direct Kuzu imports.

Kuzu must stay isolated to the graph storage facade so every other production
module depends on the abstraction instead of the database package directly.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOTS = ("campy", "mcp_engine")
IGNORED_DIR_NAMES = {
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".venv",
    "venv",
    "env",
    "tests",
}
ALLOWED_KUZU_IMPORT_FILES = {
    "mcp_engine/graph/kuzu_client.py",
    "campy/brain/hippocampus/graph/kuzu_client.py",
}


def _production_python_files() -> list[Path]:
    files: list[Path] = []
    for root_name in PRODUCTION_ROOTS:
        root = REPO_ROOT / root_name
        if not root.exists():
            continue

        for path in root.rglob("*.py"):
            if any(part.startswith(".") or part in IGNORED_DIR_NAMES for part in path.parts):
                continue
            files.append(path)

    return sorted(files)


def _is_allowed_kuzu_facade(path: Path) -> bool:
    return path.relative_to(REPO_ROOT).as_posix() in ALLOWED_KUZU_IMPORT_FILES


def _kuzu_imports_in_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] == "kuzu":
                    imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module is not None and node.module.split(".", 1)[0] == "kuzu":
                imported_names = ", ".join(alias.name for alias in node.names)
                imports.append(f"from {node.module} import {imported_names}")

    return imports


def test_direct_kuzu_imports_stay_in_graph_facade() -> None:
    violations: list[str] = []

    for path in _production_python_files():
        kuzu_imports = _kuzu_imports_in_file(path)
        if kuzu_imports and not _is_allowed_kuzu_facade(path):
            violations.extend(f"{path}: {imported_name}" for imported_name in kuzu_imports)

    assert not violations, (
        "Direct Kuzu imports must stay isolated to the graph storage facade.\n"
        "Allowed files:\n"
        + "\n".join(f"- {path}" for path in sorted(ALLOWED_KUZU_IMPORT_FILES))
        + "\nOffending imports:\n"
        + "\n".join(f"- {entry}" for entry in violations)
    )
