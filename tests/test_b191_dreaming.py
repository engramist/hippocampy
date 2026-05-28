from __future__ import annotations
import pytest

from typing import Any

from campy.brain.brainstem.sweep import _dream_consolidation


class FakeResult:
    def __init__(self, rows: list[Any]):
        self._rows = rows
        self._i = 0

    def has_next(self):
        return self._i < len(self._rows)

    def get_next(self):
        r = self._rows[self._i]
        self._i += 1
        return r


class FakeDB:
    def __init__(self, lessons: list[dict]):
        # lessons: list of dicts with keys id, domain, embedding, text, pathway, confidence
        self.lessons = lessons
        self.writes = []

    def execute(self, query: str, params: dict | None = None):
        params = params or {}
        q = query.strip()
        # DISTINCT domains
        if "RETURN DISTINCT l.domain" in q:
            domains = sorted({l["domain"] for l in self.lessons if not l.get("archived", False) and (l.get("lesson_type") is None or l.get("lesson_type") != "synthesis")})
            return FakeResult([[d] for d in domains])

        # Candidate lessons for a domain
        if "RETURN l.lesson_id, l.embedding" in q:
            domain = params.get("domain")
            rows = []
            for l in self.lessons:
                if l.get("archived"):
                    continue
                if (l.get("lesson_type") or "") == "synthesis":
                    continue
                if l.get("domain") != domain:
                    continue
                rows.append([l["id"], l["embedding"], l.get("text", ""), l.get("pathway", 0.0), l.get("confidence", 0.0)])
            return FakeResult(rows)

        return FakeResult([])

    async def execute_write(self, query: str, params: dict | None = None):
        self.writes.append({"query": query, "params": params})


class FakeLLM:
    async def achat(self, messages):
        return "MetaTitle: Explore-first dominates. Explore broadly before goal seeking. Recommendation: spend 3 quick exploratory actions."


@pytest.mark.asyncio
async def test_dream_consolidation_creates_meta_and_updates_constituents(monkeypatch):
    # Prepare three similar 'spatial' lessons that should cluster
    lessons = [
        {"id": "L1", "domain": "spatial", "embedding": [1.0, 0.0, 0.0], "text": "explore first", "pathway": 0.5, "confidence": 0.6},
        {"id": "L2", "domain": "spatial", "embedding": [0.9, 0.1, 0.0], "text": "try unexplored actions", "pathway": 0.45, "confidence": 0.55},
        {"id": "L3", "domain": "spatial", "embedding": [0.85, 0.15, 0.0], "text": "avoid early goal seeking", "pathway": 0.4, "confidence": 0.5},
        {"id": "L4", "domain": "other", "embedding": [0.0, 1.0, 0.0], "text": "other domain", "pathway": 0.3, "confidence": 0.3},
    ]

    db = FakeDB(lessons)
    llm = FakeLLM()

    # Patch embed to a deterministic 3-d vector for synthesized text
    monkeypatch.setattr("campy.brain.hippocampus.graph.embeddings.embed", lambda t, model_name=None: [0.0, 0.0, 1.0])

    config = {
        "embeddings": {"model": "mock-model"},
        "sweep": {"dreaming": {"min_cluster_size": 3, "similarity_threshold": 0.7, "max_syntheses_per_sweep": 5, "decay_boost_multiplier": 1.3}},
    }

    synthesized, errors = await _dream_consolidation(db, config, llm)

    assert errors == 0
    assert synthesized >= 1

    # Ensure at least one CREATE (meta lesson) write occurred
    creates = [w for w in db.writes if "CREATE (m:Lesson" in (w.get("query") or "")]
    assert len(creates) >= 1

    # Ensure constituent updates include decay_boost parameter
    decay_updates = [w for w in db.writes if w.get("params") and w["params"].get("decay_boost")]
    assert len(decay_updates) >= 1
