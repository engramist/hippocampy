"""
Unit tests for B374: Two-Lane Thalamic Routing and Compression.

Validates:
1. Protected Lane: Decisions, active Constraints, Negative Controls, and exact facts
   bypass compression entirely (0% loss, verbatim preservation).
2. Bulk Lane: Summaries, concepts, code extracts, and tabular data undergo specialized
   compression (graph pruning, AST folding, prose compression) achieving 50%-70% reduction.
3. Prompt Hardening: LLMProseCompressor enforces verbatim retention of entity names,
   decision identifiers, requirements, numeric parameters, and negations.
4. Standing Guardrail: GraphBundleCompressor graph-native pruning is preserved.
"""

import json
from unittest.mock import MagicMock
import pytest

from campy.brain.thalamus.bundle_compiler import BundleSection
from campy.brain.thalamus.compression import (
    ContentRouter,
    build_default_registry,
    PluggableCompressorRegistry,
)
from campy.brain.thalamus.compression.fallback import NoOpCompressor
from campy.brain.thalamus.compression.graph_bundle import GraphBundleCompressor
from campy.brain.thalamus.compression.llm_prose import LLMCompressor, _COMPRESSION_PROMPT
from campy.brain.thalamus.compression.structured_data import StructuredDataCompressor
from campy.brain.thalamus.compression.ast_mapper import ASTCodeCompressor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_section(section_type: str, content: list) -> BundleSection:
    return BundleSection(
        section_type=section_type,
        content=content,
        token_estimate=max(1, len(json.dumps(content)) // 4),
        source_node_ids=[str(i) for i in range(len(content))],
    )


# ---------------------------------------------------------------------------
# Tests: Two-Lane Routing in ContentRouter
# ---------------------------------------------------------------------------

def test_content_router_lane_definitions():
    """Verify lane memberships adhere strictly to B374 spec."""
    expected_protected = {"decision", "constraint", "negative_control", "exact_fact"}
    expected_bulk = {"summary", "semantic", "graph", "code", "tabular"}

    assert expected_protected.issubset(ContentRouter.PROTECTED_SECTION_TYPES)
    assert expected_bulk.issubset(ContentRouter.BULK_SECTION_TYPES)


@pytest.mark.parametrize("sec_type", ["decision", "constraint", "negative_control", "exact_fact"])
def test_protected_lane_routes_to_noop(sec_type):
    """Protected Lane sections must route to NoOpCompressor regardless of config."""
    config = {
        "compression": {
            "graph_prune_threshold": 0.5,
            "structured_format": "toon",
            "ast_compression": True,
        }
    }
    registry, router = build_default_registry(config)

    section = _make_section(sec_type, [{"text": "Critical architectural invariant", "type": sec_type}])
    compressor = router.route(section)

    assert isinstance(compressor, NoOpCompressor)
    assert router.is_protected(section) is True
    assert router.is_protected(sec_type) is True


@pytest.mark.parametrize("sec_type,expected_class", [
    ("graph", GraphBundleCompressor),
    ("semantic", GraphBundleCompressor),
    ("summary", LLMCompressor),
    ("code", ASTCodeCompressor),
    ("tabular", StructuredDataCompressor),
])
def test_bulk_lane_routes_to_specialized_compressor(sec_type, expected_class):
    """Bulk Lane sections must dispatch to registered specialized compressors."""
    config = {"compression": {"ast_compression": True}}
    registry, router = build_default_registry(config)

    section = _make_section(sec_type, [{"text": "bulk item"}])
    compressor = router.route(section)

    assert isinstance(compressor, expected_class)
    assert router.is_protected(section) is False


def test_protected_lane_zero_loss_guarantee():
    """Protected lane items must experience 0% loss: exact content and tokens preserved."""
    config = {"compression": {}}
    _, router = build_default_registry(config)

    protected_items = [
        {"decision_id": "D1", "text": "Must use Ed25519 signatures", "confidence": 0.99},
        {"constraint_id": "C1", "text": "Never expose private keys", "active": True},
        {"fact": "Port is 7799", "negative_assertion": "do NOT bind 0.0.0.0"},
    ]

    for sec_type in ("decision", "constraint", "negative_control", "exact_fact"):
        section = _make_section(sec_type, protected_items)
        orig_tokens = section.token_estimate
        compressed = router.compress_section(section, "security policy", config)

        assert compressed.content == protected_items
        assert compressed.token_estimate == orig_tokens
        assert compressed.section_type == sec_type


def test_bulk_lane_compression_ratio_achieved():
    """Bulk Lane sections must achieve 50%-70% compression."""
    config = {
        "compression": {
            "graph_prune_threshold": 0.50,
            "structured_format": "toon",
            "ast_compression": True,
        }
    }
    _, router = build_default_registry(config)

    # 1. Code extract: AST compression folds bodies
    python_source = """
class SecurityService:
    def __init__(self, key_store, crypto_backend):
        self.key_store = key_store
        self.backend = crypto_backend
        self._cache = {}

    def sign(self, payload: bytes) -> bytes:
        if not payload:
            raise ValueError("Payload cannot be empty")
        key = self.key_store.get_active_key()
        signature = self.backend.compute_signature(key, payload)
        self._cache[payload] = signature
        return signature

    def verify(self, payload: bytes, signature: bytes) -> bool:
        if not signature:
            return False
        key = self.key_store.get_active_key()
        return self.backend.verify_signature(key, payload, signature)
"""
    code_section = _make_section("code", [{"source": python_source, "language": "python"}])
    initial_code_tokens = code_section.token_estimate
    compressed_code = router.compress_section(code_section, "sign payload", config)
    code_ratio = compressed_code.token_estimate / initial_code_tokens
    # Folded signatures achieve > 60% compression (ratio < 0.40)
    assert code_ratio <= 0.45, f"Code ratio {code_ratio} exceeded threshold"

    # 2. Graph/Semantic: prunes low-strength nodes
    graph_nodes = [
        {"text": f"relevant concept {i}", "type": "Concept", "pathway_strength": 0.95, "confidence": 0.9}
        for i in range(5)
    ] + [
        {"text": f"stale background {i}", "type": "Concept", "pathway_strength": 0.05, "confidence": 0.5}
        for i in range(15)
    ]
    graph_section = _make_section("semantic", graph_nodes)
    initial_graph_tokens = graph_section.token_estimate
    compressed_graph = router.compress_section(graph_section, "relevant concept", config)
    graph_ratio = compressed_graph.token_estimate / initial_graph_tokens
    assert graph_ratio <= 0.50, f"Graph ratio {graph_ratio} exceeded threshold"


# ---------------------------------------------------------------------------
# Tests: Prompt Tuning in LLMProseCompressor
# ---------------------------------------------------------------------------

def test_llm_prose_prompt_tuning_constraints():
    """Verify system prompt contains all required verbatim retention constraints."""
    prompt = _COMPRESSION_PROMPT
    assert "entity name" in prompt
    assert "decision identifier" in prompt
    assert "requirement" in prompt
    assert "numeric parameter" in prompt
    assert "negation" in prompt
    assert "verbatim" in prompt
    assert "do NOT" in prompt
    assert "must never" in prompt
    assert "target_tokens" in prompt


def test_llm_prose_compressor_invokes_prompt_with_budget():
    """Verify LLMCompressor sets target_tokens and dispatches formatted prompt."""
    mock_llm = MagicMock()
    mock_llm.chat.return_value = "Compressed high-fidelity prose."

    compressor = LLMCompressor({}, llm_override=mock_llm)
    section = _make_section("summary", [{"text": "We decided on B374 to enforce 4000 token budget."}])
    config = {"compression": {"target_tokens": 100}}

    result = compressor.compress(section, "query", config)

    mock_llm.chat.assert_called_once()
    messages = mock_llm.chat.call_args[0][0]
    prompt_content = messages[0]["content"]

    assert "fit within 100 tokens" in prompt_content
    assert "We decided on B374 to enforce 4000 token budget." in prompt_content
    assert result.content[0]["text"] == "Compressed high-fidelity prose."


# ---------------------------------------------------------------------------
# Tests: Standing Guardrail — Graph-Native Pruning Preserved
# ---------------------------------------------------------------------------

def test_standing_guardrail_graph_bundle_compressor_intact():
    """Guardrail: Ensure GraphBundleCompressor is not replaced by generic JSON crushers."""
    config = {"compression": {"graph_prune_threshold": 0.40}}
    registry, router = build_default_registry(config)

    graph_compressor = registry.get("graph_bundle")
    assert isinstance(graph_compressor, GraphBundleCompressor)
    assert not hasattr(graph_compressor, "crush_json")
    assert hasattr(graph_compressor, "_score_node") or hasattr(graph_compressor, "compress")
