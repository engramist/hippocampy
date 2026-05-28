"""Compatibility shim for the moved Campy brain module.

Canonical location: campy.brain.temporal_lobe.loop.step4b_associative
"""

from campy.brain.temporal_lobe.loop.step4b_associative import *  # noqa: F401,F403
from campy.brain.temporal_lobe.loop.step4b_associative import (  # noqa: F401
    _has_signal,
    _build_trigger_pattern,
    _ERROR_INDICATORS,
    _ACTION_INDICATORS,
)
