"""Compatibility shim for the moved Campy brain module.

Canonical location: campy.brain.brainstem.sweep_patterns
"""

from campy.brain.brainstem.sweep_patterns import *  # noqa: F401,F403
from campy.brain.brainstem.sweep_patterns import (  # noqa: F401
    _discover_temporal_patterns,
    _discover_sequence_patterns,
    _discover_frequency_patterns,
    _deduplicate_candidates,
    _validate_candidates,
    _write_trigger_metadata,
    _call_llm,
    _VALIDATION_PROMPT,
)
