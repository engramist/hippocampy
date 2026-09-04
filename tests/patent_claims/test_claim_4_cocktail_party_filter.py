"""
tests/patent_claims/test_claim_4_cocktail_party_filter.py — Patent Claim 4 Verification.

Patent Claim 4:
"A selective attention filter (Cocktail Party Effect) and emotional salience multiplier,
comprising a three-tier confidence gate partitioning extracted signals into noise rejection,
tentative low-confidence retention, and confirmed hard-lock retention, augmented by an
affective salience multiplier dynamically boosting encoding strength based on emotional
signals."

Observable Mechanism Assertions:
- Observable return of `classify_artifact()` across noise (<0.60), tentative (0.60–0.90),
  and hard-lock (>0.90) thresholds.
- Assistant turn safety cap enforcing `confidence <= ASSISTANT_CAP` (0.85) to prevent
  hallucination poisoning.
- Observable scaling of `compute_salience_multiplier()` from 1.0 (neutral) to >1.3 (frustration/urgency).
- Zero mocks; pure execution on live heuristic pattern matching rules.
"""

from __future__ import annotations

import pytest

from campy.brain.temporal_lobe.loop.step4_pattern import (
    ASSISTANT_CAP,
    HARD_LOCK,
    NOISE_FLOOR,
    classify_artifact,
    compute_salience_multiplier,
)


def test_claim_4_confidence_gate_three_tier_partitioning():
    """Verify Claim 4: Confidence gate partitions signals into noise, low-confidence, and hard-lock."""
    # 1. Noise rejection (< 0.60)
    noise_res = classify_artifact(
        "just a passing conversational filler",
        gist_class=None,
        schema_org_type=None,
    )
    assert noise_res["should_proceed"] is False
    assert noise_res["confidence"] < NOISE_FLOOR
    assert noise_res["confidence_low"] is True

    # 2. Tentative low-confidence retention (0.60 <= conf < 0.90)
    # Using single-hit requirement signal with Category gist prior
    tentative_res = classify_artifact(
        "We require an automated health check monitor.",
        gist_class="Category",
        schema_org_type="DefinedTerm",
        entity_text="health check monitor",
        role="user",
    )
    assert tentative_res["should_proceed"] is True
    assert tentative_res["confidence_low"] is True
    assert NOISE_FLOOR <= tentative_res["confidence"] < HARD_LOCK

    # 3. Confirmed hard-lock retention (> 0.90)
    # Multi-hit keyword signals aligned with gist prior
    confirmed_res = classify_artifact(
        "We decided, chose, and finalized the storage engine architecture.",
        gist_class="PhysicalThing",
        schema_org_type="Product",
        entity_text="storage engine architecture",
        role="user",
    )
    assert confirmed_res["should_proceed"] is True
    assert confirmed_res["confidence_low"] is False
    assert confirmed_res["confidence"] >= HARD_LOCK
    assert confirmed_res["artifact_type"] == "decision"


def test_claim_4_assistant_safety_cap():
    """Verify Claim 4: Assistant turns are capped at ASSISTANT_CAP to prevent hallucination poisoning."""
    # Strong signals that would otherwise exceed 0.90 for a user
    asst_res = classify_artifact(
        "We decided, chose, and finalized the storage engine architecture.",
        gist_class="PhysicalThing",
        schema_org_type="Product",
        entity_text="storage engine architecture",
        role="assistant",
    )

    assert asst_res["should_proceed"] is True
    assert asst_res["confidence"] <= ASSISTANT_CAP
    assert asst_res["confidence_low"] is True


def test_claim_4_amygdala_salience_multiplier():
    """Verify Claim 4: Emotional language scales salience multiplier above 1.0."""
    neutral_text = "The migration finished at 10:00 AM."
    salience_neutral = compute_salience_multiplier(neutral_text)
    assert salience_neutral == 1.0

    frustrated_text = (
        "I told you for the third time, stop doing that! This is completely broken, damn it!"
    )
    salience_frustrated = compute_salience_multiplier(frustrated_text)
    assert salience_frustrated >= 1.3
    assert salience_frustrated <= 1.6
