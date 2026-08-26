"""
tests/test_brain_daemon_shim.py — B365 drift-prevention guard.

The root-level `brain_daemon.py` used to be an independent, drifted copy of
`campy/brain_daemon.py` — see `backlog/B365.md` for the incident: a
connection-handling fix (B362) landed on the root file while the actual
shipped/launchd-preferred entry point stayed unpatched for a full day,
because nothing made it obvious the two files were different code.

B365 collapsed root `brain_daemon.py` into a pure re-export shim. This test
is the guard that makes the mistake class impossible to reintroduce
silently: if anyone ever adds real logic back to the root file (e.g. a new
`class BrainDaemon` definition, or a redefinition of any exported name),
the identity checks below fail immediately, in CI, rather than quietly
creating a second implementation nobody remembers to keep in sync.

Deliberately NOT a blanket "no top-level .py may shadow a name inside
campy/" check (the naive version of this guard) — that would forbid the
shim itself, which is the correct, intentional state here. The right
invariant is narrower and stronger: whatever root `brain_daemon.py`
exports must be *the same object* as `campy.brain_daemon`'s, not just a
same-named, independently-defined lookalike.
"""

from __future__ import annotations


def test_root_brain_daemon_is_a_pure_reexport_of_the_real_module():
    import brain_daemon as root
    import campy.brain_daemon as real

    assert root.BrainDaemon is real.BrainDaemon, (
        "root brain_daemon.py's BrainDaemon must be identical to "
        "campy.brain_daemon.BrainDaemon (a re-export), not a redefinition -- "
        "see backlog/B365.md for the incident this guards against"
    )
    assert root.main is real.main
    assert root.route_tool_call is real.route_tool_call


def test_root_brain_daemon_defines_no_independent_classes_or_functions():
    """Belt-and-suspenders: every public name in the shim must trace back to
    campy.brain_daemon's own module, not be freshly defined in root's
    __dict__ (which is exactly how the original drift happened -- a method
    added to root's own class definition instead of the real one)."""
    import brain_daemon as root
    import campy.brain_daemon as real

    for name in dir(root):
        if name.startswith("_"):
            continue
        value = getattr(root, name)
        if not callable(value):
            continue
        assert getattr(value, "__module__", None) != "brain_daemon", (
            f"{name!r} is defined directly in root brain_daemon.py's own "
            "module namespace instead of being re-exported from "
            "campy.brain_daemon -- this is exactly how B365's file "
            "divergence started. Move the definition into "
            "campy/brain_daemon.py and re-export it instead."
        )
