"""B437: bundle_compiler.py's schema-introspection helpers
(_table_has_column / _table_has_authority / _table_has_flagged_for_review)
used `CALL table_info(...)` -- Kùzu-only Cypher syntax -- which raised
against the real Oxigraph engine and was silently swallowed, always
returning False. This meant every stage that consults these helpers
always picked the unfiltered base NamedQuery variant, letting
flagged/archived/superseded content leak into ask()/compile_context().

tests/test_bundle_compiler_stages.py already proves the *filtering
logic* is correct, but only against tests/kuzu_test_client.py's real
Kùzu client -- never against the actual production engine (Oxigraph).
These tests drive the real OxigraphClient, the one thing the prior
tests never did, closing exactly the gap that let the bug ship.
"""

from __future__ import annotations

import shutil
import tempfile

import pytest

from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient, mint_uri
from campy.brain.thalamus.bundle_compiler import (
    _stage_exact_facts,
    _stage_graph_structure,
    _stage_semantic_context,
    _table_has_authority,
    _table_has_column,
    _table_has_flagged_for_review,
)

FAKE_EMBEDDING_MODEL = "fake-test-model"
CONFIG = {"embeddings": {"model": FAKE_EMBEDDING_MODEL}}
TIER_CONFIG = {"max_semantic": 10}
DIM = 384


def _vec(seed: float) -> list[float]:
    return [seed] + [0.0] * (DIM - 1)


def _orthogonal_vec() -> list[float]:
    """A vector with ~0 cosine similarity to `_vec(1.0)` (the query
    embedding) — used for graph-traversal *targets* so they don't also
    qualify as anchors themselves (search_vectors' min_score=0.70 gate
    only cares about direction, not magnitude, so a same-direction
    scaled vector would still match)."""
    return [0.0, 1.0] + [0.0] * (DIM - 2)


def _fake_embed(text: str, model_name: str = FAKE_EMBEDDING_MODEL) -> list[float]:
    return _vec(1.0)


@pytest.fixture()
def real_oxigraph_db(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="b437_")
    db = OxigraphClient(f"{tmp}/db")
    monkeypatch.setattr(
        "campy.brain.hippocampus.graph.embeddings.embed", _fake_embed
    )
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


class TestSchemaIntrospectionHelpers:
    """Direct proof the helpers detect real columns against real Oxigraph."""

    def test_table_has_column_true_for_real_column(self, real_oxigraph_db):
        assert _table_has_column(real_oxigraph_db, "Concept", "archived") is True
        assert _table_has_column(real_oxigraph_db, "Concept", "flagged_for_review") is True
        assert _table_has_column(real_oxigraph_db, "Concept", "authority") is True

    def test_table_has_column_false_for_nonexistent_column(self, real_oxigraph_db):
        assert _table_has_column(real_oxigraph_db, "Concept", "not_a_real_column") is False

    def test_table_has_authority_and_flagged_delegate_correctly(self, real_oxigraph_db):
        assert _table_has_authority(real_oxigraph_db, "Concept") is True
        assert _table_has_flagged_for_review(real_oxigraph_db, "Concept") is True


class TestStageExactFactsRealOxigraph:
    async def test_flagged_node_excluded_against_real_oxigraph(self, real_oxigraph_db):
        db = real_oxigraph_db
        db.write_node("GlobalConstraint", {
            "global_constraint_id": "gc-flagged",
            "text_raw": "flagged content",
            "confidence": 0.9,
            "flagged_for_review": True,
            "embedding": _vec(1.0),
        })
        db.write_node("GlobalPreference", {
            "global_preference_id": "gp-clean",
            "text_raw": "clean content",
            "confidence": 0.8,
            "flagged_for_review": False,
            "embedding": _vec(1.0),
        })

        section = await _stage_exact_facts(db, "query", CONFIG, TIER_CONFIG)

        assert section is not None
        texts = {c["text"] for c in section.content}
        assert texts == {"clean content"}


class TestStageSemanticContextRealOxigraph:
    async def test_flagged_concept_excluded_against_real_oxigraph(self, real_oxigraph_db):
        db = real_oxigraph_db
        db.write_node("Concept", {
            "concept_id": "c-flagged",
            "text_raw": "flagged concept",
            "confidence": 0.9,
            "flagged_for_review": True,
            "pathway_strength": 0.5,
            "embedding": _vec(1.0),
        })
        db.write_node("Decision", {
            "decision_id": "d-clean",
            "text_raw": "clean decision",
            "confidence": 0.9,
            "flagged_for_review": False,
            "pathway_strength": 0.5,
            "embedding": _vec(1.0),
        })

        section = await _stage_semantic_context(db, "query", CONFIG, TIER_CONFIG)

        assert section is not None
        texts = {c["text"] for c in section.content}
        assert texts == {"clean decision"}
        assert "flagged concept" not in texts


class TestStageGraphStructureRealOxigraph:
    async def test_flagged_anchor_excluded_against_real_oxigraph(self, real_oxigraph_db):
        db = real_oxigraph_db
        db.write_node("Concept", {
            "concept_id": "c-flagged-anchor",
            "text_raw": "flagged anchor",
            "confidence": 0.9,
            "flagged_for_review": True,
            "pathway_strength": 0.5,
            "embedding": _vec(1.0),
        })
        db.write_node("Concept", {
            "concept_id": "c-flagged-target",
            "text_raw": "flagged target",
            "confidence": 0.9,
            "embedding": _orthogonal_vec(),
        })
        db.write_edge(
            "REQUIRES",
            mint_uri("Concept", "c-flagged-anchor"),
            mint_uri("Concept", "c-flagged-target"),
        )

        db.write_node("Concept", {
            "concept_id": "c-clean-anchor",
            "text_raw": "clean anchor",
            "confidence": 0.9,
            "flagged_for_review": False,
            "pathway_strength": 0.5,
            "embedding": _vec(1.0),
        })
        db.write_node("Concept", {
            "concept_id": "c-clean-target",
            "text_raw": "clean target",
            "confidence": 0.9,
            "embedding": _orthogonal_vec(),
        })
        db.write_edge(
            "REQUIRES",
            mint_uri("Concept", "c-clean-anchor"),
            mint_uri("Concept", "c-clean-target"),
        )

        section = await _stage_graph_structure(db, "query", CONFIG, TIER_CONFIG, existing_sources=[])

        assert section is not None
        froms = {c["from"] for c in section.content}
        assert froms == {"clean anchor"}
        assert "flagged anchor" not in froms
