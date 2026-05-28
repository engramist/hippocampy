"""Compatibility shim for the moved Campy brain module.

Canonical location: campy.brain.hippocampus.hippocampus
"""

from campy.brain.hippocampus.hippocampus import *  # noqa: F401,F403
from campy.brain.hippocampus.hippocampus import (  # noqa: F401
    _check_existing_binding,
    _system1_git_match,
    _system1_semantic_match,
    _apply_workspace_boost,
    _system2_disambiguate,
    _bind_session,
    _ensure_git_repo_root,
    _logger,
)
import sys as _sys
import types as _types
from campy.brain.hippocampus import hippocampus as _canonical_hippocampus


class _HippocampusShim(_types.ModuleType):
    """Transparent proxy to campy.brain.hippocampus.hippocampus.

    Forwards all attribute reads and writes (including private names) to the
    canonical module so that test code that manipulates module-level state via
    ``import mcp_engine.hippocampus as hipp_mod`` sees the same object as
    production code that imports from the canonical path.
    """

    def __getattr__(self, name: str):
        return getattr(_canonical_hippocampus, name)

    def __setattr__(self, name: str, value) -> None:
        if name.startswith("_HippocampusShim__") or name in ("__dict__", "__class__"):
            super().__setattr__(name, value)
        else:
            setattr(_canonical_hippocampus, name, value)


_shim = _HippocampusShim(__name__, __doc__)
_shim.__file__ = __file__
_shim.__loader__ = __loader__  # type: ignore[name-defined]
_shim.__package__ = __package__
_shim.__spec__ = __spec__  # type: ignore[name-defined]
_sys.modules[__name__] = _shim
