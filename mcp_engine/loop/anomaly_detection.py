"""Compatibility shim for the moved Campy brain module.

Canonical location: campy.brain.temporal_lobe.loop.anomaly_detection
"""

from campy.brain.temporal_lobe.loop.anomaly_detection import *  # noqa: F401,F403
from campy.brain.temporal_lobe.loop.anomaly_detection import (  # noqa: F401
    _cosine_similarity,
    _get_high_confidence_constraints,
    _get_high_confidence_preferences,
)
