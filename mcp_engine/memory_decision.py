"""
mcp_engine/memory_decision.py — compatibility shim

Canonical location: campy/brain/thalamus/memory_decision.py
"""
# ruff: noqa: F401, F403
from campy.brain.thalamus.memory_decision import (
    decide_memory_action,
    _is_multi_entity,
    _extract_key_entities,
)

__all__ = [
    "decide_memory_action",
    "_is_multi_entity",
    "_extract_key_entities",
]
