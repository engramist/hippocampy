"""
B300 — regression tests for the junk-concept gate tightening.

Covers the three observed real-graph junk patterns: bare cardinal number
words reifying as Constraints, single-token entities crossing HARD_LOCK,
and sub-signal fragments surfacing in quest_context.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Task 1 — cardinal number words are junk (step1_ner)
# ---------------------------------------------------------------------------

def test_is_junk_entity_rejects_bare_cardinal():
    from campy.brain.temporal_lobe.loop.step1_ner import _is_junk_entity
    assert _is_junk_entity("four") is True


def test_is_junk_entity_rejects_hyphenated_cardinal():
    from campy.brain.temporal_lobe.loop.step1_ner import _is_junk_entity
    assert _is_junk_entity("twenty-four") is True


def test_is_junk_entity_rejects_cardinal_case_insensitive():
    from campy.brain.temporal_lobe.loop.step1_ner import _is_junk_entity
    assert _is_junk_entity("Twenty") is True


def test_is_junk_entity_keeps_number_in_larger_phrase():
    from campy.brain.temporal_lobe.loop.step1_ner import _is_junk_entity
    assert _is_junk_entity("four retries max") is False


# ---------------------------------------------------------------------------
# Task 2 — single tokens never reify (step4_pattern)
# ---------------------------------------------------------------------------

def test_classify_artifact_single_token_capped_below_hard_lock():
    from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact, HARD_LOCK
    result = classify_artifact("four", "Restriction", "Demand")
    assert result["confidence"] <= 0.60
    assert result["confidence"] < HARD_LOCK
    assert result["confidence_low"] is True


def test_classify_artifact_single_token_entity_capped_despite_boosts():
    """Mirrors the real observed bug: single-token entity ("four") embedded
    in a sentence with a strong constraint keyword + gist agreement, which
    would otherwise reach 0.92 and HARD_LOCK as a confirmed Constraint."""
    from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact, HARD_LOCK
    result = classify_artifact(
        "You must have four retries.", "Restriction", "Demand", entity_text="four"
    )
    assert result["confidence"] <= 0.60
    assert result["confidence"] < HARD_LOCK
    assert result["confidence_low"] is True


def test_classify_artifact_multiword_constraint_still_reifies():
    """No regression: legitimate multi-word constraints still cross HARD_LOCK."""
    from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact, HARD_LOCK
    result = classify_artifact(
        "All endpoints must require JWT authentication.",
        "Restriction", "Demand"
    )
    assert result["should_proceed"] is True
    assert result["artifact_type"] == "constraint"
    assert result["confidence"] >= HARD_LOCK
    assert result["confidence_low"] is False


# ---------------------------------------------------------------------------
# Task 3 — quest_context stops surfacing sub-signal fragments
# ---------------------------------------------------------------------------

def test_get_quest_context_filters_terminal_fragment():
    from campy.brain.hippocampus.quest import get_quest_context

    class MockResult:
        def __init__(self, rows):
            self._rows = rows
            self._idx = 0

        def has_next(self):
            return self._idx < len(self._rows)

        def get_next(self):
            row = self._rows[self._idx]
            self._idx += 1
            return row

    class MockDB:
        def execute(self, query, params=None):
            if "RETURN q.name, q.status" in query:
                return MockResult([["Test Quest", "active"]])
            if "a:Constraint" in query:
                return MockResult([
                    ["c1", "four", False, 0.90],
                    ["c2", "Use Apache-2.0 for all new files", False, 0.80],
                ])
            return MockResult([])

    ctx = get_quest_context(MockDB(), "quest-1")

    texts = [c["text_raw"] for c in ctx["recent_constraints"]]
    assert "four" not in texts
    assert "Use Apache-2.0 for all new files" in texts
