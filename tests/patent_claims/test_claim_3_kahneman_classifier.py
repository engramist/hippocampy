"""
tests/patent_claims/test_claim_3_kahneman_classifier.py — Patent Claim 3 Verification.

Patent Claim 3:
"A hybrid cognitive classification system modeled on Kahneman dual-process theory,
comprising a rapid System 1 vector-centroid matcher executing without generative
language models for high-confidence inputs, and a deliberative System 2 classification
pathway activated exclusively for ambiguous inputs in a bounded intermediate confidence
interval, rejecting inputs below a defined noise floor."

Observable Mechanism Assertions:
- Observable return of `classify_concept()`:
  - System 1 fast path: `system == "1"`, `confidence >= SYSTEM1_THRESHOLD`, valid `gist_class`.
  - System 2 gray zone path: `system in ("2", "2_degraded")`, `confidence_low is True`.
  - Sub-floor noise path: `system == "noise"`, `gist_class is None`.
- Zero mocks; pure execution on live embedding model and centroids.
"""

from __future__ import annotations

import pytest

from campy.brain.temporal_lobe.loop.step2_gist import (
    NOISE_FLOOR,
    SYSTEM1_THRESHOLD,
    classify_concept,
)


def test_claim_3_kahneman_system_1_rapid_path(patent_config, patent_centroids):
    """Verify Claim 3: Strong prototypical concept triggers System 1 classification."""
    emb_model = patent_config["embeddings"]["model"]
    entity_text = "API keys"
    context_text = "We must never store API keys or credentials in source code."

    result = classify_concept(
        entity_text,
        emb_model,
        patent_centroids,
        llm_client=None,
        context=context_text,
    )

    assert result["system"] == "1"
    assert result["confidence"] >= SYSTEM1_THRESHOLD
    assert result["gist_class"] == "Restriction"
    assert "vector" in result
    assert len(result["vector"]) == 384


def test_claim_3_kahneman_gray_zone_system_2_degradation(
    patent_config, patent_centroids
):
    """Verify Claim 3: Ambiguous concept in the 0.18–0.50 range triggers System 2 pathway."""
    emb_model = patent_config["embeddings"]["model"]
    # Ambiguous term that lands in the intermediate zone (between 0.18 and 0.50)
    entity_text = "deploy the software system"

    result = classify_concept(
        entity_text,
        emb_model,
        patent_centroids,
        llm_client=None,
        context=entity_text,
    )

    # In the absence of an active LLM provider, System 2 degrades gracefully to preserve recall
    assert result["system"] in ("2", "2_degraded")
    assert result.get("confidence_low") is True
    assert NOISE_FLOOR <= result["confidence"] < SYSTEM1_THRESHOLD


def test_claim_3_kahneman_sub_floor_noise_rejection(
    patent_config, patent_centroids
):
    """Verify Claim 3: Text below the noise floor is deterministically marked as noise."""
    emb_model = patent_config["embeddings"]["model"]
    # Synthesized gibberish token yields sub-floor similarity (< 0.18)
    entity_text = "xyz123abc"

    result = classify_concept(
        entity_text,
        emb_model,
        patent_centroids,
        llm_client=None,
        context="",
    )

    assert result["system"] == "noise"
    assert result["confidence"] < NOISE_FLOOR
    assert result["gist_class"] is None
