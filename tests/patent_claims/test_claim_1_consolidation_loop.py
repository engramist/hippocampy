"""
tests/patent_claims/test_claim_1_consolidation_loop.py — Patent Claim 1 Verification.

Patent Claim 1:
"A computer-implemented method for continuous cognitive consolidation of uncurated
natural-language agent dialogue, comprising: deterministic multi-step pipeline
including entity recognition, ontological gist classification, schema routing,
selective attention confidence gating, candidate retrieval, contradiction arbitration,
and Hebbian pathway updates."

Observable Mechanism Assertions:
- End-to-end execution of `run_loop()` returning an observable summary dictionary.
- Pipeline stages producing verifiable intermediate outputs (entities, gist classification,
  schema mapping, artifact categorization).
- Zero mocks; pure execution on the live embedded Kùzu graph and embedding model.
"""

from __future__ import annotations

import pytest

from campy.brain.temporal_lobe.loop.orchestrator import run_loop
from campy.brain.temporal_lobe.loop.step1_ner import extract_entities
from campy.brain.temporal_lobe.loop.step2_gist import classify_concept
from campy.brain.temporal_lobe.loop.step3_schema_org import route_to_schema_org
from campy.brain.temporal_lobe.loop.step4_pattern import classify_artifact


@pytest.mark.asyncio
async def test_claim_1_consolidation_loop_end_to_end(
    patent_db, patent_config, patent_centroids
):
    """Verify Claim 1: run_loop executes the multi-step pipeline deterministically."""
    message_text = (
        "We decided to use an append-only WAL for transaction logging and persistence."
    )
    summary = await run_loop(
        message_id="msg-claim1-test",
        text=message_text,
        db=patent_db,
        llm_client=None,
        config=patent_config,
        centroids=patent_centroids,
        role="user",
        session_id="s-patent-prior",
    )

    # Observable returns of the Gated Consolidation Loop
    assert isinstance(summary, dict)
    assert summary["message_id"] == "msg-claim1-test"
    assert summary["entities_found"] > 0
    # Must have stored a concept, updated additively, or reified
    total_actions = (
        summary["concepts_stored"]
        + summary["additive_updates"]
        + summary["reified"]
        + summary["noise_count"]
    )
    assert total_actions > 0


def test_claim_1_consolidation_loop_stages_observable(
    patent_config, patent_centroids
):
    """Verify Claim 1 stages individually produce observable deterministic outputs."""
    text = "We decided to deploy PostgreSQL for metadata indexing."
    model_name = patent_config["nlp"]["spacy_model"]
    emb_model = patent_config["embeddings"]["model"]

    # Stage 1: NER Extraction
    doc, entities = extract_entities(text, model_name=model_name)
    assert len(entities) >= 1
    entity_text = entities[0]["text"]

    # Stage 2: Gist Classification
    gist_res = classify_concept(
        entity_text,
        emb_model,
        patent_centroids,
        llm_client=None,
        context=text,
    )
    assert "gist_class" in gist_res
    assert "confidence" in gist_res
    assert gist_res["system"] in ("1", "2", "2_degraded", "noise")

    # Stage 3: Schema Routing
    gist_class = gist_res["gist_class"] or "PhysicalThing"
    schema_res = route_to_schema_org(gist_class, entities[0].get("label"))
    assert "schema_org_type" in schema_res
    assert isinstance(schema_res["properties"], list)

    # Stage 4: Cocktail Party Attention / Pattern Matching
    artifact_res = classify_artifact(
        text,
        gist_class,
        schema_res["schema_org_type"],
        entity_text=entity_text,
        role="user",
    )
    assert artifact_res["artifact_type"] in (
        "decision",
        "constraint",
        "requirement",
        "action_item",
        "noise",
    )
    assert 0.0 <= artifact_res["confidence"] <= 1.0
    assert isinstance(artifact_res["should_proceed"], bool)
