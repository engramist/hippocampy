#!/usr/bin/env python3
"""Fail if pyproject dependency floors drift below reviewed requirements pins."""

from __future__ import annotations

import logging
import re
import sys
import tomllib
from pathlib import Path

from packaging.version import Version

# Configure logging for warning output
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

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
    """Extract package name and minimum version from a dependency spec.
    
    B340: Improved to warn on unparseable dependencies instead of silently
    skipping them. Returns None only for truly optional/extras specs that
    should be skipped, not for malformed dependency lines.
    
    Args:
        spec: A single dependency specifier string (before environment markers)
    
    Returns:
        (normalized_name, floor_version) or None if spec is skipped
        (e.g., contains environment markers we don't check)
    """
    expr = spec.split(";", 1)[0].strip()
    if not expr:
        return None
    
    # exact pin in pyproject counts as a floor too
    exact = re.fullmatch(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.!+-]+)", expr)
    if exact:
        return _normalize_name(exact.group(1)), exact.group(2)

    m = re.match(r"([A-Za-z0-9_.-]+)", expr)
    if not m:
        logger.warning(f"B340: Could not extract package name from dependency spec: {spec!r}")
        return None
    name = _normalize_name(m.group(1))

    floors: list[str] = []
    for sm in SPEC_RE.finditer(expr):
        op = sm.group(2)
        version = sm.group(3)
        if op == ">=" or op == ">":
            floors.append(version)

    if not floors:
        # Only warn if this looks like it should have had a version floor
        # (i.e., not a wildcard-only spec like "package" or "package!=1.0")
        if any(op in expr for op in [">=", ">"]):
            logger.warning(
                f"B340: Dependency spec has >= or > operator but no version extracted: {spec!r}"
            )
        # Otherwise silently skip specs without floor constraints
        return None

    floor = max(floors, key=Version)
    return name, floor


def _load_pyproject_floors(path: Path) -> dict[str, str]:
    """Load dependency specifications from pyproject.toml.
    
    B340: Reads both main dependencies and optional-dependencies (dev extras).
    Returns a dict mapping package name (normalized) to minimum version floor.
    """
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    
    # Main dependencies
    deps = data.get("project", {}).get("dependencies", [])
    floors: dict[str, str] = {}
    unparseable = []
    
    for dep in deps:
        parsed = _extract_floor(dep)
        if parsed is None:
            unparseable.append(dep)
            continue
        name, floor = parsed
        floors[name] = floor
    
    if unparseable:
        logger.warning(f"B340: {len(unparseable)} main dependencies have no version floor: {unparseable}")
    
    # B340: Optional dependencies (dev extras, tests, etc.)
    optional_deps = data.get("project", {}).get("optional-dependencies", {})
    opt_unparseable = []
    
    for extra_name, extra_deps in optional_deps.items():
        for dep in extra_deps:
            parsed = _extract_floor(dep)
            if parsed is None:
                opt_unparseable.append(f"{extra_name}: {dep}")
                continue
            name, floor = parsed
            # If already in main deps, main floor wins (stricter)
            if name not in floors or Version(floor) > Version(floors[name]):
                floors[name] = floor
    
    if opt_unparseable:
        logger.warning(f"B340: {len(opt_unparseable)} optional dependencies have no version floor: {opt_unparseable}")
    
    return floors


def main() -> int:
    req_pins = _load_requirements_pins(REQUIREMENTS)
    py_floors = _load_pyproject_floors(PYPROJECT)

    failures: list[str] = []
    missing_floors: list[str] = []
    checked = 0

    for name, pinned in sorted(req_pins.items()):
        floor = py_floors.get(name)
        if floor is None:
            # B340: Fail-closed — a pin in requirements.txt MUST have a floor in pyproject.
            # This is a structural gap that should not be silently ignored.
            missing_floors.append(name)
            continue
        checked += 1
        try:
            if Version(floor) < Version(pinned):
                failures.append(
                    f"{name}: pyproject floor {floor} is below reviewed requirements pin {pinned}"
                )
        except Exception as e:
            failures.append(
                f"{name}: could not compare versions (floor={floor!r}, pinned={pinned!r}): {e}"
            )

    if failures or missing_floors:
        print("Dependency floor drift detected:")
        for f in failures:
            print(f"  - {f}")
        if missing_floors:
            print(f"\nMissing floors (requirements.txt pins not covered by pyproject):")
            for name in missing_floors:
                print(f"  - {name}: {req_pins[name]}")
        return 1

    print(f"B340: Dependency floor check passed ({checked} verified).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
