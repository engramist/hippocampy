from __future__ import annotations

import pytest

from campy.brain.thalamus.tools import _apply_fusion_adjustments, _rrf_fuse, current_truth


class _Result:
    def __init__(self, rows: list[list]):
        self._rows = rows
        self._i = 0

    def has_next(self):
        return self._i < len(self._rows)

    def get_next(self):
        row = self._rows[self._i]
        self._i += 1
        return row


class _MockDB:
    def __init__(self, by_index: dict[str, list[dict]], lexical_rows: list[list] | None = None):
        self.by_index = by_index
        self.lexical_rows = lexical_rows or []

    def vector_search(self, table_name, index_name, embedding, limit):
        _ = table_name, embedding, limit
        return self.by_index.get(index_name, [])

    def execute(self, query, params=None):
        _ = params
        if "MATCH (m:Message)" in query and "lower(m.text_raw) CONTAINS" in query:
            return _Result(self.lexical_rows)
        # current_truth outcome batch lookup fallback
        if "UNWIND $ids AS nid" in query:
            return _Result([])
        return _Result([])


def _concept_node(node_id: str, *, ps: float = 0.0, conf: float = 0.0):
    return {
        "concept_id": node_id,
        "text_raw": node_id,
        "pathway_strength": ps,
        "confidence": conf,
        "confidence_low": False,
        "archived": False,
    }


def _decision_node(node_id: str, *, ps: float = 0.0, conf: float = 0.0):
    return {
        "decision_id": node_id,
        "text_raw": node_id,
        "pathway_strength": ps,
        "confidence": conf,
        "confidence_low": False,
        "archived": False,
    }


@pytest.mark.asyncio
async def test_vector_consensus_beats_single_lexical(monkeypatch):
    import campy.brain.thalamus.tools as tools_mod

    monkeypatch.setattr(tools_mod.emb, "embed", lambda text, model_name=None: [0.1] * 384)

    db = _MockDB(
        by_index={
            "concept_emb_idx": [
                {"node": _concept_node("shared", ps=0.2, conf=0.8), "score": 0.95},
            ],
            "decision_emb_idx": [
                {"node": _decision_node("shared", ps=0.2, conf=0.8), "score": 0.90},
            ],
        },
        lexical_rows=[
            ["lex-1", "lexical only text", "user", 0.1, True, 0.0, "2026-01-01T00:00:00"],
        ],
    )

    result = await current_truth(
        {"query": "shared", "session_id": "unknown", "limit": 5},
        db,
        {"embeddings": {"model": "mock-model"}, "retrieval": {"lexical_window_days": 30, "lexical_limit": 5}},
    )
    ids = [r["node_id"] for r in result["results"]]
    assert ids[0] == "shared"
    assert "lex-1" in ids


@pytest.mark.asyncio
async def test_lexical_recent_hit_still_surfaces(monkeypatch):
    import campy.brain.thalamus.tools as tools_mod

    monkeypatch.setattr(tools_mod.emb, "embed", lambda text, model_name=None: [0.1] * 384)

    db = _MockDB(
        by_index={
            "concept_emb_idx": [
                {"node": _concept_node("c1", ps=0.1, conf=0.6), "score": 0.80},
                {"node": _concept_node("c2", ps=0.1, conf=0.6), "score": 0.70},
            ]
        },
        lexical_rows=[
            ["lex-2", "recent lexical hit", "assistant", 0.2, True, 0.0, "2026-01-02T00:00:00"],
        ],
    )

    result = await current_truth(
        {"query": "recent", "session_id": "unknown", "limit": 5},
        db,
        {"embeddings": {"model": "mock-model"}, "retrieval": {"lexical_window_days": 30, "lexical_limit": 5}},
    )
    ids = [r["node_id"] for r in result["results"]]
    assert "lex-2" in ids


def test_pathway_strength_bounded():
    fused = [
        {"cand": {"node_id": "high", "score": 0.8}, "rrf": 1.0, "sources": {}},
        {"cand": {"node_id": "low", "score": 0.8}, "rrf": 1.0, "sources": {}},
    ]
    result_by_id = {
        "high": {"node_id": "high", "pathway_strength": 100.0},
        "low": {"node_id": "low", "pathway_strength": 1.0},
    }
    adjusted = _apply_fusion_adjustments(fused, result_by_id, outcome_map={})
    finals = {row["node_id"]: row["final"] for row in adjusted}
    ratio = finals["high"] / finals["low"]
    assert ratio <= 1.5


def test_negative_valence_demotes():
    fused = [
        {"cand": {"node_id": "neg", "score": 0.8}, "rrf": 1.0, "sources": {}},
        {"cand": {"node_id": "neu", "score": 0.8}, "rrf": 1.0, "sources": {}},
    ]
    result_by_id = {
        "neg": {"node_id": "neg", "pathway_strength": 1.0},
        "neu": {"node_id": "neu", "pathway_strength": 1.0},
    }
    outcome_map = {"neg": (-1.0, 2), "neu": (0.0, 2)}
    adjusted = _apply_fusion_adjustments(fused, result_by_id, outcome_map)
    finals = {row["node_id"]: row["final"] for row in adjusted}
    assert finals["neg"] < finals["neu"]


def test_rrf_pure_function():
    source_lists = {
        "vector:Concept": [
            {"node_id": "a", "score": 0.9},
            {"node_id": "b", "score": 0.8},
        ],
        "lexical": [
            {"node_id": "b", "score": 0.0},
            {"node_id": "c", "score": 0.0},
        ],
    }
    fused = _rrf_fuse(source_lists, limit=10)
    by_id = {entry["cand"]["node_id"]: entry["rrf"] for entry in fused}
    assert by_id["a"] == pytest.approx(1.0 / 61.0)
    assert by_id["b"] == pytest.approx((1.0 / 62.0) + (1.0 / 61.0))
    assert by_id["c"] == pytest.approx(1.0 / 62.0)


@pytest.mark.asyncio
async def test_response_shape_unchanged(monkeypatch):
    import campy.brain.thalamus.tools as tools_mod

    monkeypatch.setattr(tools_mod.emb, "embed", lambda text, model_name=None: [0.1] * 384)

    db = _MockDB(
        by_index={
            "concept_emb_idx": [
                {"node": _concept_node("shape-node", ps=0.2, conf=0.7), "score": 0.9},
            ]
        }
    )

    result = await current_truth(
        {"query": "shape", "session_id": "unknown", "limit": 3},
        db,
        {"embeddings": {"model": "mock-model"}},
    )
    row = result["results"][0]
    assert set(row.keys()) == {
        "node_id",
        "node_type",
        "text_raw",
        "confidence",
        "confidence_low",
        "pathway_strength",
        "similarity",
        "activation_score",
        "outcome_valence",
        "outcome_warning",
        "lexical_exact",
        "memory_link",
    }
