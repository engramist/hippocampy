"""Architecture boundary checks for Campy production modules.

These tests enforce the repository rule that production memory-engine code under
`campy/` and `mcp_engine/` must not import agent runtime or benchmark packages.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOTS = ("campy", "mcp_engine")
FORBIDDEN_TOP_LEVEL_MODULES = ("agents", "benchmarks")
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


def _production_python_files() -> list[Path]:
    files: list[Path] = []
    for root_name in PRODUCTION_ROOTS:
        root = REPO_ROOT / root_name
        if not root.exists():
            continue

        for path in root.rglob("*.py"):
            if any(part.startswith(".") or part in IGNORED_DIR_NAMES for part in path.parts):
                continue
            if any(part in IGNORED_DIR_NAMES for part in path.parts):
                continue
            files.append(path)

    return sorted(files)


def _forbidden_imports_in_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_name = alias.name.split(".", 1)[0]
                if root_name in FORBIDDEN_TOP_LEVEL_MODULES:
                    violations.append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module is not None:
                root_name = node.module.split(".", 1)[0]
                if root_name in FORBIDDEN_TOP_LEVEL_MODULES:
                    violations.append(node.module)

    return violations


def test_production_campy_modules_do_not_import_agents_or_benchmarks() -> None:
    violations: list[str] = []

    for path in _production_python_files():
        forbidden_imports = _forbidden_imports_in_file(path)
        for imported_name in forbidden_imports:
            violations.append(f"{path}: {imported_name}")

    assert not violations, (
        "Production Campy modules must not import agent runtime or benchmark code.\n"
        "Offending imports:\n"
        + "\n".join(f"- {entry}" for entry in violations)
    )
