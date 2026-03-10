"""
mcp_engine/loop/orchestrator.py — Gated Consolidation Loop (Steps 1–7, M4)

Runs the 9-step loop on a single message.
Called from the background worker in brain_daemon.py (never blocks notify_turn).

Loop:
  Step 1   → NER (spaCy)
  Step 1b  → Verb pattern relation extraction
  Step 2   → gist hybrid classification (System 1/2)
  Step 3   → schema.org routing
  Step 3b  → Ollama relation extraction with type context
  Step 4   → Pattern matching + confidence gating (Cocktail Party)
  Step 5   → Dual-scope candidate retrieval (Availability Heuristic)
  Step 6   → Constrained contradiction arbitration (gray zone only)
  Step 7   → Pathway update (Hebbian reinforcement) + CO_OCCURS_WITH
"""

import uuid
from datetime import datetime, timezone

from mcp_engine.loop.step1_ner       import extract_entities
from mcp_engine.loop.step1b_relations import extract_relations
from mcp_engine.loop.step2_gist      import classify_concept
from mcp_engine.loop.step3_schema_org import route_to_schema_org
from mcp_engine.loop.step3b_relations import extract_semantic_relations
from mcp_engine.loop.step4_pattern   import classify_artifact
from mcp_engine.loop.step5_retrieval import (
    retrieve_candidates, MATCH_THRESHOLD, GRAY_ZONE_UPPER
)
from mcp_engine.loop.step6_arbitration import arbitrate
from mcp_engine.loop.step7_pathway   import (
    apply_additive, apply_contradiction, write_co_occurs_with
)
from mcp_engine.graph import embeddings as emb


async def run_loop(message_id: str, text: str, db, llm_client,
                   config: dict, centroids: dict) -> dict:
    """
    Run the Gated Consolidation Loop on a single message.
    Returns a summary dict of what was created/stored.
    Designed to run as a background asyncio task — does not block notify_turn.
    """
    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )
    spacy_model = config.get("nlp", {}).get("spacy_model", "en_core_web_md")
    co_threshold = config.get("hebbian", {}).get("co_occurrence_threshold", 10)
    now = datetime.now(timezone.utc).isoformat()

    summary = {
        "message_id":        message_id,
        "entities_found":    0,
        "relations_found":   0,
        "concepts_stored":   0,
        "additive_updates":  0,
        "contradictions":    0,
        "noise_count":       0,
    }

    # ------------------------------------------------------------------
    # Step 1 — NER (spaCy)
    # ------------------------------------------------------------------
    doc, entities = extract_entities(text, model_name=spacy_model)
    summary["entities_found"] = len(entities)

    if not entities:
        return summary  # nothing to process

    # ------------------------------------------------------------------
    # Step 1b — Verb Pattern Relation Extraction
    # ------------------------------------------------------------------
    step1b_relations = extract_relations(doc, entities)
    summary["relations_found"] += len(step1b_relations)

    for rel in step1b_relations:
        await _store_relation(rel, db, now)

    # ------------------------------------------------------------------
    # Steps 2, 3, 3b — Per-entity classification + routing
    # ------------------------------------------------------------------
    typed_entities = []

    for entity in entities:
        gist_result = classify_concept(
            entity["text"], embedding_model, centroids, llm_client
        )

        if gist_result["system"] == "noise":
            summary["noise_count"] += 1
            continue

        gist_class = gist_result["gist_class"]
        schema_result = route_to_schema_org(gist_class, entity.get("label"))
        schema_org_type = schema_result["schema_org_type"]

        typed_entities.append({
            **entity,
            "gist_class":      gist_class,
            "schema_org_type": schema_org_type,
            "gist_confidence": gist_result["confidence"],
        })

    # Step 3b — Ollama semantic relation extraction (triggered if 1b found nothing)
    if len(typed_entities) > 1 and not step1b_relations:
        step3b_relations = extract_semantic_relations(typed_entities, text, llm_client)
        summary["relations_found"] += len(step3b_relations)
        for rel in step3b_relations:
            await _store_relation(rel, db, now)

    # ------------------------------------------------------------------
    # Steps 4–7 — Pattern matching → retrieval → arbitration → pathway
    # ------------------------------------------------------------------
    # concept_ids collects all concepts that cleared the noise floor
    # (both newly stored AND matched via additive) for CO_OCCURS_WITH wiring.
    concept_ids = []

    for entity in typed_entities:
        # Step 4 — Pattern Matching + Confidence Gating
        step4_result = classify_artifact(
            text,
            entity.get("gist_class"),
            entity.get("schema_org_type"),
        )

        if not step4_result["should_proceed"]:
            summary["noise_count"] += 1
            continue

        # Embed this entity for Step 5 retrieval
        vector = emb.embed(entity["text"], model_name=embedding_model)

        # Step 5 — Candidate Retrieval
        # Pass a placeholder exclude_id=""; real new concept not created yet
        candidates = retrieve_candidates(vector, exclude_id="", db)

        top = candidates[0] if candidates else None

        if top and top["similarity"] > GRAY_ZONE_UPPER:
            # Strong match → additive update, no new node
            result = await apply_additive(top["concept_id"], db, now)
            if result.get("action") == "additive":
                concept_ids.append(top["concept_id"])
                summary["additive_updates"] += 1

        elif top and top["similarity"] >= MATCH_THRESHOLD:
            # Gray zone → Step 6 arbitration
            arb = arbitrate(
                {**entity, "text": entity["text"]},
                candidates,
                text,
                llm_client,
            )

            if arb["classification"] == "additive":
                result = await apply_additive(top["concept_id"], db, now)
                if result.get("action") == "additive":
                    concept_ids.append(top["concept_id"])
                    summary["additive_updates"] += 1

            elif arb["classification"] == "contradiction":
                # Create new concept node, then draw DEPRECATED_BY
                concept_id = await _store_concept(
                    entity, step4_result, vector, embedding_model, db, now
                )
                if concept_id:
                    summary["concepts_stored"] += 1
                    concept_ids.append(concept_id)
                    await apply_contradiction(
                        concept_id, top["concept_id"], message_id, db, now
                    )
                    summary["contradictions"] += 1
                    if not step4_result["confidence_low"]:
                        await _reify_concept(
                            concept_id, step4_result["artifact_type"],
                            entity, vector, embedding_model, db, now
                        )

            else:
                # "uncertain" — store both, both remain confidence_low
                concept_id = await _store_concept(
                    entity, step4_result, vector, embedding_model, db, now
                )
                if concept_id:
                    summary["concepts_stored"] += 1
                    concept_ids.append(concept_id)
                    # uncertain does not trigger REIFIED_AS (confidence_low stays true)

        else:
            # No match — store as new concept
            concept_id = await _store_concept(
                entity, step4_result, vector, embedding_model, db, now
            )
            if concept_id:
                summary["concepts_stored"] += 1
                concept_ids.append(concept_id)
                if not step4_result["confidence_low"]:
                    await _reify_concept(
                        concept_id, step4_result["artifact_type"],
                        entity, vector, embedding_model, db, now
                    )

    # Step 7 — CO_OCCURS_WITH for all concepts from this message
    if len(concept_ids) > 1:
        min_conf = 0.60  # noise floor minimum
        await write_co_occurs_with(concept_ids, min_conf, db, now, co_threshold)

    return summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _store_concept(entity: dict, step4: dict, vector: list[float],
                          embedding_model: str, db, now: str) -> str | None:
    """Create a Concept node for an entity that cleared the noise floor."""
    concept_id = str(uuid.uuid4())
    confidence = step4["confidence"]

    try:
        await db.execute_write(
            """
            CREATE (c:Concept {
                concept_id:       $concept_id,
                text_raw:         $text_raw,
                embedding:        $embedding,
                embedding_model:  $embedding_model,
                embedding_dim:    $embedding_dim,
                gist_class:       $gist_class,
                schema_org_type:  $schema_org_type,
                confidence:       $confidence,
                confidence_low:   $confidence_low,
                pathway_strength: $pathway_strength,
                archived:         false,
                created_at:       $created_at
            })
            """,
            {
                "concept_id":      concept_id,
                "text_raw":        entity["text"],
                "embedding":       vector,
                "embedding_model": embedding_model,
                "embedding_dim":   len(vector),
                "gist_class":      entity.get("gist_class", ""),
                "schema_org_type": entity.get("schema_org_type", ""),
                "confidence":      confidence,
                "confidence_low":  step4["confidence_low"],
                "pathway_strength": max(confidence, 0.50),
                "created_at":      now,
            }
        )
        return concept_id
    except Exception:
        return None


async def _reify_concept(concept_id: str, artifact_type: str, entity: dict,
                          vector: list[float], embedding_model: str, db, now: str):
    """Create specific artifact node + REIFIED_AS edge for >90% confident concepts."""
    import uuid as _uuid

    type_map = {
        "decision":    ("Decision",    "decision_id"),
        "constraint":  ("Constraint",  "constraint_id"),
        "requirement": ("Requirement", "requirement_id"),
        "action_item": ("ActionItem",  "action_item_id"),
    }

    if artifact_type not in type_map:
        return

    node_label, pk_field = type_map[artifact_type]
    artifact_id = str(_uuid.uuid4())

    try:
        await db.execute_write(
            f"""
            CREATE (a:{node_label} {{
                {pk_field}:        $artifact_id,
                text_raw:          $text_raw,
                embedding:         $embedding,
                embedding_model:   $embedding_model,
                embedding_dim:     $embedding_dim,
                confidence:        1.0,
                confidence_low:    false,
                pathway_strength:  $confidence,
                archived:          false,
                created_at:        $created_at
            }})
            """,
            {
                "artifact_id":     artifact_id,
                "text_raw":        entity["text"],
                "embedding":       vector,
                "embedding_model": embedding_model,
                "embedding_dim":   len(vector),
                "confidence":      1.0,
                "created_at":      now,
            }
        )
        await db.execute_write(
            f"""
            MATCH (c:Concept {{concept_id: $concept_id}}),
                  (a:{node_label} {{{pk_field}: $artifact_id}})
            CREATE (c)-[:REIFIED_AS]->(a)
            """,
            {"concept_id": concept_id, "artifact_id": artifact_id}
        )
    except Exception:
        pass


async def _store_relation(rel: dict, db, now: str):
    """
    Store a named semantic relation between two Concept nodes.
    Uses MERGE on text_raw to avoid duplicate Concept creation.
    """
    rel_type = rel["relation_type"]
    valid_types = {
        "REQUIRES", "ENABLES", "REPLACES", "CONTRADICTS", "PART_OF",
        "CHOSEN_OVER", "IMPLEMENTS", "EXTENDS", "ALTERNATIVE_TO",
    }
    if rel_type not in valid_types:
        return

    try:
        await db.execute_write(
            f"""
            MERGE (h:Concept {{text_raw: $head}})
            ON CREATE SET h.concept_id = $head_id, h.confidence = 0.70,
                          h.confidence_low = true, h.pathway_strength = 0.70,
                          h.archived = false, h.created_at = $now
            MERGE (t:Concept {{text_raw: $tail}})
            ON CREATE SET t.concept_id = $tail_id, t.confidence = 0.70,
                          t.confidence_low = true, t.pathway_strength = 0.70,
                          t.archived = false, t.created_at = $now
            MERGE (h)-[r:{rel_type}]->(t)
            ON CREATE SET r.confidence = $confidence, r.inferred_by = $inferred_by,
                          r.inferred_at = $now
            """,
            {
                "head":        rel["head"],
                "head_id":     str(uuid.uuid4()),
                "tail":        rel["tail"],
                "tail_id":     str(uuid.uuid4()),
                "confidence":  rel.get("confidence", 0.85),
                "inferred_by": rel.get("inferred_by", "system"),
                "now":         now,
            }
        )
    except Exception:
        pass
