"""
tests/test_bundle_compiler_stages.py — Real-Kuzu regression tests for
_stage_exact_facts / _stage_semantic_context (B306).

Unlike the mocked tests in test_bundle_compiler.py, these run the stages'
raw Cypher against a real Kuzu database. Mocking db.execute() never
exercises the actual query text, so a Cypher syntax bug in these two
stages was previously invisible: it was thrown, caught by a bare
`except Exception`, and silently turned into "no content" on every call.
"""

from __future__ import annotations

import shutil
import tempfile

import pytest

from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.thalamus.bundle_compiler import (
    _stage_exact_facts,
    _stage_semantic_context,
)

FAKE_DIM = 4
FAKE_EMBEDDING_MODEL = "fake-test-model"
CONFIG = {"embeddings": {"model": FAKE_EMBEDDING_MODEL}}
TIER_CONFIG = {"max_semantic": 10}


def _fake_embed(text: str, model_name: str = FAKE_EMBEDDING_MODEL) -> list[float]:
    """Deterministic stand-in for the real sentence-transformers model."""
    return [1.0, 0.0, 0.0, 0.0] if text == "query" else [0.0, 1.0, 0.0, 0.0]


@pytest.fixture()
def real_db(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="bundle_stage_")
    db = KuzuClient(f"{tmp}/db")
    monkeypatch.setattr(
        "campy.brain.hippocampus.graph.embeddings.embed", _fake_embed
    )
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


class TestStageExactFacts:
    def _create_tables(self, db: KuzuClient) -> None:
        db.execute(
            "CREATE NODE TABLE GlobalConstraint("
            "id STRING, text_raw STRING, confidence DOUBLE, "
            f"embedding FLOAT[{FAKE_DIM}], PRIMARY KEY (id))"
        )
        db.execute(
            "CREATE NODE TABLE GlobalPreference("
            "id STRING, text_raw STRING, confidence DOUBLE, "
            f"embedding FLOAT[{FAKE_DIM}], PRIMARY KEY (id))"
        )

    async def test_returns_matching_facts_across_both_labels(self, real_db):
        db = real_db
        self._create_tables(db)
        db.execute(
            "CREATE (n:GlobalConstraint {id: 'gc1', text_raw: 'never delete prod', "
            "confidence: 0.9, embedding: $emb})",
            {"emb": [0.99, 0.01, 0.0, 0.0]},
        )
        db.execute(
            "CREATE (n:GlobalPreference {id: 'gp1', text_raw: 'prefers terse replies', "
            "confidence: 0.8, embedding: $emb})",
            {"emb": [0.98, 0.02, 0.0, 0.0]},
        )
        db.execute(
            "CREATE (n:GlobalPreference {id: 'gp2', text_raw: 'unrelated far fact', "
            "confidence: 0.8, embedding: $emb})",
            {"emb": [0.0, 0.0, 1.0, 0.0]},
        )

        section = await _stage_exact_facts(db, "query", CONFIG, TIER_CONFIG)

        assert section is not None
        assert section.section_type == "exact_fact"
        texts = {c["text"] for c in section.content}
        types = {c["type"] for c in section.content}
        assert texts == {"never delete prod", "prefers terse replies"}
        assert types == {"GlobalConstraint", "GlobalPreference"}

    async def test_returns_none_when_nothing_matches(self, real_db):
        db = real_db
        self._create_tables(db)
        db.execute(
            "CREATE (n:GlobalConstraint {id: 'gc1', text_raw: 'unrelated', "
            "confidence: 0.9, embedding: $emb})",
            {"emb": [0.0, 0.0, 1.0, 0.0]},
        )

        section = await _stage_exact_facts(db, "query", CONFIG, TIER_CONFIG)

        assert section is None

    async def test_limit_applies_across_both_labels_combined(self, real_db):
        """Regression guard: a naive `UNION ... LIMIT 10` in Kuzu 0.11.3 only
        limits the last branch, not the combined result across both labels."""
        db = real_db
        self._create_tables(db)
        for i in range(8):
            db.execute(
                f"CREATE (n:GlobalConstraint {{id: 'gc{i}', text_raw: 'gc match {i}', "
                "confidence: 0.9, embedding: $emb})",
                {"emb": [0.99, 0.01, 0.0, 0.0]},
            )
        for i in range(8):
            db.execute(
                f"CREATE (n:GlobalPreference {{id: 'gp{i}', text_raw: 'gp match {i}', "
                "confidence: 0.8, embedding: $emb})",
                {"emb": [0.98, 0.02, 0.0, 0.0]},
            )

        section = await _stage_exact_facts(db, "query", CONFIG, TIER_CONFIG)

        assert section is not None
        assert len(section.content) == 10


class TestStageSemanticContext:
    def _create_tables(self, db: KuzuClient) -> None:
        for table in ("Concept", "Decision", "Constraint", "Requirement"):
            db.execute(
                f"CREATE NODE TABLE {table}("
                "id STRING, text_raw STRING, confidence DOUBLE, "
                f"pathway_strength DOUBLE, embedding FLOAT[{FAKE_DIM}], PRIMARY KEY (id))"
            )

    async def test_returns_matching_content_across_labels(self, real_db):
        db = real_db
        self._create_tables(db)
        db.execute(
            "CREATE (n:Concept {id: 'c1', text_raw: 'concept close', confidence: 0.9, "
            "pathway_strength: 0.6, embedding: $emb})",
            {"emb": [0.99, 0.01, 0.0, 0.0]},
        )
        db.execute(
            "CREATE (n:Decision {id: 'd1', text_raw: 'decision close', confidence: 0.9, "
            "pathway_strength: 0.6, embedding: $emb})",
            {"emb": [0.97, 0.03, 0.0, 0.0]},
        )
        db.execute(
            "CREATE (n:Requirement {id: 'r1', text_raw: 'requirement far', confidence: 0.9, "
            "pathway_strength: 0.6, embedding: $emb})",
            {"emb": [0.0, 0.0, 1.0, 0.0]},
        )

        section = await _stage_semantic_context(db, "query", CONFIG, TIER_CONFIG)

        assert section is not None
        assert section.section_type == "semantic"
        texts = {c["text"] for c in section.content}
        assert texts == {"concept close", "decision close"}
        assert "requirement far" not in texts

    async def test_respects_limit_across_unioned_labels(self, real_db):
        """Regression guard: a naive `UNION ... ORDER BY ... LIMIT` in Kuzu 0.11.3
        only orders/limits the last branch, not the globally closest matches
        across all four labels."""
        db = real_db
        self._create_tables(db)
        # Closest match is in the FIRST branch (Concept), not the last
        # (Requirement) - this only passes if the cap is applied globally.
        db.execute(
            "CREATE (n:Concept {id: 'c1', text_raw: 'closest match', confidence: 0.9, "
            "pathway_strength: 0.6, embedding: $emb})",
            {"emb": [1.0, 0.0, 0.0, 0.0]},
        )
        for table in ("Decision", "Constraint", "Requirement"):
            db.execute(
                f"CREATE (n:{table} {{id: '{table.lower()}1', text_raw: '{table} match', "
                "confidence: 0.9, pathway_strength: 0.6, embedding: $emb})",
                {"emb": [0.99, 0.01, 0.0, 0.0]},
            )

        section = await _stage_semantic_context(db, "query", CONFIG, {"max_semantic": 1})

        assert section is not None
        assert len(section.content) == 1
        assert section.content[0]["text"] == "closest match"

    async def test_returns_none_when_nothing_matches(self, real_db):
        db = real_db
        self._create_tables(db)
        db.execute(
            "CREATE (n:Concept {id: 'c1', text_raw: 'unrelated', confidence: 0.9, "
            "pathway_strength: 0.6, embedding: $emb})",
            {"emb": [0.0, 0.0, 1.0, 0.0]},
        )

        section = await _stage_semantic_context(db, "query", CONFIG, TIER_CONFIG)

        assert section is None
