"""B435: bundle_compiler.py's _stage_semantic_context enforces a hardcoded
0.30 cosine-distance floor with no lexical rescue for real, relevant text
that happens to embed far from a paraphrased/terse query. This was
documented in the orphaned pre-cutover benchmark report
(docs/benchmarks/kuzu-baseline-kpis.md, PR #229): a natural-language
probe question against a short concept node measured ~0.50 distance --
well past the floor -- and was silently dropped.

Reproduced directly against a real sentence-transformers embedding
(2026-09-20): "What is Alex's current diet? Are they vegan or
pescatarian?" vs. "vegan" measures 0.48 distance; vs. "does not eat
meat, fish, or dairy" measures 0.51 -- both comfortably past 0.30.

These tests drive the real OxigraphClient (the actual production engine
since the B389/B397 cutover) with deliberately far-apart, fully
controlled embeddings -- proving the *mechanism* (a real lexical/keyword
match rescues a node vector search alone would miss), independent of any
one embedding model's specific numbers.
"""

from __future__ import annotations

import shutil
import tempfile

import pytest

from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.thalamus.bundle_compiler import _stage_semantic_context

FAKE_EMBEDDING_MODEL = "fake-test-model"
CONFIG = {"embeddings": {"model": FAKE_EMBEDDING_MODEL}}
TIER_CONFIG = {"max_semantic": 10}
DIM = 384


def _query_vec() -> list[float]:
    return [1.0] + [0.0] * (DIM - 1)


def _far_vec() -> list[float]:
    """Orthogonal to `_query_vec()` -- cosine distance 1.0, nowhere near
    clearing the 0.30 floor -- simulating a real embedding model placing
    a textually-relevant paraphrase/terse fact far from the query."""
    return [0.0, 1.0] + [0.0] * (DIM - 2)


def _fake_embed(text: str, model_name: str = FAKE_EMBEDDING_MODEL) -> list[float]:
    return _query_vec()


@pytest.fixture()
def real_oxigraph_db(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="b435_")
    db = OxigraphClient(f"{tmp}/db")
    monkeypatch.setattr(
        "campy.brain.hippocampus.graph.embeddings.embed", _fake_embed
    )
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


class TestLexicalFallback:
    async def test_baseline_vector_search_alone_misses_far_paraphrase(self, real_oxigraph_db):
        """Sanity baseline: with the fallback's keyword unable to match
        (different text entirely), a far-embedded node is correctly
        absent -- proving the floor itself still works as designed."""
        db = real_oxigraph_db
        db.write_node("Concept", {
            "concept_id": "c-unrelated",
            "text_raw": "completely unrelated topic about spacecraft engines",
            "confidence": 0.9,
            "pathway_strength": 0.5,
            "embedding": _far_vec(),
        })

        section = await _stage_semantic_context(db, "vegan diet preferences", CONFIG, TIER_CONFIG)

        assert section is None

    async def test_lexical_fallback_rescues_far_embedded_keyword_match(self, real_oxigraph_db):
        """The real bug: a node whose text genuinely answers the query
        (exact keyword overlap) but whose embedding lands far outside the
        0.30 floor must still surface via the lexical fallback."""
        db = real_oxigraph_db
        db.write_node("Concept", {
            "concept_id": "c-vegan",
            "text_raw": "vegan diet preferences",
            "confidence": 0.9,
            "pathway_strength": 0.5,
            "embedding": _far_vec(),
        })

        section = await _stage_semantic_context(db, "vegan diet preferences", CONFIG, TIER_CONFIG)

        assert section is not None
        texts = {c["text"] for c in section.content}
        assert "vegan diet preferences" in texts

    async def test_lexical_fallback_still_excludes_flagged_nodes(self, real_oxigraph_db):
        """The B437 exclusions apply to the lexical path too -- a
        flagged-for-review node must not be rescued just because it's a
        keyword match."""
        db = real_oxigraph_db
        db.write_node("Concept", {
            "concept_id": "c-vegan-flagged",
            "text_raw": "vegan diet preferences",
            "confidence": 0.9,
            "flagged_for_review": True,
            "pathway_strength": 0.5,
            "embedding": _far_vec(),
        })

        section = await _stage_semantic_context(db, "vegan diet preferences", CONFIG, TIER_CONFIG)

        assert section is None

    async def test_lexical_fallback_does_not_duplicate_vector_hit(self, real_oxigraph_db):
        """A node close enough to clear the vector-search floor on its
        own must not also be appended a second time via the lexical
        fallback."""
        db = real_oxigraph_db
        db.write_node("Concept", {
            "concept_id": "c-close",
            "text_raw": "vegan diet preferences",
            "confidence": 0.9,
            "pathway_strength": 0.5,
            "embedding": _query_vec(),
        })

        section = await _stage_semantic_context(db, "vegan diet preferences", CONFIG, TIER_CONFIG)

        assert section is not None
        assert len(section.content) == 1

    async def test_lexical_fallback_never_outranks_a_real_vector_match(self, real_oxigraph_db):
        """A genuinely close vector match must still rank first -- the
        lexical fallback's fixed synthetic distance (just under the
        floor) must not let a keyword-only hit jump ahead of it."""
        db = real_oxigraph_db
        db.write_node("Concept", {
            "concept_id": "c-real-match",
            "text_raw": "the real closest match",
            "confidence": 0.9,
            "pathway_strength": 0.5,
            "embedding": _query_vec(),
        })
        db.write_node("Concept", {
            "concept_id": "c-lexical-only",
            "text_raw": "vegan diet preferences",
            "confidence": 0.9,
            "pathway_strength": 0.5,
            "embedding": _far_vec(),
        })

        section = await _stage_semantic_context(
            db, "vegan diet preferences the real closest match", CONFIG, TIER_CONFIG
        )

        assert section is not None
        assert section.content[0]["text"] == "the real closest match"
