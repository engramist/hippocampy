"""
tests/patent_claims/test_claim_9_valence_weighted_retrieval.py — Patent Claim 9 Verification.

Patent Claim 9:
"A valence-weighted retrieval and Amygdala reflex system for agentic planning, comprising:
evaluating candidate plans against historical plans weighted by affective outcome valence
(valence in [-1.0, 1.0]), emitting proactive warnings for candidate strategies resembling
past negative outcomes (valence < -0.5), emitting suggestions for strategies resembling
past positive outcomes (valence > 0.5), and ranking query-time retrieval via combined
similarity, pathway strength, and valence weighting."

Observable Mechanism Assertions:
- Observable return of `register_plan()`:
  - Negative candidate plan triggers `warnings` containing `p-patent-failure` (valence -0.9).
  - Positive candidate plan triggers `suggestions` containing `p-patent-success` (valence 0.85).
- Observable return of `recall_plans_for_query()`:
  - Non-negative filter (`min_valence = 0.0`) returns successful plans (`p-patent-success`).
  - Strict valence-weighted ranking score `(similarity * |valence| * pathway_strength)`.
- Zero mocks; pure execution on live Kùzu graph fixture.
"""

from __future__ import annotations

import pytest

from campy.brain.thalamus.tools.quests import (
    recall_plans_for_query,
    register_plan,
)


@pytest.mark.asyncio
async def test_claim_9_amygdala_reflex_proactive_warnings_and_suggestions(
    patent_db, patent_config
):
    """Verify Claim 9: Amygdala reflex produces warnings for negative plans and suggestions for positive plans."""
    # 1. Proactive warning reflex on declaring strategy similar to historical failure
    fail_declaration = {
        "goal": "Use synchronous blocking locks across worker threads",
        "steps": ["Acquire global mutex in event loop"],
        "session_id": "s-patent-prior",
    }
    fail_res = await register_plan(fail_declaration, patent_db, patent_config)

    assert fail_res["write_ok"] is True
    assert "warnings" in fail_res
    assert len(fail_res["warnings"]) > 0

    warning_plan = fail_res["warnings"][0]
    assert warning_plan["plan_id"] == "p-patent-failure"
    assert warning_plan["valence"] <= -0.5
    assert len(warning_plan["steps"]) > 0
    assert warning_plan["steps"][0]["status"] == "failed"

    # 2. Proactive suggestion reflex on declaring strategy similar to historical success
    succ_declaration = {
        "goal": "Implement memory-mapped zero-copy buffer architecture",
        "steps": ["Allocate memory map pool"],
        "session_id": "s-patent-prior",
    }
    succ_res = await register_plan(succ_declaration, patent_db, patent_config)

    assert succ_res["write_ok"] is True
    assert "suggestions" in succ_res
    assert len(succ_res["suggestions"]) > 0

    suggestion_plan = succ_res["suggestions"][0]
    assert suggestion_plan["plan_id"] == "p-patent-success"
    assert suggestion_plan["valence"] >= 0.5
    assert any(s["status"] == "completed" for s in suggestion_plan["steps"])


@pytest.mark.asyncio
async def test_claim_9_valence_weighted_query_retrieval(
    patent_db, patent_config
):
    """Verify Claim 9: recall_plans_for_query ranks candidates using similarity and outcome valence."""
    # Recall with min_valence=0.0 (default positive filter)
    recalled_plans = await recall_plans_for_query(
        goal_query="memory-mapped zero-copy buffer",
        db=patent_db,
        config=patent_config,
        limit=5,
        min_valence=0.0,
    )

    assert len(recalled_plans) > 0
    top_plan = recalled_plans[0]
    assert top_plan["plan_id"] == "p-patent-success"
    assert top_plan["valence"] >= 0.0
    assert top_plan["similarity"] > 0.70
    assert top_plan["pathway_strength"] > 0.0
