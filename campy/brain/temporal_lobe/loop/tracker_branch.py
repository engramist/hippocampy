"""B543: the original decision tracker (Loop steps 2-7) as a deprecated side branch.

DEPRECATED (B543): steps 2-7 were built to track a developer's decisions. They used to gate whether any
entity of a turn was stored. With `[loop] tracker_side_branch` on they only ADD records (Decision, Constraint,
Requirement, ActionItem, Lesson, Procedure, relations, co-occurrence) and never remove a stored Concept or
withhold a turn's Observation extraction. What is stored is decided by the entity rules (B544 admission).
Kept working for the developer store (Layer 2 triggers read Lessons and Procedures). Removal is a later decision.
"""

from __future__ import annotations

import logging

STATUS = "deprecated: side branch (B543)"

_logger = logging.getLogger(__name__)


def tracker_side_branch_enabled(config: dict | None) -> bool:
    """`[loop] tracker_side_branch` (default false; env `CAMPY_TRACKER_SIDE_BRANCH=1` turns it on).
    A config without the key reads as off."""
    return bool(((config or {}).get("loop") or {}).get("tracker_side_branch", False))


def warn_if_tracker_without_admission(config: dict | None) -> bool:
    """Log one warning (daemon start) when the flag is on and `entity_admission` is off: then no rule stores
    entities and the tracker is the only store of them, which is the legacy state. Returns whether it warned."""
    if not tracker_side_branch_enabled(config):
        return False
    if bool(((config or {}).get("loop") or {}).get("entity_admission", False)):
        return False
    _logger.warning(
        "[loop] tracker_side_branch is on but entity_admission is off: no rule stores entities, so the "
        "deprecated decision tracker is still the only thing deciding which entities are stored")
    return True
