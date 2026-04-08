from __future__ import annotations

import pytest


class SingleRowResult:
    def __init__(self, row):
        self._row = row
        self._read = False
    def has_next(self): return not self._read
    def get_next(self):
        self._read = True
        return self._row


class MultiRowResult:
    def __init__(self, rows):
        self._rows = list(rows)
        self._idx = 0
    def has_next(self): return self._idx < len(self._rows)
    def get_next(self):
        row = self._rows[self._idx]
        self._idx += 1
        return row


class EmptyResult:
    def has_next(self): return False


def test_jaccard_similarity_basic():
    from mcp_engine.loop.step5_retrieval import _jaccard_similarity

    a = {"a", "b"}
    b = {"b", "c"}
    assert abs(_jaccard_similarity(a, b) - (1.0 / 3.0)) < 1e-6


def test_topological_promotion_boosts_candidate():
    from mcp_engine.loop.step5_retrieval import retrieve_candidates, MATCH_THRESHOLD

    class MockDB:
        def vector_search(self, table_name, index_name, embedding, limit):
            # single candidate in the topo range
            return [
                {"node": {"concept_id": "cand1", "text_raw": "candidate", "archived": False},
                 "score": 0.60},
            ]

        def execute(self, q, p=None):
            # incoming neighbors and candidate neighbors match fully
            if 'MATCH (c:Concept)-[r]->(n:Concept)' in q:
                ids = p.get('ids', []) if p else []
                if 'inc1' in ids:
                    return MultiRowResult([[f'n{i}'] for i in range(3)])
                if 'cand1' in ids:
                    return MultiRowResult([[f'n{i}'] for i in range(3)])
            # no CO_OCCURS_WITH rows
            if 'CO_OCCURS_WITH' in q:
                return EmptyResult()
            return EmptyResult()

    result = retrieve_candidates([0.1] * 384, "other-id", MockDB(), exclude_ids=["inc1"])
    assert len(result) == 1
    cand = result[0]
    assert cand.get("topo_boosted", False) is True
    assert pytest.approx(cand.get("jaccard_overlap", 0.0), rel=1e-3) == 1.0
    assert cand.get("orig_similarity") == pytest.approx(0.60)
    assert cand.get("similarity") >= MATCH_THRESHOLD


def test_topological_no_promotion_if_low_jaccard():
    from mcp_engine.loop.step5_retrieval import retrieve_candidates

    class MockDB:
        def vector_search(self, table_name, index_name, embedding, limit):
            return [
                {"node": {"concept_id": "cand2", "text_raw": "candidate2", "archived": False},
                 "score": 0.60},
            ]

        def execute(self, q, p=None):
            ids = p.get('ids', []) if p else []
            if 'MATCH (c:Concept)-[r]->(n:Concept)' in q:
                if 'inc2' in ids:
                    return MultiRowResult([["a"], ["b"]])
                if 'cand2' in ids:
                    return MultiRowResult([["x"], ["y"]])
            if 'CO_OCCURS_WITH' in q:
                return EmptyResult()
            return EmptyResult()

    result = retrieve_candidates([0.1] * 384, "other-id", MockDB(), exclude_ids=["inc2"])
    # no candidates should be promoted because jaccard == 0
    assert result == []


def test_neighbor_cap_and_promotion_with_large_neighbor_sets():
    from mcp_engine.loop.step5_retrieval import retrieve_candidates

    # create large neighbor lists for incoming and candidate but identical
    incoming_neighbors = [f'n{i}' for i in range(100)]
    candidate_neighbors = incoming_neighbors.copy()

    class MockDB:
        def vector_search(self, table_name, index_name, embedding, limit):
            return [
                {"node": {"concept_id": "cand3", "text_raw": "candidate3", "archived": False},
                 "score": 0.60},
            ]

        def execute(self, q, p=None):
            ids = p.get('ids', []) if p else []
            if 'MATCH (c:Concept)-[r]->(n:Concept)' in q:
                if 'inc3' in ids:
                    return MultiRowResult([[i] for i in incoming_neighbors])
                if 'cand3' in ids:
                    return MultiRowResult([[i] for i in candidate_neighbors])
            if 'CO_OCCURS_WITH' in q:
                return EmptyResult()
            return EmptyResult()

    result = retrieve_candidates([0.1] * 384, "other-id", MockDB(), exclude_ids=["inc3"])
    # identical large neighbor sets should still promote the candidate
    assert len(result) == 1
    assert result[0].get("topo_boosted", False) is True
