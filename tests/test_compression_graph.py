# tests/test_compression_graph.py
import math
import pytest
from campy.brain.thalamus.bundle_compiler import BundleSection
from campy.brain.thalamus.compression.graph_bundle import GraphBundleCompressor, _cosine_similarity, _node_prefix


def _graph_section(nodes: list[dict]) -> BundleSection:
    return BundleSection(
        section_type="semantic",
        content=nodes,
        token_estimate=sum(len(str(n)) for n in nodes),
        source_node_ids=[n.get("text", "")[:20] for n in nodes],
    )


def _make_nodes(n: int, high_strength: int = 1) -> list[dict]:
    """Create n nodes; first `high_strength` have pathway_strength=0.95, rest 0.05."""
    nodes = []
    for i in range(n):
        nodes.append({
            "text": f"node {i}",
            "type": "Concept" if i % 2 == 0 else "Decision",
            "pathway_strength": 0.95 if i < high_strength else 0.05,
            "confidence": 0.9,
        })
    return nodes


def test_cosine_similarity_identical_vectors():
    v = [1.0, 0.0, 0.0]
    assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6


def test_cosine_similarity_orthogonal_vectors():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(_cosine_similarity(a, b)) < 1e-6


def test_node_prefix_mapping():
    assert _node_prefix("Concept") == "C"
    assert _node_prefix("Decision") == "D"
    assert _node_prefix("Lesson") == "L"
    assert _node_prefix("Unknown") == "?"


def test_prune_drops_low_strength_nodes():
    nodes = _make_nodes(10, high_strength=3)
    section = _graph_section(nodes)
    compressor = GraphBundleCompressor({"compression": {"graph_prune_threshold": 0.5}})
    result = compressor.compress(section, "test query", {})
    # Compact text should mention high-strength nodes
    text = result.content[0]["compact"] if result.content else ""
    assert "node 0" in text or "node 1" in text or "node 2" in text


def test_empty_section_returns_unchanged():
    section = _graph_section([])
    compressor = GraphBundleCompressor({})
    result = compressor.compress(section, "", {})
    assert result.content == []


def test_compact_notation_contains_type_prefix():
    nodes = [{"text": "use JWT", "type": "Decision", "pathway_strength": 0.9, "confidence": 0.9}]
    section = _graph_section(nodes)
    compressor = GraphBundleCompressor({"compression": {"graph_prune_threshold": 0.0}})
    result = compressor.compress(section, "auth", {})
    text = result.content[0]["compact"] if result.content else ""
    assert "D:" in text


def test_token_estimate_reduced_after_pruning():
    nodes = _make_nodes(20, high_strength=4)
    section = _graph_section(nodes)
    compressor = GraphBundleCompressor({"compression": {"graph_prune_threshold": 0.5}})
    result = compressor.compress(section, "test", {})
    assert result.token_estimate < section.token_estimate


def test_protected_constraint_survives_aggressive_pruning():
    """A hard Constraint must never be pruned, even with a 1.0 threshold and a
    query it has no similarity to and zero pathway strength."""
    nodes = [
        {"text": f"irrelevant concept {i}", "type": "Concept",
         "pathway_strength": 0.9, "confidence": 0.9}
        for i in range(10)
    ]
    nodes.append({
        "text": "never store secrets in the repo",
        "type": "Constraint",
        "pathway_strength": 0.0,   # isolated / weak — would lose on score alone
        "confidence": 0.5,
    })
    section = _graph_section(nodes)
    # threshold 1.0 would prune everything that isn't protected
    compressor = GraphBundleCompressor({"compression": {"graph_prune_threshold": 1.0}})
    result = compressor.compress(section, "completely unrelated query", {})
    text = result.content[0]["compact"] if result.content else ""
    assert "never store secrets in the repo" in text
    assert "K:" in text  # Constraint prefix


def test_locked_decision_survives_but_ordinary_decision_prunes():
    """Decision with confidence>=0.95 is protected; a 0.9 decision is not."""
    nodes = [
        {"text": "locked: use JWT", "type": "Decision",
         "pathway_strength": 0.0, "confidence": 0.97},
        {"text": "tentative: maybe sessions", "type": "Decision",
         "pathway_strength": 0.0, "confidence": 0.90},
    ] + [
        {"text": f"filler {i}", "type": "Concept", "pathway_strength": 0.99, "confidence": 0.9}
        for i in range(8)
    ]
    section = _graph_section(nodes)
    compressor = GraphBundleCompressor({"compression": {"graph_prune_threshold": 1.0}})
    result = compressor.compress(section, "unrelated", {})
    text = result.content[0]["compact"] if result.content else ""
    assert "locked: use JWT" in text
    assert "tentative: maybe sessions" not in text
