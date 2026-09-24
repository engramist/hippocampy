import sys
import types
import importlib.machinery
import pytest

# Required for pytest-asyncio < 0.21 compatibility
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )

# ---------------------------------------------------------------------------
# spaCy compatibility shim
#
# spaCy 3.x uses pydantic.v1 compatibility which is broken on Python 3.14.
# Pre-stub `spacy` in sys.modules so that modules which `import spacy` at
# module-level don't corrupt sys.modules and cascade-fail unrelated tests.
#
# Tests that need a *real* working spaCy (i.e. actual NER output) must check
# `SPACY_AVAILABLE` and skip when False.
# ---------------------------------------------------------------------------
SPACY_AVAILABLE = False
try:
    import spacy as _real_spacy
    # Import alone isn't enough — spaCy 3.x loads on Python 3.14 but
    # pydantic v1 compat is broken, so spacy.load() fails at runtime.
    _real_spacy.load("en_core_web_md")
    SPACY_AVAILABLE = True
except Exception:
    # Build a minimal stub that satisfies `import spacy` without side-effects.
    _stub = types.ModuleType("spacy")
    _stub.__version__ = "0.0.0+stub"
    _stub.__spec__ = importlib.machinery.ModuleSpec("spacy", loader=None)

    def _load_unavailable(model_name="en_core_web_md"):
        raise RuntimeError(
            f"spaCy is not available on this Python version "
            f"(Python {sys.version_info.major}.{sys.version_info.minor}). "
            "Skip this test with: @pytest.mark.skipif(not SPACY_AVAILABLE, ...)"
        )

    _stub.load = _load_unavailable
    # Register the stub and common sub-modules before any test imports them.
    sys.modules.setdefault("spacy", _stub)
    for _sub in [
        "spacy.language", "spacy.pipeline", "spacy.tokens",
        "spacy.vocab", "spacy.schemas", "spacy.errors",
        "spacy.util", "spacy.attrs", "spacy.matcher",
    ]:
        _submod = types.ModuleType(_sub)
        _submod.__spec__ = importlib.machinery.ModuleSpec(_sub, loader=None)
        sys.modules.setdefault(_sub, _submod)

# ---------------------------------------------------------------------------
# Kùzu test client compatibility shim (B397)
#
# Production code has removed KuzuClient (B397 cutover to Oxigraph + sqlite-vec).
# When kuzu is installed in the test environment, tests that explicitly verify
# backward compatibility (e.g. migration roundtrip, vector parity) can resolve
# KuzuClient via tests.kuzu_test_client.
# ---------------------------------------------------------------------------
try:
    import tests.kuzu_test_client as _kuzu_test_mod
    if _kuzu_test_mod.KUZU_AVAILABLE:
        sys.modules.setdefault("tests.kuzu_test_client", _kuzu_test_mod)
except Exception:
    pass


# ---------------------------------------------------------------------------
# B455: never let the suite touch the developer's real, running daemon.
#
# A full run on a dev machine used to `launchctl unload`/`load` the real
# ~/Library/LaunchAgents/ai.hippocampy.brain.plist (and could `pkill`), bouncing
# the live daemon mid-work. CI has no daemon so it never noticed. Any test that
# needs to observe these calls re-patches `subprocess.run` itself (as
# tests/test_bringup_priorities.py already does), which overrides this guard.
# ---------------------------------------------------------------------------
_DESTRUCTIVE_LAUNCHCTL_VERBS = frozenset(
    {"unload", "load", "remove", "bootout", "bootstrap", "kickstart", "stop", "start", "kill"}
)


@pytest.fixture(autouse=True)
def _never_touch_the_live_daemon(monkeypatch):
    import subprocess
    from pathlib import Path

    real_run = subprocess.run

    def _argv0(cmd):
        first = cmd[0] if isinstance(cmd, (list, tuple)) and cmd else cmd
        return Path(str(first)).name if isinstance(first, (str, Path)) else ""

    def guard(cmd, *args, **kwargs):
        name = _argv0(cmd)
        argv = list(cmd) if isinstance(cmd, (list, tuple)) else []
        if name in ("pkill", "killall") or (
            name == "launchctl" and len(argv) > 1 and str(argv[1]) in _DESTRUCTIVE_LAUNCHCTL_VERBS
        ):
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guard)
