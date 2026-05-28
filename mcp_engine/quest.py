"""Compatibility shim for the moved Campy brain module.

Canonical location: campy.brain.hippocampus.quest
"""

from campy.brain.hippocampus.quest import *  # noqa: F401,F403
from campy.brain.hippocampus.quest import _query_artifacts, _basename  # noqa: F401
import sys as _sys
import types as _types
from campy.brain.hippocampus import quest as _canonical_quest


class _QuestShim(_types.ModuleType):
    """Transparent proxy to campy.brain.hippocampus.quest.

    Forwards all attribute reads and writes (including private names) to the
    canonical module so that test code that manipulates module-level state via
    ``import mcp_engine.quest as quest_mod`` sees the same object as production
    code that imports from the canonical path.
    """

    def __getattr__(self, name: str):
        return getattr(_canonical_quest, name)

    def __setattr__(self, name: str, value) -> None:
        if name.startswith("_QuestShim__") or name in ("__dict__", "__class__"):
            super().__setattr__(name, value)
        else:
            setattr(_canonical_quest, name, value)


_shim = _QuestShim(__name__, __doc__)
_shim.__file__ = __file__
_shim.__loader__ = __loader__  # type: ignore[name-defined]
_shim.__package__ = __package__
_shim.__spec__ = __spec__  # type: ignore[name-defined]
_sys.modules[__name__] = _shim
