"""
mcp_engine/tools/arc_mechanics.py — compatibility shim

Canonical implementation has moved to:
    campy.brain.thalamus.tools.arc_mechanics
"""
# ruff: noqa: F401

from campy.brain.thalamus.tools.arc_mechanics import (
    ARC_DOMAINS,
    SUMMARY_LIMIT,
    publish_mechanic_summary,
    recall_mechanic_priors,
    # Private helpers
    _now_iso,
    _normalized_json,
    _record_hash,
    _compact,
    _safe_float,
    _safe_int,
)
