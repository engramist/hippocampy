import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import types

# Provide a dummy 'kuzu' module for tests that import graph clients.
sys.modules.setdefault('kuzu', types.SimpleNamespace())

from mcp_engine.tools import get_disambiguation_queue
from mcp_engine.loop.step5_retrieval import retrieve_candidates


class RowResult:
    def __init__(self, rows):
        self.rows = list(rows)
        self.idx = 0

    def has_next(self):
        return self.idx < len(self.rows)

    def get_next(self):
        row = self.rows[self.idx]
        self.idx += 1
        return row


class MockDBForQueue:
    def execute(self, query, params=None):
        if "MATCH (e:DisambiguationEvent)" in query and "WHERE e.status = 'pending'" in query:
            return RowResult([
                ["eid-1", "cA", "cB", 0.85, "2026-04-01T00:00:00Z"]
            ])
        if "MATCH (c:Concept {concept_id: $cid})" in query:
            cid = params.get("cid")
            if cid == "cA":
                return RowResult([["cA", "Alpha", "Thing", 0.6, 0.5, True, ["alt-A"]]])
            if cid == "cB":
                return RowResult([["cB", "Beta", "Thing", 0.7, 0.4, False, []]])
        if "MATCH (a:Concept {concept_id: $a})-[]->(n:Concept)<-[]-(b:Concept {concept_id: $b})" in query:
            return RowResult([["n1", "Neighbor 1"]])
        return RowResult([])


class MockDBForRetrieval:
    def vector_search(self, table_name, index_name, embedding, limit):
        return [
            {"node": {"concept_id": "cB", "text_raw": "B", "pathway_strength": 0.8, "confidence": 0.9, "gist_class": "", "schema_org_type": "", "created_at": ""}, "score": 0.90},
            {"node": {"concept_id": "cC", "text_raw": "C", "pathway_strength": 0.7, "confidence": 0.8, "gist_class": "", "schema_org_type": "", "created_at": ""}, "score": 0.85},
        ]

    def execute(self, query, params=None):
        if "MATCH (a:Concept)-[:DISTINCT_FROM]-(b:Concept)" in query:
            # Simulate that cB is DISTINCT_FROM the provided exclude id
            return RowResult([["cB"]])
        return RowResult([])


@pytest.mark.asyncio
async def test_get_disambiguation_queue_returns_pair():
    db = MockDBForQueue()
    res = await get_disambiguation_queue({"limit": 1}, db, {})
    assert "pairs" in res
    assert res["total_pending"] == 1
    pair = res["pairs"][0]
    assert pair["event_id"] == "eid-1"
    assert pair["concept_a"]["concept_id"] == "cA"
    assert pair["concept_b"]["concept_id"] == "cB"
    assert isinstance(pair["shared_neighbors"], list)


def test_retrieve_candidates_respects_distinct_from():
    db = MockDBForRetrieval()
    embedding = [0.0] * 384
    hits = retrieve_candidates(embedding, exclude_id="", db=db, limit=5, exclude_ids=["cA"])
    # cB should be filtered out because it's DISTINCT_FROM the exclude id
    ids = [h["concept_id"] for h in hits]
    assert "cB" not in ids
    assert "cC" in ids

