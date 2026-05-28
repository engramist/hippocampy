"""Tests for the Emotion sense (7th Cocktail Party sense) in Step 4."""
import pytest
from campy.brain.temporal_lobe.loop.step4_pattern import compute_salience_multiplier


class TestComputeSalienceMultiplier:
    """Unit tests for compute_salience_multiplier()."""

    def test_neutral_text_returns_1(self):
        assert compute_salience_multiplier("ok sounds good") == 1.0

    def test_empty_string_returns_1(self):
        assert compute_salience_multiplier("") == 1.0

    def test_none_returns_1(self):
        assert compute_salience_multiplier(None) == 1.0

    def test_single_frustration_signal(self):
        result = compute_salience_multiplier("I told you not to do that")
        assert result == pytest.approx(1.15, abs=0.01)

    def test_single_excitement_signal(self):
        result = compute_salience_multiplier("I love it")
        assert result == pytest.approx(1.105, abs=0.01)

    def test_single_urgency_signal(self):
        result = compute_salience_multiplier("we need this ASAP")
        assert result == pytest.approx(1.12, abs=0.01)

    def test_multiple_frustration_signals_stack(self):
        result = compute_salience_multiplier(
            "No no, wrong again! I told you not to do that!"
        )
        assert result > 1.15

    def test_mixed_signals_combine(self):
        result = compute_salience_multiplier(
            "I told you this is critical and needs to be done ASAP!"
        )
        assert result > 1.3

    def test_caps_at_1_6(self):
        result = compute_salience_multiplier(
            "NO! Stop! I told you! This is broken and terrible! "
            "Wrong again! How many times! Damn! Ugh!"
        )
        assert result == pytest.approx(1.6, abs=0.01)

    def test_outcome_valence_contributes(self):
        result_with_failure = compute_salience_multiplier("that's wrong, revert it")
        result_neutral = compute_salience_multiplier("please update the config")
        assert result_with_failure > result_neutral

    def test_case_insensitive(self):
        result_lower = compute_salience_multiplier("i told you not to do that")
        result_upper = compute_salience_multiplier("I TOLD YOU NOT TO DO THAT")
        assert result_lower == result_upper


import inspect

from campy.brain.temporal_lobe.loop.step4_pattern import (
    classify_artifact,
    NOISE_FLOOR,
)


class TestConfidenceRescue:
    """Tests for the amygdala burn-in: emotional content rescues from noise floor."""

    def test_below_noise_floor_preserves_raw_confidence(self):
        """classify_artifact should preserve raw confidence even when below noise floor."""
        # Event gist class with no keyword signals → prior_conf=0.50 (below NOISE_FLOOR 0.60)
        # Uses neutral text with no action/decision/constraint/requirement signals
        result = classify_artifact(
            "the party happened yesterday",
            gist_class="Event",
            schema_org_type="Event",
            role="user",
        )
        assert result["should_proceed"] is False
        # Raw confidence should be preserved (not 0.0) for rescue evaluation
        # Event with no keyword signals gets prior_conf=0.50
        assert result["confidence"] > 0

    def test_no_gist_class_returns_zero_confidence(self):
        """No gist class → true noise, confidence 0.0, not rescuable."""
        result = classify_artifact(
            "I told you not to do that!",
            gist_class=None,
            schema_org_type=None,
            role="user",
        )
        assert result["confidence"] == 0.0
        assert result["should_proceed"] is False

    def test_salience_above_rescue_threshold(self):
        """Strongly emotional text produces salience >= 1.3."""
        from campy.brain.temporal_lobe.loop.step4_pattern import compute_salience_multiplier
        result = compute_salience_multiplier(
            "NO! I told you! Stop doing that! This is broken!"
        )
        assert result >= 1.3


class TestPathwayStrengthBoost:
    """Tests for salience multiplier effect on pathway_strength."""

    def test_store_concept_signature_accepts_salience(self):
        """Verify _store_concept accepts salience kwarg without error."""
        from campy.brain.temporal_lobe.loop.orchestrator import _store_concept
        sig = inspect.signature(_store_concept)
        assert "salience" in sig.parameters

    def test_salience_default_is_1(self):
        """Default salience should be 1.0 (no boost)."""
        from campy.brain.temporal_lobe.loop.orchestrator import _store_concept
        sig = inspect.signature(_store_concept)
        assert sig.parameters["salience"].default == 1.0
