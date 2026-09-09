#!/usr/bin/env python3
"""
scripts/check_env_drift.py — B416: Local Environment Drift Guard.

Compares the packages installed in the *running interpreter's* environment
against the dependency closure this project actually declares (`pyproject.toml`
+ `requirements.txt`), and flags what is left over.

Why a closure, not a flat diff: a plain "installed minus declared" comparison
flags every transitive dependency too (pydantic pulls in annotated-types,
fastapi pulls in starlette, etc.) — in this repo that is 164 of 199 installed
packages, which drowns the 3 packages that actually matter. This script
instead does a breadth-first walk over each installed distribution's own
`requires` metadata (`importlib.metadata`), starting from the declared roots,
so anything reachable by a real dependency edge counts as legitimate. Only
packages installed for no traceable reason are reported.

Background (B416, see backlog/B416.md): `torch` is not declared anywhere in
this project. It arrived transitively via `sentence-transformers`, which B355
removed when fastembed replaced it as the embedding backend — but `.venv`s
that predate B355 (or that installed something else with a hard torch
dependency since) still carry it. `thinc.compat` (spaCy's ML backend
selection) unconditionally *attempts* `import torch` for backend
auto-detection, so merely having it installed costs ~150-225MB resident
whenever spaCy is loaded, in an environment production does not have. See
backlog/B400.md for the original investigation.

This is deliberately NOT wired into CI (see B416 "Explicitly NOT in scope"):
CI always installs clean from requirements.txt, so a drift check there would
guard nothing and only add a failure surface. This is a local-development
hazard, wired instead into benchmarks/kpi_monitor.py's measurement path
(B415) — a drifted environment cannot silently produce a baseline.

CLI usage:
    python scripts/check_env_drift.py              # human-readable report
    python scripts/check_env_drift.py --json        # machine-readable report
    python scripts/check_env_drift.py --quiet       # exit code only

Exit codes:
    0 — no known-harmful contaminants present (undeclared-but-benign packages
        may still be listed; they are not a failure by themselves)
    1 — one or more of the known-harmful packages (torch, sentence-
        transformers, transformers) is present and undeclared
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - repo requires-python is >=3.12
    import tomli as tomllib  # type: ignore[no-redef]

from importlib import metadata

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
REQUIREMENTS = REPO_ROOT / "requirements.txt"

# Every venv is bootstrapped with these before a single `pip install` from
# this project's own files ever runs. They are never "declared" by
# pyproject.toml/requirements.txt, but flagging them as drift would be noise,
# not signal.
BOOTSTRAP_EXEMPT = {"pip", "setuptools", "wheel"}

# B416: the specific contaminants this card exists to catch. If any of these
# show up undeclared, name them explicitly rather than burying them in a
# generic "undeclared" list.
KNOWN_HARMFUL = {"torch", "sentence-transformers", "transformers"}

# Installed out-of-band by a documented, non-pip step (`make install` /
# requirements.txt both say: after `pip install`, run
# `python -m spacy download en_core_web_md`) -- spaCy model data packaged as
# a pip-installable wheel, but it is not, and cannot be, a `pyproject.toml`
# / `requirements.txt` entry (its own index is spaCy's model release URL).
# Expected, not drift.
OUT_OF_BAND_EXEMPT = {"en-core-web-md"}

_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def _normalize(name: str) -> str:
    """PEP 503 normalization: case-insensitive; '.'/'_' collapse to '-'."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def _iter_requirement_names(specs: Iterable[str]) -> set[str]:
    """Extract bare package names from a list of PEP 508 requirement strings."""
    names: set[str] = set()
    for spec in specs:
        expr = spec.split(";", 1)[0].strip()  # drop environment markers
        if not expr:
            continue
        # Drop extras syntax, e.g. "uvicorn[standard]>=0.32.1" -> "uvicorn"
        expr = expr.split("[", 1)[0].strip()
        m = _NAME_RE.match(expr)
        if m:
            names.add(_normalize(m.group(1)))
    return names


def load_pyproject_declared(pyproject_path: Path = PYPROJECT) -> set[str]:
    """Every package pyproject.toml declares: main deps + all optional-dependency
    extras (dev/test/ollama/bedrock/observability/indicator), plus the project's
    own name (an editable install of the project itself is always a root)."""
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    declared = _iter_requirement_names(project.get("dependencies", []))
    for _extra_name, specs in project.get("optional-dependencies", {}).items():
        declared |= _iter_requirement_names(specs)
    declared.add(_normalize(project.get("name", "hippocampy")))
    return declared


def load_requirements_declared(requirements_path: Path = REQUIREMENTS) -> set[str]:
    if not requirements_path.exists():
        return set()
    lines = []
    for raw in requirements_path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return _iter_requirement_names(lines)


def installed_distributions() -> dict[str, metadata.Distribution]:
    """All distributions visible to the *running* interpreter, keyed by
    normalized name. Reflects whichever python executed this script -- run it
    with the interpreter whose environment you want inspected."""
    dists: dict[str, metadata.Distribution] = {}
    for dist in metadata.distributions():
        name = dist.metadata.get("Name")
        if not name:
            continue
        dists[_normalize(name)] = dist
    return dists


def _dist_requires(dist: metadata.Distribution) -> set[str]:
    """Direct dependency names declared by an installed distribution's own
    metadata (its `Requires-Dist` entries), excluding requirements gated
    behind an extra nothing in this project's closure has requested (e.g.
    `torch ; extra == "torch"` on thinc -- present in thinc's metadata, but
    inert unless something installs `thinc[torch]`)."""
    requires = dist.requires or []
    names: set[str] = set()
    for req in requires:
        if "extra ==" in req or "extra==" in req or "extra ==" in req.replace("'", '"'):
            continue
        expr = req.split(";", 1)[0].strip()
        expr = expr.split("[", 1)[0].strip()
        m = _NAME_RE.match(expr)
        if m:
            names.add(_normalize(m.group(1)))
    return names


def compute_dependency_closure(
    roots: set[str],
    installed: dict[str, metadata.Distribution],
    self_name: str | None = None,
) -> set[str]:
    """BFS over installed distributions' own `requires` metadata, starting
    from the declared roots. A package is "legitimate" if there is a real
    dependency edge — declared-or-transitive — reaching it; this is what
    distinguishes an actual transitive dependency from an orphan.

    `self_name` (this project's own normalized name, e.g. "hippocampy") is
    never expanded via its *installed* distribution metadata: an editable
    `pip install -e .` bakes a snapshot of pyproject.toml's dependencies into
    the installed dist-info at install time, and nothing re-syncs it when
    pyproject.toml changes afterward without a reinstall -- exactly the kind
    of stale-venv drift this script exists to catch. Its direct dependencies
    are already in `roots`, read straight from the current pyproject.toml
    source, which is the authoritative, always-current copy.
    """
    closure: set[str] = set()
    frontier = set(roots) | BOOTSTRAP_EXEMPT | OUT_OF_BAND_EXEMPT
    while frontier:
        name = frontier.pop()
        if name in closure:
            continue
        closure.add(name)
        if self_name is not None and name == self_name:
            continue  # see docstring: don't trust our own installed metadata
        dist = installed.get(name)
        if dist is None:
            continue  # declared but not installed (e.g. an unused extra) -- fine
        for dep in _dist_requires(dist):
            if dep not in closure:
                frontier.add(dep)
    return closure


def check_env_drift() -> dict:
    """Run the full drift check against the current interpreter's environment."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    self_name = _normalize(data.get("project", {}).get("name", "hippocampy"))

    declared = load_pyproject_declared() | load_requirements_declared()
    installed = installed_distributions()
    closure = compute_dependency_closure(declared, installed, self_name=self_name)

    undeclared = sorted(name for name in installed if name not in closure)
    known_harmful_present = sorted(name for name in undeclared if name in KNOWN_HARMFUL)
    legitimate_transitive = sorted(
        name for name in installed if name in closure and name not in declared
    )

    return {
        "python_executable": sys.executable,
        "declared_count": len(declared),
        "installed_count": len(installed),
        "closure_count": len(closure),
        "declared": sorted(declared),
        "legitimate_transitive_count": len(legitimate_transitive),
        "legitimate_transitive_sample": legitimate_transitive[:15],
        "undeclared_count": len(undeclared),
        "undeclared": undeclared,
        "known_harmful_present": known_harmful_present,
        "drifted": bool(known_harmful_present),
    }


def format_report(result: dict) -> str:
    lines = [
        "HippoCampy Environment Drift Check (B416)",
        f"  interpreter        : {result['python_executable']}",
        f"  declared (roots)   : {result['declared_count']}",
        f"  installed          : {result['installed_count']}",
        f"  dependency closure : {result['closure_count']}",
        f"  legitimate transitive (undeclared but reachable): {result['legitimate_transitive_count']}",
        f"  undeclared (not reachable from any declared root): {result['undeclared_count']}",
    ]
    if result["undeclared"]:
        lines.append("")
        lines.append("  Undeclared packages:")
        for name in result["undeclared"]:
            marker = "  *** KNOWN HARMFUL ***" if name in result["known_harmful_present"] else ""
            lines.append(f"    - {name}{marker}")
    if result["known_harmful_present"]:
        lines.append("")
        lines.append(
            "DRIFTED: known-harmful contaminant(s) present and undeclared: "
            + ", ".join(result["known_harmful_present"])
        )
        lines.append(
            "  torch typically arrives via sentence-transformers/transformers "
            "(removed by B355) and costs ~150-225MB RSS via thinc.compat's "
            "opportunistic `import torch` whenever spaCy loads."
        )
        lines.append("  Rebuild with: make rebuild-venv")
    else:
        lines.append("")
        lines.append("OK: no known-harmful contaminants detected.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="B416: Local environment drift guard.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--quiet", action="store_true", help="Suppress report; exit code only.")
    args = parser.parse_args()

    result = check_env_drift()

    if args.json:
        print(json.dumps(result, indent=2))
    elif not args.quiet:
        print(format_report(result))

    return 1 if result["drifted"] else 0


if __name__ == "__main__":
    sys.exit(main())
