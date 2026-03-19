import sys
import types
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
        sys.modules.setdefault(_sub, types.ModuleType(_sub))
