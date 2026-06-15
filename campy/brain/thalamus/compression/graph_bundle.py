"""
campy/brain/thalamus/compression/graph_bundle.py

GraphBundleCompressor — graph-native compression for Campy memory bundles.

WHY THIS IS NOT TOON/ONTO:
Campy's "semantic" and "graph" bundle sections are subgraphs, not JSON arrays.
TOON/ONTO reduces syntactic overhead (curly braces, repeated keys) but keeps
all nodes — including irrelevant ones. GraphBundleCompressor prunes semantically
irrelevant nodes *before* serialization using graph signals:

  score(node) = cosine_similarity(query_emb, node_emb) × pathway_strength

  - cosine_similarity: how close this node is to what the agent asked
  - pathway_strength: Campy's graph-maintained consolidation weight (0–1).
    High pathway_strength = well-established memory. This is a native KuzuDB
    property, not a heuristic — it reflects the Gated Consolidation Loop output.

Nodes scoring below the bottom `graph_prune_threshold` percentile are dropped.
Remaining nodes emit in compact adjacency notation (type prefix + text).

PHASE B: When _stage_graph_structure in bundle_compiler.py returns relationship
data (adjacency), replace the simple score with Personalized PageRank:
  - Build adjacency from relationship data in the "graph" section
  - Use query_emb as the PageRank personalization vector
  - Use power iteration (20 steps, damping 0.85)
The interface of this compressor does not change — only the scoring function.
"""

from __future__ import annotations
import math
from typing import TYPE_CHECKING
from campy.brain.thalamus.compression import Compressor

if TYPE_CHECKING:
    from campy.brain.thalamus.bundle_compiler import BundleSection

_PREFIX_MAP = {
    "Concept":          "C",
    "Decision":         "D",
    "Lesson":           "L",
    "Plan":             "P",
    "Procedure":        "PR",
    "Constraint":       "K",
    "Requirement":      "R",
    "ActionItem":       "A",
    "GlobalConstraint": "GK",
    "GlobalPreference": "GP",
}


def _node_prefix(node_type: str) -> str:
    return _PREFIX_MAP.get(node_type, "?")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _embed_query(query: str, config: dict) -> list[float] | None:
    try:
        from campy.brain.hippocampus.graph import embeddings as emb
        model_name = config.get("embeddings", {}).get(
            "model", "sentence-transformers/all-MiniLM-L6-v2"
        )
        return emb.embed(query, model_name=model_name)
    except Exception:
        return None


def _embed_text(text: str, config: dict) -> list[float] | None:
    try:
        from campy.brain.hippocampus.graph import embeddings as emb
        model_name = config.get("embeddings", {}).get(
            "model", "sentence-transformers/all-MiniLM-L6-v2"
        )
        return emb.embed(text, model_name=model_name)
    except Exception:
        return None


def _score_node(node: dict, query_emb: list[float] | None, config: dict) -> float:
    """
    Phase A scoring: cosine_similarity(query_emb, node_emb) × pathway_strength.
    Falls back to pathway_strength × confidence if embedding unavailable.
    """
    pathway_strength = float(node.get("pathway_strength", 0.5))
    confidence = float(node.get("confidence", 0.5))

    if query_emb is not None:
        text = node.get("text", "")
        node_emb = _embed_text(text, config) if text else None
        if node_emb is not None:
            sim = _cosine_similarity(query_emb, node_emb)
            return max(0.0, sim) * pathway_strength
    # Fallback: pure graph signal
    return pathway_strength * confidence


def _compact_line(node: dict) -> str:
    prefix = _node_prefix(node.get("type", ""))
    text = node.get("text", "").strip()
    return f"{prefix}:{text}"


class GraphBundleCompressor(Compressor):
    """
    Scores, prunes, and serializes graph bundle sections using graph-native signals.
    """

    def __init__(self, config: dict) -> None:
        self._config = config

    def compress(self, section: "BundleSection", query: str, config: dict) -> "BundleSection":
        from campy.brain.thalamus.bundle_compiler import BundleSection as BS

        if not section.content:
            return section

        # config={} is falsy; fall back to self._config which holds constructor config
        effective_config = config or self._config
        threshold = effective_config.get("compression", {}).get("graph_prune_threshold", 0.30)

        # Score each node
        query_emb = _embed_query(query, effective_config) if query else None
        scored = [
            (node, _score_node(node, query_emb, effective_config))
            for node in section.content
            if isinstance(node, dict)
        ]

        if not scored:
            return section

        # Prune bottom `threshold` fraction by score
        scored.sort(key=lambda x: x[1])
        cutoff_index = max(0, int(len(scored) * threshold))
        surviving = [node for node, _ in scored[cutoff_index:]]

        if not surviving:
            surviving = [scored[-1][0]]  # always keep at least one node

        # Serialize in compact adjacency notation
        lines = [_compact_line(n) for n in surviving]
        compact_text = "\n".join(lines)

        return BS(
            section_type=section.section_type,
            content=[{"compact": compact_text}],
            token_estimate=len(compact_text) // 4,
            source_node_ids=section.source_node_ids,
        )
