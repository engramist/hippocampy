#!/usr/bin/env python3
"""Fail if pyproject dependency floors drift below reviewed requirements pins."""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = REPO_ROOT / "requirements.txt"
PYPROJECT = REPO_ROOT / "pyproject.toml"

REQ_PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.!+-]+)$")
SPEC_RE = re.compile(r"([A-Za-z0-9_.-]+)\s*([<>=!~]{1,2})\s*([A-Za-z0-9_.!+-]+)")
EXACT_RE = re.compile(r"^([A-Za-z0-9_.-]+)===?([A-Za-z0-9_.!+-]+)$")


def _normalize_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _load_requirements_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = REQ_PIN_RE.match(line)
        if not m:
            continue
        name, version = m.groups()
        pins[_normalize_name(name)] = version
    return pins


def _extract_floor(spec: str) -> tuple[str, str] | None:
    expr = spec.split(";", 1)[0].strip()
    # exact pin in pyproject counts as a floor too
    exact = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.!+-]+)", expr)
    if exact:
        return _normalize_name(exact.group(1)), exact.group(2)

    m = re.match(r"([A-Za-z0-9_.-]+)", expr)
    if not m:
        return None
    name = _normalize_name(m.group(1))

    floors: list[str] = []
    for sm in SPEC_RE.finditer(expr):
        op = sm.group(2)
        version = sm.group(3)
        if op == ">=" or op == ">":
            floors.append(version)

    if not floors:
        return None

    floor = max(floors, key=Version)
    return name, floor


def _load_pyproject_floors(path: Path) -> dict[str, str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    deps = data.get("project", {}).get("dependencies", [])
    floors: dict[str, str] = {}
    for dep in deps:
        parsed = _extract_floor(dep)
        if parsed is None:
            continue
        name, floor = parsed
        floors[name] = floor
    return floors


def main() -> int:
    req_pins = _load_requirements_pins(REQUIREMENTS)
    py_floors = _load_pyproject_floors(PYPROJECT)

    failures: list[str] = []
    checked = 0

    for name, pinned in sorted(req_pins.items()):
        floor = py_floors.get(name)
        if floor is None:
            continue
        checked += 1
        if Version(floor) < Version(pinned):
            failures.append(
                f"{name}: pyproject floor {floor} is below reviewed requirements pin {pinned}"
            )

    if failures:
        print("Dependency floor drift detected:")
        for f in failures:
            print(f"- {f}")
        return 1

    print(f"Dependency floor check passed ({checked} shared dependencies verified).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
