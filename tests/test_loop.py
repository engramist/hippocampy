"""
Tests for Gated Consolidation Loop steps 1–7.

Run with: python3 -m pytest tests/test_loop.py -v
"""

import pytest
import math
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.dirname(__file__))  # make conftest importable

# Import the SPACY_AVAILABLE flag installed by conftest.py
try:
    from conftest import SPACY_AVAILABLE
except ImportError:
    SPACY_AVAILABLE = False

_needs_spacy = pytest.mark.skipif(
    not SPACY_AVAILABLE,
    reason="spaCy not compatible with this Python version"
)


# ---------------------------------------------------------------------------
# Step 1 — NER
# ---------------------------------------------------------------------------

@_needs_spacy
def test_step1_ner_extracts_entities():
    from campy.brain.temporal_lobe.loop.step1_ner import extract_entities
    doc, entities = extract_entities("Apple released the iPhone 16 in California.")
    assert len(entities) > 0
    texts = [e["text"] for e in entities]
    # spaCy en_core_web_md should catch ORG and GPE
    assert any("Apple" in t or "iPhone" in t or "California" in t for t in texts)


@_needs_spacy
def test_step1_ner_returns_doc_and_list():
    from campy.brain.temporal_lobe.loop.step1_ner import extract_entities
    doc, entities = extract_entities("Google is based in Mountain View.")
    assert hasattr(doc, "ents")         # spaCy Doc
    assert isinstance(entities, list)
    for e in entities:
        assert "text" in e
        assert "label" in e


@_needs_spacy
def test_step1_ner_empty_text():
    from campy.brain.temporal_lobe.loop.step1_ner import extract_entities
    doc, entities = extract_entities("")
    assert entities == []


def test_step1_junk_filter_rejects_box_drawing():
    from campy.brain.temporal_lobe.loop.step1_ner import _is_junk_entity
    assert _is_junk_entity("╮") is True
    assert _is_junk_entity("─────────") is True
    assert _is_junk_entity("│") is True
    assert _is_junk_entity("╭──╮") is True


def test_step1_junk_filter_rejects_uuids():
    from campy.brain.temporal_lobe.loop.step1_ner import _is_junk_entity
    assert _is_junk_entity("1b38edeb-7e6d-4023-8bd8-6d95bd30273b") is True
    assert _is_junk_entity("35997791-1232-4022-bb63-2a4379d0c990") is True


def test_step1_junk_filter_rejects_formatting_artifacts():
    from campy.brain.temporal_lobe.loop.step1_ner import _is_junk_entity
    assert _is_junk_entity("▟▀ Plan") is True     # < 40% alnum
    assert _is_junk_entity("/auth\n  ") is True    # embedded newline
    assert _is_junk_entity("") is True
    assert _is_junk_entity("   ") is True


def test_step1_junk_filter_numbers():
    from campy.brain.temporal_lobe.loop.step1_ner import _is_junk_entity
    assert _is_junk_entity("0.92") is True
    assert _is_junk_entity("03") is True
    assert _is_junk_entity("18") is True
    assert _is_junk_entity("384") is True
    assert _is_junk_entity("1.0") is True


def test_step1_junk_filter_ordinals():
    """ISSUE-026: ordinal words should be filtered as junk."""
    from campy.brain.temporal_lobe.loop.step1_ner import _is_junk_entity
    assert _is_junk_entity("first") is True
    assert _is_junk_entity("Second") is True
    assert _is_junk_entity("1st") is True
    assert _is_junk_entity("3rd") is True


def test_step1_junk_filter_system_terms():
    """ISSUE-026: SideQuests internal vocabulary should be filtered."""
    from campy.brain.temporal_lobe.loop.step1_ner import _is_junk_entity
    assert _is_junk_entity("MainQuest") is True
    assert _is_junk_entity("SideQuest") is True
    assert _is_junk_entity("Brain") is True
    assert _is_junk_entity("current_truth") is True
    assert _is_junk_entity("notify_turn") is True
    # Real entities should still pass
    assert _is_junk_entity("PostgreSQL") is False
    assert _is_junk_entity("SQLAlchemy") is False
    assert _is_junk_entity("JWT") is False


def test_step1_junk_filter_keeps_real_entities():
    from campy.brain.temporal_lobe.loop.step1_ner import _is_junk_entity
    assert _is_junk_entity("PostgreSQL") is False
    assert _is_junk_entity("SQLAlchemy") is False
    assert _is_junk_entity("JWT") is False
    assert _is_junk_entity("REST API") is False
    assert _is_junk_entity("the user database") is False
    assert _is_junk_entity("Google") is False


# ---------------------------------------------------------------------------
# Step 1b — Verb patterns
# ---------------------------------------------------------------------------

@_needs_spacy
def test_step1b_requires_relation():
    from campy.brain.temporal_lobe.loop.step1_ner import extract_entities
    from campy.brain.temporal_lobe.loop.step1b_relations import extract_relations
    doc, entities = extract_entities("Authentication requires a valid token.")
    rels = extract_relations(doc, entities)
    # Should extract at least one REQUIRES relation
    rel_types = [r["relation_type"] for r in rels]
    # T9 fix: assert >= 0 was a tautology and never fails. spaCy's dep parser
    # on this sentence reliably extracts "Authentication"-REQUIRES-"token".
    assert len(rels) >= 1, f"Expected at least one REQUIRES relation, got: {rels}"
    for r in rels:
        assert "head" in r
        assert "tail" in r
        assert "relation_type" in r
        assert "inferred_by" in r
        assert r["inferred_by"] == "system"


@_needs_spacy
def test_step1b_relation_types_are_valid():
    from campy.brain.temporal_lobe.loop.step1b_relations import extract_relations, VALID_RELATION_TYPES
    from campy.brain.temporal_lobe.loop.step1_ner import extract_entities
    doc, entities = extract_entities("React extends the component model.")
    rels = extract_relations(doc, entities)
    for r in rels:
        assert r["relation_type"] in VALID_RELATION_TYPES


# ---------------------------------------------------------------------------
# Step 2 — gist classification
# ---------------------------------------------------------------------------

def test_step2_system1_high_confidence():
    """If centroid similarity is high, classify without LLM."""
    from campy.brain.temporal_lobe.loop.step2_gist import classify_concept, SYSTEM1_THRESHOLD
    from campy.brain.hippocampus.graph import embeddings as emb

    # Build a fake centroid that IS the embedding of "constraint" text
    text = "you must always validate input"
    vector = emb.embed(text)

    # Use just one centroid so it always wins
    centroids = {"Restriction": vector}

    result = classify_concept(text, "sentence-transformers/all-MiniLM-L6-v2",
                              centroids, llm_client=None)
    assert result["gist_class"] == "Restriction"
    assert result["system"] in ("1", "2_degraded")


def test_step2_noise_below_floor():
    """Random noise vector far from all centroids → noise exit."""
    from campy.brain.temporal_lobe.loop.step2_gist import classify_concept
    from campy.brain.hippocampus.graph import embeddings as emb

    # Two very different concepts → low similarity between them
    centroid_text = "mandatory access control policy enforcement"
    query_text    = "banana flavored ice cream"
    centroid_vec  = emb.embed(centroid_text)
    query_vec     = emb.embed(query_text)  # noqa — used only for difference

    # Force a centroid dict where ALL classes have near-zero similarity
    # by using a reversed/orthogonal-ish vector (simple approach: use 0-vector centroid)
    import random
    random.seed(42)
    zero_centroids = {"Restriction": [0.0] * 384}

    result = classify_concept(query_text, "sentence-transformers/all-MiniLM-L6-v2",
                              zero_centroids, llm_client=None)
    assert result["system"] in ("noise", "2_degraded")


def test_step2_llm_fallback_called_in_gray_zone(monkeypatch):
    """
    Gray zone (0.60–0.85) triggers LLM client call.
    T9 fix: use controlled vectors to guarantee gray zone similarity,
    rather than relying on real embedding distances which may vary.
    """
    import math
    from campy.brain.temporal_lobe.loop import step2_gist
    from campy.brain.hippocampus.graph import embeddings as emb

    class MockLLM:
        def __init__(self):
            self.called = False
        def chat(self, messages):
            self.called = True
            return '{"class": "Category", "confidence": 0.78}'

    mock_llm = MockLLM()

    # Build a unit vector and a centroid at exactly 0.35 cosine similarity.
    # Gray zone for all-MiniLM-L6-v2 is 0.25–0.50.
    dim = 384
    unit_vec = [0.0] * dim
    unit_vec[0] = 1.0

    cos_target = 0.35
    gray_centroid = [0.0] * dim
    gray_centroid[0] = cos_target
    gray_centroid[1] = math.sqrt(1.0 - cos_target ** 2)  # already normalized

    # Monkeypatch embed to return our controlled unit vector
    monkeypatch.setattr(emb, "embed", lambda text, model_name=None: unit_vec)

    centroids = {"Category": gray_centroid}
    result = step2_gist.classify_concept(
        "any text", "sentence-transformers/all-MiniLM-L6-v2",
        centroids, llm_client=mock_llm
    )

    # Cosine similarity = 0.35 → gray zone (0.25–0.50) → LLM must be called
    assert mock_llm.called, "LLM should have been called for gray-zone similarity 0.35"
    assert result["gist_class"] == "Category"
    assert result["system"] == "2"
    assert result["confidence"] == pytest.approx(0.78, abs=0.01)


def test_step2_decision_sentence_not_noise():
    """ISSUE-025: decision sentences about tools must not be dropped as noise."""
    from campy.brain.temporal_lobe.loop.step2_gist import classify_concept, NOISE_FLOOR
    from campy.brain.hippocampus.graph import embeddings as emb
    import numpy as np
    from pathlib import Path
    import re

    # Build centroids from seed file (same as daemon does)
    seed_path = Path('campy/data/GistSeedExamples.md')
    seed_text = seed_path.read_text()
    current_class = None
    class_vectors = {}
    for line in seed_text.split('\n'):
        if line.startswith('## '):
            match = re.search(r'gist:(\w+)', line)
            if match:
                current_class = match.group(1)
                class_vectors[current_class] = []
        elif re.match(r'\d+\.', line.strip()) and current_class:
            m = re.search(r'"(.+?)"', line)
            if m:
                class_vectors[current_class].append(emb.embed(m.group(1)))

    centroids = {}
    for cls, vecs in class_vectors.items():
        arr = np.array(vecs)
        mean = arr.mean(axis=0)
        norm = np.linalg.norm(mean)
        centroids[cls] = (mean / norm).tolist() if norm > 0 else mean.tolist()

    result = classify_concept(
        "SQLAlchemy",
        "sentence-transformers/all-MiniLM-L6-v2",
        centroids,
        None,  # no LLM — should still pass noise floor
        context="We decided to use SQLAlchemy as the ORM because it has better migration support than raw SQL."
    )
    assert result["system"] != "noise", (
        f"Decision sentence classified as noise (score={result['confidence']:.4f}, "
        f"NOISE_FLOOR={NOISE_FLOOR}). Expected System 1 or System 2."
    )


# ---------------------------------------------------------------------------
# Step 3 — schema.org routing
# ---------------------------------------------------------------------------

def test_step3_restriction_routes_to_demand():
    from campy.brain.temporal_lobe.loop.step3_schema_org import route_to_schema_org
    result = route_to_schema_org("Restriction")
    assert result["schema_org_type"] == "Demand"
    assert "description" in result["properties"]


def test_step3_planned_event_routes_to_action():
    from campy.brain.temporal_lobe.loop.step3_schema_org import route_to_schema_org
    result = route_to_schema_org("PlannedEvent")
    assert result["schema_org_type"] == "Action"


def test_step3_agent_person_disambiguation():
    from campy.brain.temporal_lobe.loop.step3_schema_org import route_to_schema_org
    result = route_to_schema_org("Agent", spacy_label="PERSON")
    assert result["schema_org_type"] == "Person"


def test_step3_agent_org_disambiguation():
    from campy.brain.temporal_lobe.loop.step3_schema_org import route_to_schema_org
    result = route_to_schema_org("Agent", spacy_label="ORG")
    assert result["schema_org_type"] == "Organization"


def test_step3_unknown_class_fallback():
    from campy.brain.temporal_lobe.loop.step3_schema_org import route_to_schema_org
    result = route_to_schema_org("NonExistentClass")
    assert result["schema_org_type"] == "Thing"


# ---------------------------------------------------------------------------
# Step 3b — semantic relation extraction (mocked LLM)
# ---------------------------------------------------------------------------

def test_step3b_returns_valid_relation():
    from campy.brain.temporal_lobe.loop.step3b_relations import extract_semantic_relations, SEMANTIC_TYPES

    class MockLLM:
        def chat(self, messages):
            return '{"head": "React", "relation_type": "EXTENDS", "tail": "JavaScript", "confidence": 0.85}'

    entities = [
        {"text": "React",      "label": "PRODUCT", "gist_class": "PhysicalThing", "schema_org_type": "Product"},
        {"text": "JavaScript", "label": "PRODUCT", "gist_class": "PhysicalThing", "schema_org_type": "Product"},
    ]
    rels = extract_semantic_relations(entities, "React extends JavaScript.", MockLLM())
    assert len(rels) == 1
    assert rels[0]["relation_type"] in SEMANTIC_TYPES
    assert rels[0]["inferred_by"] == "LLM"
    assert 0.0 <= rels[0]["confidence"] <= 1.0


def test_step3b_null_response_returns_empty():
    from campy.brain.temporal_lobe.loop.step3b_relations import extract_semantic_relations

    class MockLLM:
        def chat(self, messages):
            return "null"

    entities = [
        {"text": "foo", "label": "ORG", "gist_class": "Agent", "schema_org_type": "Organization"},
        {"text": "bar", "label": "ORG", "gist_class": "Agent", "schema_org_type": "Organization"},
    ]
    rels = extract_semantic_relations(entities, "foo and bar", MockLLM())
    assert rels == []


def test_step3b_no_llm_returns_empty():
    from campy.brain.temporal_lobe.loop.step3b_relations import extract_semantic_relations
    entities = [
        {"text": "A", "label": "ORG", "gist_class": "Agent", "schema_org_type": "Organization"},
        {"text": "B", "label": "ORG", "gist_class": "Agent", "schema_org_type": "Organization"},
    ]
    rels = extract_semantic_relations(entities, "A and B", llm_client=None)
    assert rels == []


def test_step3b_invalid_relation_type_rejected():
    from campy.brain.temporal_lobe.loop.step3b_relations import extract_semantic_relations

    class MockLLM:
        def chat(self, messages):
            return '{"head": "A", "relation_type": "FOOBAR", "tail": "B", "confidence": 0.9}'

    entities = [
        {"text": "A", "label": "PRODUCT", "gist_class": "PhysicalThing", "schema_org_type": "Product"},
        {"text": "B", "label": "PRODUCT", "gist_class": "PhysicalThing", "schema_org_type": "Product"},
    ]
    rels = extract_semantic_relations(entities, "A and B", MockLLM())
    assert rels == []


# ---------------------------------------------------------------------------
# Step 4 — pattern matching + confidence gates
# ---------------------------------------------------------------------------

def test_step4_decision_keywords_hard_lock():
    from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact, HARD_LOCK
    result = classify_artifact(
        "We decided to use PostgreSQL. We agreed on this approach.",
        "Category", "DefinedTerm"
    )
    assert result["should_proceed"] is True
    assert result["artifact_type"] == "decision"
    assert result["confidence"] >= HARD_LOCK
    assert result["confidence_low"] is False


def test_step4_constraint_keywords():
    from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact, NOISE_FLOOR
    result = classify_artifact(
        "You must never store passwords in plaintext.",
        "Restriction", "Demand"
    )
    assert result["should_proceed"] is True
    assert result["artifact_type"] == "constraint"
    assert result["confidence"] >= NOISE_FLOOR


def test_step4_noise_floor_no_keywords_no_prior():
    from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact
    # Agent gist with no keywords has prior confidence 0.40 < NOISE_FLOOR
    result = classify_artifact("John Smith", "Agent", "Person")
    assert result["should_proceed"] is False
    assert result["artifact_type"] == "noise"


def test_step4_restriction_prior_soft_lock():
    from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact, NOISE_FLOOR, HARD_LOCK
    # Restriction gist with no signal keywords → prior 0.80 → soft-lock
    result = classify_artifact(
        "The system will handle this appropriately.",  # no constraint keywords
        "Restriction", "Demand"
    )
    assert result["should_proceed"] is True
    assert result["confidence"] >= NOISE_FLOOR
    assert result["confidence_low"] is True   # below HARD_LOCK


def test_step4_single_decision_signal_with_gist_crosses_hard_lock():
    """One keyword hit + gist agreement should reach full confidence (>0.90)."""
    from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact, HARD_LOCK
    # "Category" gist has prior_type="decision" → gist agrees with keyword signal
    result = classify_artifact(
        "We decided to use SQLAlchemy as the ORM.",
        "Category", "DefinedTerm"
    )
    assert result["should_proceed"] is True
    assert result["artifact_type"] == "decision"
    assert result["confidence"] >= HARD_LOCK
    assert result["confidence_low"] is False


def test_step4_single_constraint_signal_with_gist_crosses_hard_lock():
    """One constraint keyword + Restriction gist should reach full confidence."""
    from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact, HARD_LOCK
    result = classify_artifact(
        "All endpoints must require JWT authentication.",
        "Restriction", "Demand"
    )
    assert result["should_proceed"] is True
    assert result["artifact_type"] == "constraint"
    assert result["confidence"] >= HARD_LOCK
    assert result["confidence_low"] is False


def test_step4_no_gist_class_returns_noise():
    from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact
    result = classify_artifact("some text", None, None)
    assert result["should_proceed"] is False


def test_step4_requirement_keywords():
    from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact
    result = classify_artifact(
        "We need the API to return results within 200ms.",
        "Restriction", "Demand"
    )
    assert result["should_proceed"] is True


def test_step4_action_keywords():
    from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact
    result = classify_artifact(
        "We will implement OAuth next sprint.",
        "PlannedEvent", "Action"
    )
    assert result["should_proceed"] is True
    assert result["artifact_type"] == "action_item"


# ---------------------------------------------------------------------------
# ISSUE-024 — Assistant confidence cap (hallucination poisoning fix)
# ---------------------------------------------------------------------------

def test_step4_assistant_role_capped_below_hard_lock():
    """Assistant turns with strong signals should still be capped at ASSISTANT_CAP."""
    from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact, HARD_LOCK, ASSISTANT_CAP
    # This same input crosses HARD_LOCK for role="user"
    result_user = classify_artifact(
        "We decided to use SQLAlchemy for the ORM.",
        "Category", "DefinedTerm", role="user"
    )
    assert result_user["confidence"] > HARD_LOCK
    assert result_user["confidence_low"] is False

    # But for role="assistant", it's capped
    result_asst = classify_artifact(
        "We decided to use SQLAlchemy for the ORM.",
        "Category", "DefinedTerm", role="assistant"
    )
    assert result_asst["confidence"] <= ASSISTANT_CAP
    assert result_asst["confidence"] < HARD_LOCK
    assert result_asst["confidence_low"] is True
    assert result_asst["should_proceed"] is True  # still enters graph, just tentative


def test_step4_assistant_constraint_stays_tentative():
    """Assistant-originated constraints must not create confirmed Constraint nodes."""
    from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact, HARD_LOCK
    result = classify_artifact(
        "You must always use bcrypt with cost factor 12.",
        "Restriction", "Demand", role="assistant"
    )
    assert result["artifact_type"] == "constraint"
    assert result["confidence"] < HARD_LOCK
    assert result["confidence_low"] is True


def test_step4_plan_signal_extracts_ordered_steps_numbered():
    from campy.brain.temporal_lobe.loop.step4_pattern import has_plan_signal, detect_ordered_plan_steps
    text = """Here is the plan:
1. Gather failing tests
2. Fix schema migration
3. Re-run the suite
"""
    assert has_plan_signal(text) is True
    steps = detect_ordered_plan_steps(text)
    assert len(steps) == 3
    assert steps[0] == "Gather failing tests"


def test_step4_plan_signal_extracts_ordered_steps_bullets():
    from campy.brain.temporal_lobe.loop.step4_pattern import detect_ordered_plan_steps
    text = """My approach:
- first run smoke tests
- then patch tool schemas
- finally run integration checks
"""
    steps = detect_ordered_plan_steps(text)
    assert len(steps) == 3


def test_step4_outcome_success_signal_valence():
    from campy.brain.temporal_lobe.loop.step4_pattern import infer_outcome_valence
    assert infer_outcome_valence("Looks good, approved, all tests pass") == 0.8


def test_step4_outcome_failure_signal_valence():
    from campy.brain.temporal_lobe.loop.step4_pattern import infer_outcome_valence
    assert infer_outcome_valence("That broke production, revert and start over") == -0.8


def test_step4_user_role_unchanged():
    """User turns are not affected by the assistant cap."""
    from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact, HARD_LOCK
    result = classify_artifact(
        "We must never use SQLite in production.",
        "Restriction", "Demand", role="user"
    )
    assert result["confidence"] > HARD_LOCK
    assert result["confidence_low"] is False


def test_step4_default_role_is_user():
    """Omitting role defaults to 'user' — no cap applied."""
    from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact, HARD_LOCK
    result = classify_artifact(
        "We decided to use Redis for caching.",
        "Category", "DefinedTerm"
    )
    assert result["confidence"] > HARD_LOCK
    assert result["confidence_low"] is False


# ---------------------------------------------------------------------------
# Step 5 — candidate retrieval (mock DB)
# ---------------------------------------------------------------------------

def test_step5_filters_below_threshold():
    from campy.brain.temporal_lobe.loop.step5_retrieval import retrieve_candidates, MATCH_THRESHOLD

    class MockDB:
        def vector_search(self, table_name, index_name, embedding, limit):
            return [
                {"node": {"concept_id": "abc", "text_raw": "low sim", "archived": False,
                          "pathway_strength": 0.5, "confidence": 0.7,
                          "gist_class": "Category", "schema_org_type": "Thing",
                          "created_at": "2024-01-01T00:00:00"},
                 "score": 0.50},  # below 0.75
            ]

    result = retrieve_candidates([0.1] * 384, "other-id", MockDB())
    assert result == []  # filtered out


def test_step5_filters_archived_nodes():
    from campy.brain.temporal_lobe.loop.step5_retrieval import retrieve_candidates

    class MockDB:
        def vector_search(self, table_name, index_name, embedding, limit):
            return [
                {"node": {"concept_id": "abc", "text_raw": "archived node", "archived": True,
                          "pathway_strength": 0.8, "confidence": 0.9,
                          "gist_class": "Category", "schema_org_type": "Thing",
                          "created_at": "2024-01-01T00:00:00"},
                 "score": 0.95},
            ]

    result = retrieve_candidates([0.1] * 384, "other-id", MockDB())
    assert result == []  # archived filtered out


def test_step5_filters_self():
    from campy.brain.temporal_lobe.loop.step5_retrieval import retrieve_candidates

    class MockDB:
        def vector_search(self, table_name, index_name, embedding, limit):
            return [
                {"node": {"concept_id": "self-id", "text_raw": "self", "archived": False,
                          "pathway_strength": 1.0, "confidence": 1.0,
                          "gist_class": "Category", "schema_org_type": "Thing",
                          "created_at": "2024-01-01T00:00:00"},
                 "score": 1.0},
            ]

    result = retrieve_candidates([0.1] * 384, "self-id", MockDB())
    assert result == []  # excluded


def test_step5_returns_sorted_by_similarity():
    from campy.brain.temporal_lobe.loop.step5_retrieval import retrieve_candidates

    class MockDB:
        def vector_search(self, table_name, index_name, embedding, limit):
            return [
                {"node": {"concept_id": "low", "text_raw": "low", "archived": False,
                          "pathway_strength": 0.5, "confidence": 0.7,
                          "gist_class": "Category", "schema_org_type": "Thing",
                          "created_at": "2024-01-01T00:00:00"},
                 "score": 0.78},
                {"node": {"concept_id": "high", "text_raw": "high", "archived": False,
                          "pathway_strength": 0.8, "confidence": 0.9,
                          "gist_class": "Category", "schema_org_type": "Thing",
                          "created_at": "2024-01-01T00:00:00"},
                 "score": 0.91},
            ]

    result = retrieve_candidates([0.1] * 384, "other", MockDB())
    assert len(result) == 2
    assert result[0]["similarity"] > result[1]["similarity"]  # descending


# ---------------------------------------------------------------------------
# Step 6 — arbitration (mock LLM)
# ---------------------------------------------------------------------------

def test_step6_additive_classification():
    from campy.brain.temporal_lobe.loop.step6_arbitration import arbitrate

    class MockLLM:
        def chat(self, messages):
            return '{"classification": "additive", "rationale": "same idea", "referenced_index": 1}'

    candidates = [{"concept_id": "abc", "text_raw": "existing", "similarity": 0.82,
                   "pathway_strength": 0.7}]
    result = arbitrate({"text": "new concept"}, candidates, "context", MockLLM())
    assert result["classification"] == "additive"
    assert result["referenced_node_ids"] == ["abc"]


def test_step6_contradiction_classification():
    from campy.brain.temporal_lobe.loop.step6_arbitration import arbitrate

    class MockLLM:
        def chat(self, messages):
            return '{"classification": "contradiction", "rationale": "opposite", "referenced_index": 1}'

    candidates = [{"concept_id": "xyz", "text_raw": "old idea", "similarity": 0.80,
                   "pathway_strength": 0.6}]
    result = arbitrate({"text": "conflicting concept"}, candidates, "ctx", MockLLM())
    assert result["classification"] == "contradiction"
    assert "xyz" in result["referenced_node_ids"]


def test_step6_invalid_classification_falls_back_to_uncertain():
    from campy.brain.temporal_lobe.loop.step6_arbitration import arbitrate

    class MockLLM:
        def chat(self, messages):
            return '{"classification": "BOGUS", "rationale": "??", "referenced_index": null}'

    candidates = [{"concept_id": "abc", "text_raw": "x", "similarity": 0.80,
                   "pathway_strength": 0.5}]
    result = arbitrate({"text": "y"}, candidates, "ctx", MockLLM())
    assert result["classification"] == "uncertain"


def test_step6_no_llm_returns_uncertain():
    from campy.brain.temporal_lobe.loop.step6_arbitration import arbitrate
    candidates = [{"concept_id": "abc", "text_raw": "x", "similarity": 0.80,
                   "pathway_strength": 0.5}]
    result = arbitrate({"text": "y"}, candidates, "ctx", llm_client=None)
    assert result["classification"] == "uncertain"


def test_step6_llm_error_returns_uncertain():
    from campy.brain.temporal_lobe.loop.step6_arbitration import arbitrate

    class BrokenLLM:
        def chat(self, messages):
            raise RuntimeError("connection refused")

    candidates = [{"concept_id": "abc", "text_raw": "x", "similarity": 0.82,
                   "pathway_strength": 0.5}]
    result = arbitrate({"text": "y"}, candidates, "ctx", BrokenLLM())
    assert result["classification"] == "uncertain"


# ---------------------------------------------------------------------------
# Step 7 — pathway strength math
# ---------------------------------------------------------------------------

def test_step7_increment_formula():
    from campy.brain.temporal_lobe.loop.step7_pathway import pathway_strength_increment
    # Strengthen 0.5 with 1 day since access
    result = pathway_strength_increment(0.5, 1.0)
    expected = 0.5 + math.log(1 + 1/1.0)
    assert abs(result - expected) < 1e-10


def test_step7_increment_recent_access_stronger():
    from campy.brain.temporal_lobe.loop.step7_pathway import pathway_strength_increment
    # More recent = bigger increment
    increment_recent = pathway_strength_increment(0.5, 0.001)
    increment_old    = pathway_strength_increment(0.5, 100.0)
    assert increment_recent > increment_old


def test_step7_increment_zero_days_doesnt_crash():
    from campy.brain.temporal_lobe.loop.step7_pathway import pathway_strength_increment
    result = pathway_strength_increment(0.5, 0.0)
    assert result > 0.5


def test_step7_decay_formula():
    from campy.brain.temporal_lobe.loop.step7_pathway import pathway_strength_decay
    result = pathway_strength_decay(1.0, 0.95, 7.0)
    expected = 1.0 * (0.95 ** 7)
    assert abs(result - expected) < 1e-10


@pytest.mark.asyncio
async def test_step7_apply_additive_updates_strength():
    from campy.brain.temporal_lobe.loop.step7_pathway import apply_additive

    calls = []

    class MockQueryResult:
        def __init__(self, row):
            self._row = row
            self._consumed = False
        def has_next(self):
            return not self._consumed
        def get_next(self):
            self._consumed = True
            return self._row

    class MockDB:
        def execute(self, query, params=None):
            # Now returns [pathway_strength, last_accessed_at, created_at]
            return MockQueryResult([0.5, None, "2024-01-01T00:00:00+00:00"])
        async def execute_write(self, query, params=None):
            calls.append(params)

    result = await apply_additive("concept-123", MockDB(), "2024-01-02T00:00:00+00:00")
    assert result["action"] == "additive"
    assert result["new_strength"] > 0.5
    assert len(calls) == 1  # one write call
    assert calls[0]["increment"] > 0  # atomic increment value


@pytest.mark.asyncio
async def test_step7_apply_contradiction_archives_old():
    from campy.brain.temporal_lobe.loop.step7_pathway import apply_contradiction

    writes = []

    class MockQueryResult:
        def has_next(self): return True
        def get_next(self): return [0.7]

    class MockDB:
        def execute(self, query, params=None):
            return MockQueryResult()
        async def execute_write(self, query, params=None):
            writes.append(query)

    result = await apply_contradiction("new-id", "old-id", "msg-id", MockDB(),
                                       "2024-01-02T00:00:00+00:00")
    assert result["action"] == "contradiction"
    assert "merge_event_id" in result

    # Verify the right operations were written
    all_writes = " ".join(writes)
    assert "archived" in all_writes          # old node archived
    assert "DEPRECATED_BY" in all_writes     # deprecation edge
    assert "MergeEvent" in all_writes        # audit node created
    assert "TRIGGERED" in all_writes         # message → merge event
    assert "UPDATES_PATHWAY" in all_writes   # merge event → concept


@pytest.mark.asyncio
async def test_step7_co_occurs_with_single_pair():
    from campy.brain.temporal_lobe.loop.step7_pathway import write_co_occurs_with

    writes = []

    class MockDB:
        async def execute_write(self, query, params=None):
            writes.append(params)

    n = await write_co_occurs_with(["aaa", "bbb"], 0.7, MockDB(),
                                   "2024-01-01T00:00:00+00:00")
    assert n == 1
    # L17 fix: now batched into a single UNWIND call — one write with pairs list
    assert len(writes) == 1
    pairs = writes[0]["pairs"]
    assert len(pairs) == 1
    # Sorted: "aaa" < "bbb" so a_id=aaa, b_id=bbb
    assert pairs[0]["a_id"] == "aaa"
    assert pairs[0]["b_id"] == "bbb"


@pytest.mark.asyncio
async def test_step7_co_occurs_with_three_concepts():
    from campy.brain.temporal_lobe.loop.step7_pathway import write_co_occurs_with

    writes = []

    class MockDB:
        async def execute_write(self, query, params=None):
            writes.append(params)

    # 3 concepts → 3 pairs (n*(n-1)/2)
    n = await write_co_occurs_with(["a", "b", "c"], 0.65, MockDB(), "2024-01-01T00:00:00")
    assert n == 3


@pytest.mark.asyncio
async def test_step7_co_occurs_with_less_than_two():
    from campy.brain.temporal_lobe.loop.step7_pathway import write_co_occurs_with

    class MockDB:
        async def execute_write(self, query, params=None):
            pass

    n = await write_co_occurs_with(["only-one"], 0.7, MockDB(), "2024-01-01T00:00:00")
    assert n == 0
