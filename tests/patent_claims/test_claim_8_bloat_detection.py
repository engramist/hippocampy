"""
tests/patent_claims/test_claim_8_bloat_detection.py — Patent Claim 8 Verification.

Patent Claim 8:
"A context window bloat detection method in an autonomous memory agent, comprising:
tracking cumulative token consumption against a model-specific context window capacity,
evaluating a deterministic utilization threshold (BLOAT_WARNING_THRESHOLD = 0.75),
and generating proactive natural-language boundary alerts when utilization exceeds the
threshold to prompt cross-session handoff before out-of-memory degradation."

Observable Mechanism Assertions:
- Observable return of `check_context_health()`:
  - For bloated session `s-patent-active` (utilization 100,000 / 128,000 = 78.1% > 75%):
    - Non-None warning string returned.
    - String reports exact utilization percentage (78%) and recommends fresh conversation.
  - For healthy fresh session `s-patent-fresh` (utilization 500 / 128,000 = 0.4% <= 75%):
    - Returns None (zero false positives).
- Zero mocks; pure execution on live Kùzu graph fixture.
"""

from __future__ import annotations

import pytest

from campy.brain.thalamus.working_memory import check_context_health


def test_claim_8_bloat_warning_threshold_trigger(patent_db):
    """Verify Claim 8: check_context_health returns warning string when utilization > 75%."""
    # 1. Bloated session evaluation (> 75%)
    bloat_session_id = "s-patent-active"
    warning = check_context_health(patent_db, bloat_session_id)

    assert warning is not None
    assert isinstance(warning, str)
    assert "78%" in warning
    assert "100000/128000" in warning
    assert "fresh conversation" in warning.lower()

    # 2. Healthy fresh session evaluation (<= 75%)
    fresh_session_id = "s-patent-fresh"
    healthy_status = check_context_health(patent_db, fresh_session_id)

    assert healthy_status is None
