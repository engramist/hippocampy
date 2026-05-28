"""
Tests for mcp_engine/sweep_patterns.py — Offline Pattern Discovery (Phase 4).

Run with: python3 -m pytest tests/test_sweep_patterns.py -v
"""

from __future__ import annotations

import json
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Helpers / mock builders
# ---------------------------------------------------------------------------

def _make_db(rows_by_query=None, vector_results=None):
    """Build a mock DB that returns controlled data."""
    rows_by_query = rows_by_query or {}
    vector_results = vector_results or {}

    class MockResult:
        def __init__(self, rows):
            self._rows = list(rows)
            self._idx = 0
        def has_next(self):
            return self._idx < len(self._rows)
        def get_next(self):
            row = self._rows[self._idx]
            self._idx += 1
            return row

    class MockDB:
        def __init__(self):
            self.written = []

        def execute(self, q, p=None):
            for pattern, rows in rows_by_query.items():
                if pattern in q:
                    return MockResult(rows)
            return MockResult([])

        async def execute_write(self, q, p=None):
            self.written.append({"q": q, "p": p})

        def vector_search(self, table_name, index_name, vec, limit):
            return vector_results.get(index_name, [])

    return MockDB()


def _make_llm(response):
    """Build a mock LLM client that returns a fixed string."""
    class MockLLM:
        def chat(self, messages):
            if isinstance(response, str):
                return response
            return json.dumps(response)
    return MockLLM()


# ---------------------------------------------------------------------------
# discover_patterns — coordinator
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discover_patterns_disabled():
    """When enabled=false, returns zero counts immediately."""
    from campy.brain.brainstem.sweep_patterns import discover_patterns
    db = _make_db()
    config = {"sweep": {"patterns": {"enabled": False}}}
    result = await discover_patterns(db, config, llm_client=None)
    assert result["candidates_found"] == 0
    assert result["triggers_written"] == 0
    assert result["errors"] == 0


@pytest.mark.asyncio
async def test_discover_patterns_empty_graph():
    """Empty graph produces no candidates and no errors."""
    from campy.brain.brainstem.sweep_patterns import discover_patterns
    db = _make_db()
    config = {"sweep": {"patterns": {"enabled": True}}}
    result = await discover_patterns(db, config, llm_client=None)
    assert result["candidates_found"] == 0
    assert result["errors"] == 0


@pytest.mark.asyncio
async def test_discover_patterns_returns_expected_keys():
    """Summary dict contains all expected keys."""
    from campy.brain.brainstem.sweep_patterns import discover_patterns
    db = _make_db()
    config = {}
    result = await discover_patterns(db, config, llm_client=None)
    assert "candidates_found" in result
    assert "candidates_validated" in result
    assert "triggers_written" in result
    assert "errors" in result
    assert "by_type" in result
    assert "temporal" in result["by_type"]
    assert "sequence" in result["by_type"]
    assert "frequency" in result["by_type"]


@pytest.mark.asyncio
async def test_discover_patterns_individual_type_disable():
    """Each pattern type can be disabled independently."""
    from campy.brain.brainstem.sweep_patterns import discover_patterns
    db = _make_db()
    config = {"sweep": {"patterns": {
        "enabled": True,
        "temporal_enabled": False,
        "sequence_enabled": False,
        "frequency_enabled": True,
    }}}
    result = await discover_patterns(db, config, llm_client=None)
    assert result["by_type"]["temporal"] == 0
    assert result["by_type"]["sequence"] == 0
    assert result["errors"] == 0


# ---------------------------------------------------------------------------
# _discover_temporal_patterns
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_temporal_finds_consistent_interval():
    """Detects a pattern when messages occur at consistent intervals."""
    from campy.brain.brainstem.sweep_patterns import _discover_temporal_patterns

    base = datetime(2026, 5, 20, 8, 0, 0, tzinfo=timezone.utc)
    ts1 = base
    ts2 = base + timedelta(hours=8)
    ts3 = base + timedelta(hours=16)

    db = _make_db(rows_by_query={
        "CONTAINS_LESSON": [
            ["lesson-1", "SSO token expired after 8 hours", ts1],
            ["lesson-1", "SSO token expired after 8 hours", ts2],
            ["lesson-1", "SSO token expired after 8 hours", ts3],
        ],
    })

    result = await _discover_temporal_patterns(db, {})
    assert len(result) == 1
    assert result[0]["type"] == "temporal"
    assert result[0]["node_id"] == "lesson-1"
    assert abs(result[0]["mean_interval_seconds"] - 28800) < 100


@pytest.mark.asyncio
async def test_temporal_rejects_inconsistent_intervals():
    """Rejects patterns where intervals vary too much (high CV)."""
    from campy.brain.brainstem.sweep_patterns import _discover_temporal_patterns

    base = datetime(2026, 5, 20, 8, 0, 0, tzinfo=timezone.utc)
    ts1 = base
    ts2 = base + timedelta(hours=2)
    ts3 = base + timedelta(hours=20)

    db = _make_db(rows_by_query={
        "CONTAINS_LESSON": [
            ["lesson-1", "Random error", ts1],
            ["lesson-1", "Random error", ts2],
            ["lesson-1", "Random error", ts3],
        ],
    })

    result = await _discover_temporal_patterns(db, {"max_temporal_cv": 0.30})
    assert len(result) == 0


@pytest.mark.asyncio
async def test_temporal_requires_minimum_instances():
    """Requires at least min_temporal_instances occurrences."""
    from campy.brain.brainstem.sweep_patterns import _discover_temporal_patterns

    base = datetime(2026, 5, 20, 8, 0, 0, tzinfo=timezone.utc)
    db = _make_db(rows_by_query={
        "CONTAINS_LESSON": [
            ["lesson-1", "Error", base],
            ["lesson-1", "Error", base + timedelta(hours=8)],
        ],
    })

    result = await _discover_temporal_patterns(db, {"min_temporal_instances": 3})
    assert len(result) == 0


@pytest.mark.asyncio
async def test_temporal_empty_graph_no_error():
    """Empty graph produces empty list, not an error."""
    from campy.brain.brainstem.sweep_patterns import _discover_temporal_patterns
    db = _make_db()
    result = await _discover_temporal_patterns(db, {})
    assert result == []


# ---------------------------------------------------------------------------
# _discover_sequence_patterns
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sequence_finds_repeated_failure_chain():
    """Detects a pattern when the same action chain precedes failure N+ times."""
    from campy.brain.brainstem.sweep_patterns import _discover_sequence_patterns
    from unittest.mock import patch

    db = _make_db(rows_by_query={
        "NEXT_STEP": [
            ["git pull origin main", "resolve merge conflict", "git reset --hard", "step-1", -0.8],
            ["git pull origin main", "resolve merge conflict", "git reset --hard", "step-2", -0.7],
            ["git pull origin main", "resolve merge conflict", "git reset --hard", "step-3", -0.9],
        ],
    })

    mock_embedding = [0.5] * 384
    with patch("campy.brain.brainstem.sweep_patterns.emb.embed_batch",
               return_value=[mock_embedding] * 3):
        result = await _discover_sequence_patterns(db, {})

    assert len(result) == 1
    assert result[0]["type"] == "sequence"
    assert result[0]["node_type"] == "Procedure"
    assert result[0]["node_id"] is None
    assert result[0]["instance_count"] == 3


@pytest.mark.asyncio
async def test_sequence_rejects_insufficient_instances():
    """Requires at least min_sequence_instances matching chains."""
    from campy.brain.brainstem.sweep_patterns import _discover_sequence_patterns
    from unittest.mock import patch

    db = _make_db(rows_by_query={
        "NEXT_STEP": [
            ["step a", "step b", "fail", "s1", -0.5],
            ["step a", "step b", "fail", "s2", -0.6],
        ],
    })

    mock_embedding = [0.5] * 384
    with patch("campy.brain.brainstem.sweep_patterns.emb.embed_batch",
               return_value=[mock_embedding] * 2):
        result = await _discover_sequence_patterns(db, {"min_sequence_instances": 3})

    assert len(result) == 0


@pytest.mark.asyncio
async def test_sequence_empty_graph():
    """Empty graph produces no sequence candidates."""
    from campy.brain.brainstem.sweep_patterns import _discover_sequence_patterns
    db = _make_db()
    result = await _discover_sequence_patterns(db, {})
    assert result == []


# ---------------------------------------------------------------------------
# _discover_frequency_patterns
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_frequency_detects_increasing_trend():
    """Detects Lessons with increasing occurrence count across sessions."""
    from campy.brain.brainstem.sweep_patterns import _discover_frequency_patterns

    base = datetime(2026, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
    db = _make_db(rows_by_query={
        "CONTAINS_LESSON": [
            ["lesson-1", "Build failure in CI", "s1", base, 1],
            ["lesson-1", "Build failure in CI", "s2", base + timedelta(days=1), 2],
            ["lesson-1", "Build failure in CI", "s3", base + timedelta(days=2), 3],
            ["lesson-1", "Build failure in CI", "s4", base + timedelta(days=3), 5],
        ],
    })

    result = await _discover_frequency_patterns(db, {})
    assert len(result) == 1
    assert result[0]["type"] == "frequency"
    assert result[0]["node_id"] == "lesson-1"
    assert result[0]["slope"] > 0


@pytest.mark.asyncio
async def test_frequency_ignores_decreasing_trend():
    """Does not flag Lessons with decreasing occurrence rate."""
    from campy.brain.brainstem.sweep_patterns import _discover_frequency_patterns

    base = datetime(2026, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
    db = _make_db(rows_by_query={
        "CONTAINS_LESSON": [
            ["lesson-1", "Error", "s1", base, 5],
            ["lesson-1", "Error", "s2", base + timedelta(days=1), 3],
            ["lesson-1", "Error", "s3", base + timedelta(days=2), 2],
            ["lesson-1", "Error", "s4", base + timedelta(days=3), 1],
        ],
    })

    result = await _discover_frequency_patterns(db, {})
    assert len(result) == 0


@pytest.mark.asyncio
async def test_frequency_requires_minimum_sessions():
    """Needs at least min_frequency_sessions to detect a trend."""
    from campy.brain.brainstem.sweep_patterns import _discover_frequency_patterns

    base = datetime(2026, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
    db = _make_db(rows_by_query={
        "CONTAINS_LESSON": [
            ["lesson-1", "Error", "s1", base, 1],
            ["lesson-1", "Error", "s2", base + timedelta(days=1), 2],
        ],
    })

    result = await _discover_frequency_patterns(db, {"min_frequency_sessions": 4})
    assert len(result) == 0


@pytest.mark.asyncio
async def test_frequency_empty_graph():
    """Empty graph produces no candidates."""
    from campy.brain.brainstem.sweep_patterns import _discover_frequency_patterns
    db = _make_db()
    result = await _discover_frequency_patterns(db, {})
    assert result == []


# ---------------------------------------------------------------------------
# _deduplicate_candidates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dedup_removes_existing_patterns():
    """Candidates with patterns already in the graph are removed."""
    from campy.brain.brainstem.sweep_patterns import _deduplicate_candidates

    db = _make_db(rows_by_query={
        "Lesson": [["docker|container"]],
        "Procedure": [],
    })

    candidates = [
        {"proposed_trigger_pattern": "docker|container", "type": "temporal"},
        {"proposed_trigger_pattern": "aws|sso|token", "type": "temporal"},
    ]

    result = await _deduplicate_candidates(db, candidates)
    assert len(result) == 1
    assert result[0]["proposed_trigger_pattern"] == "aws|sso|token"


@pytest.mark.asyncio
async def test_dedup_keeps_all_when_no_existing():
    """All candidates pass through when no existing triggers."""
    from campy.brain.brainstem.sweep_patterns import _deduplicate_candidates

    db = _make_db()
    candidates = [
        {"proposed_trigger_pattern": "pattern-a", "type": "temporal"},
        {"proposed_trigger_pattern": "pattern-b", "type": "sequence"},
    ]

    result = await _deduplicate_candidates(db, candidates)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# _validate_candidates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validate_no_llm_accepts_all_as_low_confidence():
    """Without LLM, all candidates are accepted with confidence_low=True."""
    from campy.brain.brainstem.sweep_patterns import _validate_candidates

    candidates = [
        {"type": "temporal", "node_text": "test", "evidence": "ev"},
    ]

    validated, errors = await _validate_candidates(candidates, llm_client=None)
    assert len(validated) == 1
    assert validated[0]["confidence_low"] is True
    assert errors == 0


@pytest.mark.asyncio
async def test_validate_llm_filters_invalid():
    """LLM can reject candidates by returning valid=false."""
    from campy.brain.brainstem.sweep_patterns import _validate_candidates

    candidates = [
        {"type": "temporal", "node_text": "real", "evidence": "solid",
         "proposed_trigger_pattern": "real|pattern"},
        {"type": "frequency", "node_text": "noise", "evidence": "weak",
         "proposed_trigger_pattern": "noise"},
    ]

    response = json.dumps([
        {"index": 0, "valid": True, "confidence": 0.85, "reason": "Clear pattern"},
        {"index": 1, "valid": False, "confidence": 0.3, "reason": "Too noisy"},
    ])
    llm = _make_llm(response)

    validated, errors = await _validate_candidates(candidates, llm)
    assert len(validated) == 1
    assert validated[0]["node_text"] == "real"
    assert errors == 0


@pytest.mark.asyncio
async def test_validate_empty_candidates():
    """Empty candidate list returns empty result."""
    from campy.brain.brainstem.sweep_patterns import _validate_candidates

    validated, errors = await _validate_candidates([], llm_client=None)
    assert len(validated) == 0
    assert errors == 0


# ---------------------------------------------------------------------------
# _write_trigger_metadata
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_trigger_updates_existing_lesson():
    """Writes trigger metadata to an existing Lesson node."""
    from campy.brain.brainstem.sweep_patterns import _write_trigger_metadata

    db = _make_db()
    candidates = [{
        "type": "temporal",
        "node_type": "Lesson",
        "node_id": "lesson-abc",
        "node_text": "SSO expired",
        "proposed_trigger_pattern": "SSO|expired|token",
        "proposed_hook_type": "PostToolUse",
        "proposed_tool": "Bash",
        "confidence_low": False,
        "validated": True,
        "validation_confidence": 0.85,
    }]

    written, errors = await _write_trigger_metadata(db, {}, candidates)
    assert written == 1
    assert errors == 0
    assert any("trigger_pattern" in w["q"] and "Lesson" in w["q"] for w in db.written)


@pytest.mark.asyncio
async def test_write_trigger_creates_new_procedure():
    """Creates a new Procedure node for sequence pattern candidates."""
    from campy.brain.brainstem.sweep_patterns import _write_trigger_metadata
    from unittest.mock import patch

    db = _make_db()
    candidates = [{
        "type": "sequence",
        "node_type": "Procedure",
        "node_id": None,
        "node_text": "git pull -> merge conflict -> reset",
        "steps": ["git pull", "merge conflict", "reset --hard"],
        "proposed_trigger_pattern": "git|pull|merge|conflict",
        "proposed_hook_type": "PreToolUse",
        "proposed_tool": "",
        "evidence": "3 occurrences",
        "confidence_low": False,
        "validated": True,
        "validation_confidence": 0.80,
    }]

    with patch("campy.brain.brainstem.sweep_patterns.emb.embed",
               return_value=[0.1] * 384):
        written, errors = await _write_trigger_metadata(db, {}, candidates)

    assert written == 1
    assert errors == 0
    create_write = next(w for w in db.written if "CREATE" in w["q"] and "Procedure" in w["q"])
    assert create_write["p"]["trigger_pattern"] == "git|pull|merge|conflict"
    assert create_write["p"]["trigger_hook_type"] == "PreToolUse"


@pytest.mark.asyncio
async def test_write_trigger_skips_empty_pattern():
    """Candidates with empty trigger patterns are skipped."""
    from campy.brain.brainstem.sweep_patterns import _write_trigger_metadata

    db = _make_db()
    candidates = [{
        "type": "temporal",
        "node_type": "Lesson",
        "node_id": "lesson-xyz",
        "proposed_trigger_pattern": "",
        "proposed_hook_type": "PostToolUse",
        "proposed_tool": "",
    }]

    written, errors = await _write_trigger_metadata(db, {}, candidates)
    assert written == 0
    assert errors == 0
