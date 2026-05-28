"""Compatibility shim for the moved Campy brain module.

Canonical location: campy.brain.brainstem.phase
"""

from campy.brain.brainstem.phase import *  # noqa: F401,F403
import sys as _sys
import types as _types
from campy.brain.brainstem import phase as _canonical_phase


class _PhaseShim(_types.ModuleType):
    """Transparent proxy to campy.brain.brainstem.phase.

    Forwards all attribute reads and writes (including private names) to the
    canonical module so that test code that manipulates module-level state via
    ``import mcp_engine.phase as phase_mod`` sees the same object as production
    code that imports from the canonical path.
    """

    def __getattr__(self, name: str):
        return getattr(_canonical_phase, name)

    def __setattr__(self, name: str, value) -> None:
        if name.startswith("_PhaseShim__") or name in ("__dict__", "__class__"):
            super().__setattr__(name, value)
        else:
            setattr(_canonical_phase, name, value)


_shim = _PhaseShim(__name__, __doc__)
_shim.__file__ = __file__
_shim.__loader__ = __loader__  # type: ignore[name-defined]
_shim.__package__ = __package__
_shim.__spec__ = __spec__  # type: ignore[name-defined]
_sys.modules[__name__] = _shim
