"""Compatibility shim for the moved Campy brain module.

Canonical location: campy.brain.temporal_lobe.loop.step4_pattern
"""

from campy.brain.temporal_lobe.loop.step4_pattern import *  # noqa: F401,F403
from campy.brain.temporal_lobe.loop.step4_pattern import (  # noqa: F401
    _DECISION_SIGNALS,
    _CONSTRAINT_SIGNALS,
    _REQUIREMENT_SIGNALS,
    _ACTION_SIGNALS,
    _PLAN_SIGNALS,
    _SUCCESS_SIGNALS,
    _FAILURE_SIGNALS,
    _FRUSTRATION_SIGNALS,
    _EXCITEMENT_SIGNALS,
    _URGENCY_SIGNALS,
    _GIST_ARTIFACT_PRIOR,
    _match_signals,
    _entity_sentence,
    _noise_result,
)
