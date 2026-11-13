#!/usr/bin/env python3
"""
Benchmark-name guard (PRINCIPLES.md, Principle 4: generalise, don't memorise).

The package must not behave differently because it is being benchmarked. This check
fails when a benchmark's name or one of its conversation ids appears in the code of
`campy/`: in an identifier, or in a string the program uses.

Comments and docstrings are not code and are not checked: they are where a gate result
is recorded ("LoCoMo 28 gained / 12 lost").

A deliberate exception goes in ALLOWED below, as "path:name", with a reason next to it.

Usage:
    python scripts/check_benchmark_names.py
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCANNED = "campy"

# A benchmark name, or a benchmark conversation id such as conv-26.
NAME_RE = re.compile(r"locomo|long_?mem_?eval|\bdmr\b|\bconv-\d{1,3}\b", re.IGNORECASE)

# "relative/path.py:matched text" -> allowed. Keep empty unless there is a reason.
ALLOWED: set[str] = set()


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def find_hits(source: str) -> list[tuple[int, str]]:
    """Return (line, matched text) for each benchmark name in identifiers or used strings."""
    tree = ast.parse(source)
    docstrings = _docstring_nodes(tree)
    hits = []
    for node in ast.walk(tree):
        texts = []
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            texts.append(node.value)
        elif isinstance(node, ast.Name):
            texts.append(node.id)
        elif isinstance(node, ast.Attribute):
            texts.append(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            texts.append(node.name)
        elif isinstance(node, ast.arg):
            texts.append(node.arg)
        elif isinstance(node, ast.keyword) and node.arg:
            texts.append(node.arg)
        for text in texts:
            m = NAME_RE.search(text)
            if m:
                hits.append((getattr(node, "lineno", 0), m.group(0)))
    return sorted(set(hits))


def scan(root: Path) -> list[str]:
    problems = []
    for path in sorted((root / SCANNED).rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if "__pycache__" in rel:
            continue
        try:
            hits = find_hits(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        for line, text in hits:
            if f"{rel}:{text}" not in ALLOWED:
                problems.append(f"{rel}:{line}: {text!r}")
    return problems


def main() -> int:
    problems = scan(REPO_ROOT)
    if problems:
        print("FAIL: a benchmark name appears in the code of campy/ (Principle 4):")
        for p in problems:
            print(f"  {p}")
        print("\nA rule must name a general construction, not a benchmark. Remove the name, or add a "
              "reasoned entry to ALLOWED in scripts/check_benchmark_names.py.")
        return 1
    print("Benchmark-name guard OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
