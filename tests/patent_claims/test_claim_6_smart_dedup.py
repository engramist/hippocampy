"""
tests/patent_claims/test_claim_6_smart_dedup.py — Patent Claim 6 Verification.

Patent Claim 6:
"A method for context-aware retrieval deduplication, comprising: comparing retrieved
candidate memory nodes against an active set of loaded nodes in a session context window,
and softly demoting already-loaded candidates by a deterministic demotion factor
(DEDUP_DEMOTION_FACTOR) rather than omitting them, tagging candidates with context state
flags while allowing higher-ranking fresh candidates to occupy top injection slots."

Observable Mechanism Assertions:
- Observable return of `deduplicate_results()`:
  - Already-loaded items flagged with `already_in_context == True`.
  - Unloaded items flagged with `already_in_context == False`.
  - Zero omissions: result count remains identical before and after deduplication.
  - Score transformation: `_rank` demoted by exactly `DEDUP_DEMOTION_FACTOR` (0.3).
  - Rank inversion: lower-scoring fresh candidate promoted ahead of demoted candidate.
- Zero mocks.
"""

from __future__ import annotations

import pytest

from campy.brain.thalamus.working_memory import (
    DEDUP_DEMOTION_FACTOR,
    deduplicate_results,
)


def test_claim_6_deduplicate_results_demotion_without_omission():
    """Verify Claim 6: deduplicate_results demotes loaded candidates without dropping them."""
    loaded_ids = {"node-in-context"}

    # Initial candidate set where the already-loaded item has a higher initial rank
    initial_candidates = [
        {
            "node_id": "node-in-context",
            "_rank": 0.90,
            "text_raw": "Architecture decision regarding index storage",
        },
        {
            "node_id": "node-fresh",
            "_rank": 0.40,
            "text_raw": "Newly relevant lesson regarding socket timeouts",
        },
    ]

    deduped = deduplicate_results(initial_candidates, loaded_ids)

    # 1. Zero omission assertion
    assert len(deduped) == 2

    loaded_item = next(r for r in deduped if r["node_id"] == "node-in-context")
    fresh_item = next(r for r in deduped if r["node_id"] == "node-fresh")

    # 2. Context status tagging
    assert loaded_item["already_in_context"] is True
    assert fresh_item["already_in_context"] is False

    # 3. Soft demotion score assertion
    expected_demoted_rank = 0.90 * DEDUP_DEMOTION_FACTOR  # 0.90 * 0.3 = 0.27
    assert loaded_item["_rank"] == pytest.approx(expected_demoted_rank)
    assert fresh_item["_rank"] == pytest.approx(0.40)

    # 4. Rank reordering assertion: Fresh node (0.40) outranks demoted node (0.27)
    assert deduped[0]["node_id"] == "node-fresh"
    assert deduped[1]["node_id"] == "node-in-context"
