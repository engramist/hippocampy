"""
B301 — outcome-sense polarity regression tests.

Covers: judgment-shaped failure signals (not count-reports), the >=2 margin
rule for mixed messages, the user-only role gate on auto outcome-sense, and
the valence_trigger audit trail on system-labeled Lessons.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from campy.brain.temporal_lobe.loop.step4_pattern import (
    infer_outcome_valence,
    infer_outcome_valence_detail,
)


# ---------------------------------------------------------------------------
# Task 5, bullet 1 — the actual observed failure case
# ---------------------------------------------------------------------------

def test_success_summary_with_failure_counts_never_reads_as_failure():
    text = (
        "✅ B290 Continuous Work State — COMPLETE & CERTIFIED\n"
        "192 passed, daemon healthy, all 9 B290 commits in place.\n"
        "17 failed + 12 errors in the sampled set were pre-existing; "
        "the only failures (4) are fixed."
    )
    assert infer_outcome_valence(text) in (None, 0.8)
    assert infer_outcome_valence(text) != -0.8


# ---------------------------------------------------------------------------
# Task 5, bullet 2 — judgment still detected
# ---------------------------------------------------------------------------

def test_that_broke_revert_it_is_failure():
    assert infer_outcome_valence("that broke the build, revert it") == -0.8


# ---------------------------------------------------------------------------
# Task 5, bullet 3 — subject-anchored "failed" vs. bare count mention
# ---------------------------------------------------------------------------

def test_the_deploy_failed_is_failure():
    assert infer_outcome_valence("the deploy failed") == -0.8


def test_bare_failed_count_alone_is_none():
    assert infer_outcome_valence("17 failed") is None


# ---------------------------------------------------------------------------
# Task 5, bullet 4 — margin rule
# ---------------------------------------------------------------------------

def test_one_success_one_failure_hit_is_ambiguous():
    # "approved" (success) vs "the test failed" (failure) — 1 vs 1 → None
    text = "approved, but the test failed"
    assert infer_outcome_valence(text) is None


# ---------------------------------------------------------------------------
# Task 5, bullet 6 — trigger audit on the detail variant
# ---------------------------------------------------------------------------

def test_detail_variant_returns_matched_signals():
    valence, signals = infer_outcome_valence_detail("that broke the build, revert it")
    assert valence == -0.8
    assert signals  # non-empty — records which pattern(s) fired


def test_detail_variant_empty_signals_when_none():
    valence, signals = infer_outcome_valence_detail("17 failed")
    assert valence is None
    assert signals == []


# ---------------------------------------------------------------------------
# Signal-list parity between step4_pattern.py and the _shared.py fallback copy
# ---------------------------------------------------------------------------

def _shared_fallback_signal_list(name: str):
    import ast
    import pathlib

    shared_src = pathlib.Path("campy/brain/thalamus/tools/_shared.py").read_text()
    tree = ast.parse(shared_src)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    return None


def test_shared_fallback_failure_signals_match_step4_pattern():
    fallback = _shared_fallback_signal_list("_FAILURE_SIGNALS")
    assert fallback is not None, "fallback _FAILURE_SIGNALS not found in _shared.py"

    from campy.brain.temporal_lobe.loop.step4_pattern import _FAILURE_SIGNALS

    assert fallback == _FAILURE_SIGNALS


def test_shared_fallback_success_signals_match_step4_pattern():
    fallback = _shared_fallback_signal_list("_SUCCESS_SIGNALS")
    assert fallback is not None, "fallback _SUCCESS_SIGNALS not found in _shared.py"

    from campy.brain.temporal_lobe.loop.step4_pattern import _SUCCESS_SIGNALS

    assert fallback == _SUCCESS_SIGNALS


# ---------------------------------------------------------------------------
# Task 5, bullet 5 — role gate: notify_turn only auto-reports outcome for
# user turns, never assistant turns.
# ---------------------------------------------------------------------------

class _EmptyResult:
    """Mirrors tests/adapters/test_claude_memory_capture.py's stub."""

    def has_next(self):
        return False


def _make_capture_db(written):
    mock_db = MagicMock()
    mock_db.execute = lambda *a, **k: _EmptyResult()
    mock_db.vector_search = lambda *a, **k: []

    async def capture_write(q, p=None):
        written.append((q, p or {}))

    mock_db.execute_write = capture_write
    return mock_db


async def _fake_route_session(*a, **k):
    from campy.brain.hippocampus.hippocampus import RoutingResult
    return RoutingResult("quest-1", 0.5, "semantic_s1", False, "tentative")


def _lesson_writes(written):
    return [(q, p) for q, p in written if "CREATE (l:Lesson" in q]


@pytest.mark.asyncio
async def test_assistant_role_does_not_auto_report_outcome(monkeypatch):
    from campy.brain.thalamus.tools import capture as capture_mod
    from campy.brain.hippocampus import hippocampus as hippocampus_mod

    monkeypatch.setattr(capture_mod.emb, "embed", lambda text, model_name=None: [0.1] * 384)
    monkeypatch.setattr(hippocampus_mod, "route_session", _fake_route_session)

    written = []
    mock_db = _make_capture_db(written)

    result = await capture_mod.notify_turn(
        {"role": "assistant", "content": "revert it, that broke", "session_id": "sess-outcome-1"},
        mock_db,
        {},
    )
    assert result["status"] == "ingested"
    assert _lesson_writes(written) == []


@pytest.mark.asyncio
async def test_user_role_does_auto_report_outcome(monkeypatch):
    from campy.brain.thalamus.tools import capture as capture_mod
    from campy.brain.hippocampus import hippocampus as hippocampus_mod

    monkeypatch.setattr(capture_mod.emb, "embed", lambda text, model_name=None: [0.1] * 384)
    monkeypatch.setattr(hippocampus_mod, "route_session", _fake_route_session)

    written = []
    mock_db = _make_capture_db(written)

    result = await capture_mod.notify_turn(
        {"role": "user", "content": "revert it, that broke", "session_id": "sess-outcome-2"},
        mock_db,
        {},
    )
    assert result["status"] == "ingested"
    lesson_writes = _lesson_writes(written)
    assert len(lesson_writes) == 1

    # Task 5, bullet 6 — trigger audit: the lesson text carries [valence_trigger:
    _, params = lesson_writes[0]
    assert "[valence_trigger:" in params["text_raw"]
