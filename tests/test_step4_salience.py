"""Tests for the Emotion sense (7th Cocktail Party sense) in Step 4."""
import pytest
from mcp_engine.loop.step4_pattern import compute_salience_multiplier


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
