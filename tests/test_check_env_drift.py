"""
tests/test_check_env_drift.py — Tests for scripts/check_env_drift.py (B416).

Closure-computation logic is tested against synthetic fixtures (not the
ambient interpreter's real installed packages) so these tests are
deterministic regardless of which venv runs them -- including this
checkout's own .venv, which (per B416's whole premise) may itself be
drifted. `check_env_drift()` end-to-end is also exercised against the real
pyproject.toml/requirements.txt and the real running interpreter, but only
for assertions that hold true in *any* environment (declared roots are
never flagged as undeclared).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_env_drift import (
    BOOTSTRAP_EXEMPT,
    KNOWN_HARMFUL,
    _iter_requirement_names,
    _normalize,
    check_env_drift,
    compute_dependency_closure,
    load_pyproject_declared,
    load_requirements_declared,
)


def _dist(requires: list[str]):
    """A minimal stand-in for importlib.metadata.Distribution: check_env_drift
    only ever reads `.requires` off it."""
    return SimpleNamespace(requires=requires)


def test_normalize_pep503():
    assert _normalize("Sentence-Transformers") == "sentence-transformers"
    assert _normalize("typing_extensions") == "typing-extensions"
    assert _normalize("PyYAML") == "pyyaml"
    assert _normalize("some.pkg__name") == "some-pkg-name"


def test_iter_requirement_names_strips_markers_extras_versions():
    names = _iter_requirement_names(
        [
            "fastapi>=0.133.0",
            "click>=8.2",
            "torch>=1.6.0; extra == \"torch\"",
            "uvicorn[standard]>=0.32.1",
            "typing-extensions ; python_version < \"3.11\"",
        ]
    )
    assert names == {"fastapi", "click", "torch", "uvicorn", "typing-extensions"}


def test_compute_dependency_closure_reaches_transitive_deps():
    # A -> B -> C is a real dependency chain; C is "legitimate transitive",
    # not orphaned, even though only A is declared.
    installed = {
        "a": _dist(["b>=1.0"]),
        "b": _dist(["c>=1.0"]),
        "c": _dist([]),
        "orphan": _dist([]),
    }
    closure = compute_dependency_closure({"a"}, installed)
    assert "a" in closure
    assert "b" in closure
    assert "c" in closure
    assert "orphan" not in closure


def test_compute_dependency_closure_skips_extra_gated_requirements():
    # thinc-style: torch only reachable if something requests the "torch" extra,
    # which nothing here does -- so torch must NOT be pulled into the closure.
    installed = {
        "thinc": _dist(['torch>=1.6.0; extra == "torch"', "numpy>=1.19"]),
        "torch": _dist([]),
        "numpy": _dist([]),
    }
    closure = compute_dependency_closure({"thinc"}, installed)
    assert "numpy" in closure
    assert "torch" not in closure


def test_compute_dependency_closure_bootstrap_exempt_always_present():
    installed = {name: _dist([]) for name in BOOTSTRAP_EXEMPT}
    closure = compute_dependency_closure(set(), installed)
    assert BOOTSTRAP_EXEMPT <= closure


def test_compute_dependency_closure_does_not_trust_stale_self_metadata():
    """B416's actual bug, caught while building this script: an editable
    `pip install -e .` bakes pyproject.toml's dependencies into the
    installed dist-info at install time. If pyproject.toml later drops a
    dependency (e.g. B355 dropping sentence-transformers) without a
    reinstall, the *installed* hippocampy metadata still lists it -- which
    would otherwise make the closure walk "legitimize" a real contaminant
    via a stale self-reference. self_name must not be expanded that way."""
    installed = {
        "hippocampy": _dist(["sentence-transformers>=2.2.0"]),  # stale, pre-B355 metadata
        "sentence-transformers": _dist(["torch>=1.11.0"]),
        "torch": _dist([]),
    }
    # Roots come from the *current* pyproject.toml source, which no longer
    # declares sentence-transformers -- only "hippocampy" itself is a root.
    closure = compute_dependency_closure({"hippocampy"}, installed, self_name="hippocampy")
    assert "hippocampy" in closure
    assert "sentence-transformers" not in closure
    assert "torch" not in closure


def test_compute_dependency_closure_trusts_non_self_metadata():
    # Without the self_name carve-out, a normal (non-self) package's
    # installed metadata is trusted normally.
    installed = {
        "hippocampy": _dist([]),
        "fastapi": _dist(["starlette>=1.0"]),
        "starlette": _dist([]),
    }
    closure = compute_dependency_closure({"hippocampy", "fastapi"}, installed, self_name="hippocampy")
    assert "starlette" in closure


def test_load_pyproject_declared_includes_known_direct_deps():
    declared = load_pyproject_declared()
    for name in ("fastembed", "pyoxigraph", "spacy", "typer", "fastapi", "hippocampy"):
        assert name in declared, f"{name} should be a declared root"
    # B355: sentence-transformers was removed as a dependency; it must not
    # be declared, or a real contamination would go undetected.
    assert "sentence-transformers" not in declared
    assert "torch" not in declared


def test_load_requirements_declared_includes_known_direct_deps():
    declared = load_requirements_declared()
    for name in ("pyoxigraph", "fastembed", "spacy", "psutil", "pytest"):
        assert name in declared


def test_known_harmful_set_matches_card():
    assert KNOWN_HARMFUL == {"torch", "sentence-transformers", "transformers"}


def test_check_env_drift_end_to_end_never_flags_declared_roots():
    """Runs against the real pyproject.toml/requirements.txt and whatever
    interpreter executes pytest. Regardless of whether *this* interpreter
    happens to be drifted (the repo's shared .venv may well be, per B416's
    premise), nothing this project actually declares should ever show up in
    `undeclared` -- that would mean the closure walk is broken, not that
    the environment is contaminated."""
    result = check_env_drift()
    declared = load_pyproject_declared() | load_requirements_declared()
    installed_and_declared = declared & set(result["undeclared"])
    assert installed_and_declared == set(), (
        f"declared packages incorrectly flagged as undeclared: {installed_and_declared}"
    )
    assert result["declared_count"] > 0
    assert result["installed_count"] > 0
    assert result["closure_count"] >= result["declared_count"]


def test_check_env_drift_known_harmful_present_is_subset_of_known_harmful():
    result = check_env_drift()
    assert set(result["known_harmful_present"]) <= KNOWN_HARMFUL
    assert result["drifted"] == bool(result["known_harmful_present"])
