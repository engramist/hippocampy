"""
tests/test_llm_routing.py — B16: Task-Based Model Routing

Verifies that create_llm_client_for_step() correctly resolves:
- Default (no override) → uses global [llm] config
- Step-specific override → uses merged config (override wins for present keys)
- Partial override → inherits missing keys from global block
- Unknown step name → falls back to global config
- Nested step dicts don't bleed into each other
"""

import pytest
from unittest.mock import MagicMock, patch

from campy.brain.llm.provider import create_llm_client_for_step, LLMClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BASE_CONFIG = {
    "llm": {
        "provider":  "ollama",
        "model":     "qwen2.5:3b",
        "base_url":  "http://localhost:11434/v1",
    }
}

OVERRIDE_CONFIG = {
    "llm": {
        "provider":  "ollama",
        "model":     "qwen2.5:3b",
        "base_url":  "http://localhost:11434/v1",
        "step6_arbitration": {
            "provider": "anthropic",
            "model":    "claude-sonnet-4-6",
        },
        "step2_gist": {
            "model": "qwen2.5:7b",
            # provider / base_url inherited from global
        },
        "quest_purpose": {
            "provider": "openai",
            "model":    "gpt-4.1-mini",
        },
    }
}


def _mock_openai_client(provider, model, base_url=None, api_key=None):
    """Return a mock OpenAI client with a predictable identity."""
    mock = MagicMock()
    mock._provider = provider
    mock._model = model
    mock._base_url = base_url
    return mock


# ---------------------------------------------------------------------------
# Tests: no override configured
# ---------------------------------------------------------------------------

class TestNoOverride:
    def test_unknown_step_returns_default(self):
        """An unrecognised step name falls back to the global provider."""
        with patch("campy.brain.llm.provider.create_llm_client") as mock_factory:
            mock_factory.return_value = MagicMock(spec=LLMClient)
            result = create_llm_client_for_step(BASE_CONFIG, "step_does_not_exist")
            assert result is not None
            # factory called once with global-only llm config
            called_cfg = mock_factory.call_args[0][0]
            assert called_cfg["llm"]["provider"] == "ollama"
            assert called_cfg["llm"]["model"] == "qwen2.5:3b"

    def test_step2_no_override_uses_global(self):
        with patch("campy.brain.llm.provider.create_llm_client") as mock_factory:
            mock_factory.return_value = MagicMock(spec=LLMClient)
            create_llm_client_for_step(BASE_CONFIG, "step2_gist")
            called_cfg = mock_factory.call_args[0][0]
            assert called_cfg["llm"]["model"] == "qwen2.5:3b"

    def test_step6_no_override_uses_global(self):
        with patch("campy.brain.llm.provider.create_llm_client") as mock_factory:
            mock_factory.return_value = MagicMock(spec=LLMClient)
            create_llm_client_for_step(BASE_CONFIG, "step6_arbitration")
            called_cfg = mock_factory.call_args[0][0]
            assert called_cfg["llm"]["provider"] == "ollama"


# ---------------------------------------------------------------------------
# Tests: step-specific override
# ---------------------------------------------------------------------------

class TestStepOverride:
    def test_step6_uses_override_provider_and_model(self):
        """step6_arbitration override replaces provider + model."""
        with patch("campy.brain.llm.provider.create_llm_client") as mock_factory:
            mock_factory.return_value = MagicMock(spec=LLMClient)
            create_llm_client_for_step(OVERRIDE_CONFIG, "step6_arbitration")
            called_cfg = mock_factory.call_args[0][0]
            assert called_cfg["llm"]["provider"] == "anthropic"
            assert called_cfg["llm"]["model"] == "claude-sonnet-4-6"

    def test_step2_partial_override_inherits_global_provider(self):
        """step2_gist only overrides model; provider/base_url inherited from global."""
        with patch("campy.brain.llm.provider.create_llm_client") as mock_factory:
            mock_factory.return_value = MagicMock(spec=LLMClient)
            create_llm_client_for_step(OVERRIDE_CONFIG, "step2_gist")
            called_cfg = mock_factory.call_args[0][0]
            assert called_cfg["llm"]["model"] == "qwen2.5:7b"      # overridden
            assert called_cfg["llm"]["provider"] == "ollama"        # inherited
            assert called_cfg["llm"]["base_url"] == "http://localhost:11434/v1"  # inherited

    def test_step3b_no_override_uses_global(self):
        """step3b_relations has no override in OVERRIDE_CONFIG → global falls through."""
        with patch("campy.brain.llm.provider.create_llm_client") as mock_factory:
            mock_factory.return_value = MagicMock(spec=LLMClient)
            create_llm_client_for_step(OVERRIDE_CONFIG, "step3b_relations")
            called_cfg = mock_factory.call_args[0][0]
            assert called_cfg["llm"]["provider"] == "ollama"
            assert called_cfg["llm"]["model"] == "qwen2.5:3b"

    def test_quest_purpose_override(self):
        with patch("campy.brain.llm.provider.create_llm_client") as mock_factory:
            mock_factory.return_value = MagicMock(spec=LLMClient)
            create_llm_client_for_step(OVERRIDE_CONFIG, "quest_purpose")
            called_cfg = mock_factory.call_args[0][0]
            assert called_cfg["llm"]["provider"] == "openai"
            assert called_cfg["llm"]["model"] == "gpt-4.1-mini"


# ---------------------------------------------------------------------------
# Tests: no nested step dicts bleed into sibling steps
# ---------------------------------------------------------------------------

class TestIsolation:
    def test_step6_override_does_not_bleed_to_step2(self):
        """After resolving step6, config passed for step2 should not contain anthropic."""
        with patch("campy.brain.llm.provider.create_llm_client") as mock_factory:
            mock_factory.return_value = MagicMock(spec=LLMClient)
            create_llm_client_for_step(OVERRIDE_CONFIG, "step2_gist")
            called_cfg = mock_factory.call_args[0][0]
            # Should NOT have anthropic, should have ollama
            assert called_cfg["llm"]["provider"] == "ollama"
            # No nested step dicts should survive in the merged llm config
            assert "step6_arbitration" not in called_cfg["llm"]
            assert "quest_purpose" not in called_cfg["llm"]

    def test_merged_config_has_no_nested_dicts(self):
        """The resolved llm block should be flat (no sub-dicts)."""
        with patch("campy.brain.llm.provider.create_llm_client") as mock_factory:
            mock_factory.return_value = MagicMock(spec=LLMClient)
            create_llm_client_for_step(OVERRIDE_CONFIG, "step6_arbitration")
            called_cfg = mock_factory.call_args[0][0]
            for v in called_cfg["llm"].values():
                assert not isinstance(v, dict), f"Nested dict found: {v}"

    def test_original_config_not_mutated(self):
        """create_llm_client_for_step must not mutate the config dict it receives."""
        import copy
        original = copy.deepcopy(OVERRIDE_CONFIG)
        with patch("campy.brain.llm.provider.create_llm_client"):
            create_llm_client_for_step(OVERRIDE_CONFIG, "step6_arbitration")
        assert OVERRIDE_CONFIG == original, "Config was mutated!"


# ---------------------------------------------------------------------------
# Tests: None propagation (factory returns None)
# ---------------------------------------------------------------------------

class TestNonePropagation:
    def test_returns_none_when_factory_returns_none(self):
        """If the underlying factory can't init the provider, None is returned."""
        with patch("campy.brain.llm.provider.create_llm_client", return_value=None):
            result = create_llm_client_for_step(BASE_CONFIG, "step6_arbitration")
            assert result is None

    def test_returns_none_for_override_when_factory_returns_none(self):
        """Even with a valid override config, None propagates if provider unavailable."""
        with patch("campy.brain.llm.provider.create_llm_client", return_value=None):
            result = create_llm_client_for_step(OVERRIDE_CONFIG, "step6_arbitration")
            assert result is None
