"""
mcp_engine/loop/orchestrator.py — Gated Consolidation Loop (Steps 1–7, M4)

Runs the 9-step loop on a single message.
Called from the background worker in brain_daemon.py (never blocks notify_turn).

Loop:
  Step 1   → NER (ONNX, B387)
  Step 1b  → Verb pattern relation extraction
  Step 2   → gist hybrid classification (System 1/2)
  Step 3   → schema.org routing
  Step 3b  → Ollama relation extraction with type context
  Step 4   → Pattern matching + confidence gating (Cocktail Party)
  Step 5   → Dual-scope candidate retrieval (Availability Heuristic)
  Step 6   → Constrained contradiction arbitration (gray zone only)
  Step 7   → Pathway update (Hebbian reinforcement) + CO_OCCURS_WITH
"""

from __future__ import annotations
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from campy.brain.temporal_lobe.loop.step1_ner       import extract_entities

_logger = logging.getLogger(__name__)
from campy.brain.temporal_lobe.loop.step1b_relations import extract_relations
from campy.brain.temporal_lobe.loop.step2_gist      import classify_concept
from campy.brain.temporal_lobe.loop.step3_schema_org import route_to_schema_org
from campy.brain.temporal_lobe.loop.step3b_relations import extract_semantic_relations
from campy.brain.temporal_lobe.loop.step4_pattern   import classify_artifact, compute_salience_multiplier, NOISE_FLOOR
from campy.brain.temporal_lobe.loop.step5_retrieval import (
    retrieve_candidates, MATCH_THRESHOLD, GRAY_ZONE_UPPER
)
from campy.brain.temporal_lobe.loop.step6_arbitration import arbitrate
from campy.brain.temporal_lobe.loop.step7_pathway   import (
    apply_additive, apply_contradiction, write_co_occurs_with,
    rescore_nearby_low_confidence, create_decision_chain,
)
from campy.brain.temporal_lobe.loop.step4b_associative import check_associative_triggers  # Phase 3
from campy.brain.temporal_lobe.loop.step7_5_lesson import extract_lessons  # B11
from campy.brain.temporal_lobe.loop.anomaly_detection import check_anomalies, store_anomaly_flag  # B12
from campy.brain.hippocampus.graph import embeddings as emb
from campy.brain.llm.provider import create_llm_client_for_step  # B16


async def run_loop(message_id: str, text: str, db, llm_client,
                   config: dict, centroids: dict,
                   role: str = "user",
                   session_id: str = "unknown",
                   precomputed: dict | None = None) -> dict:
    """
    Run the Gated Consolidation Loop on a single message.
    Returns a summary dict of what was created/stored.
    Designed to run as a background asyncio task — does not block notify_turn.

    role: "user" or "assistant" — assistant turns get a confidence cap
    in Step 4 to prevent hallucination poisoning of the graph.

    session_id: passed through to _reify_concept so ESTABLISHED_IN edges
    (artifact → Session) are written for all artifact types (B43).

    precomputed: optional dict to bypass expensive LLM steps for stable
    knowledge. Expected schema:
    {
        "entities": [{"text": str, "gist_class": str, "schema_org_type": str, "label": str}],
        "relations": [{"head": str, "relation_type": str, "tail": str, "confidence": float}]
    }
    """
    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )
    # B387: "spacy_model" config key kept for backward compatibility with
    # existing campy.toml/sidequests.toml files -- extract_entities() no
    # longer uses it (the ONNX NER model is a single fixed choice), but a
    # stale config key here must not become a KeyError for anyone upgrading.
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
        "reified":           0,
        "lessons_found":     0,
        "anomalies_detected": 0,  # B12
        "triggers_bound":    0,   # Phase 3: Step 4b auto-bindings
        "salience_rescues":  0,   # Emotion sense: amygdala noise-floor rescues
    }

    # ------------------------------------------------------------------
    # B16 — Resolve per-step LLM clients (task-based model routing)
    # Falls back to the default llm_client if no override is configured.
    # ------------------------------------------------------------------
    llm_step2 = create_llm_client_for_step(config, "step2_gist") or llm_client
    llm_step3b = create_llm_client_for_step(config, "step3b_relations") or llm_client
    llm_step6 = create_llm_client_for_step(config, "step6_arbitration") or llm_client

    # ------------------------------------------------------------------
    # Step 1, 1b, 2, 3, 3b — Entity and Relation extraction
    # B108: Bypass if precomputed data is supplied
    # ------------------------------------------------------------------
    typed_entities = []
    deferred_relations = []

    if precomputed:
        # Use precomputed entities
        for ent in precomputed.get("entities", []):
            text_raw = ent["text"]
            gist_class = ent["gist_class"]
            # Re-embed locally to ensure compatibility with current model
            vector = await asyncio.to_thread(emb.embed, text_raw, model_name=embedding_model)
            typed_entities.append({
                "text": text_raw,
                "label": ent.get("label", "PRODUCT"),
                "gist_class": gist_class,
                "schema_org_type": ent.get("schema_org_type", ""),
                "gist_confidence": 0.95,
                "vector": vector,
            })
        summary["entities_found"] = len(typed_entities)

        # Use precomputed relations
        for rel in precomputed.get("relations", []):
            deferred_relations.append({
                "head": rel["head"],
                "relation_type": rel["relation_type"],
                "tail": rel["tail"],
                "confidence": rel.get("confidence", 0.95),
                "inferred_by": "precomputed",
            })
        summary["relations_found"] = len(deferred_relations)

    else:
        # Standard Loop Flow
        # Step 1 — NER (ONNX, B387)
        doc, entities = extract_entities(text, model_name=spacy_model)
        summary["entities_found"] = len(entities)

        if not entities:
            return summary  # nothing to process

        # Step 1b — Verb Pattern Relation Extraction
        step1b_relations = extract_relations(doc, entities)

        # Steps 2, 3 — Per-entity classification + routing
        for entity in entities:
            gist_result = classify_concept(
                entity["text"], embedding_model, centroids, llm_step2,
                context=text,
            )

            if gist_result["system"] == "noise":
                summary["noise_count"] += 1
                continue

            gist_class = gist_result["gist_class"]
            schema_result = route_to_schema_org(gist_class, entity.get("label"))
            schema_org_type = schema_result["schema_org_type"]

            if gist_result["system"] == "2" and gist_class:
                await _save_gist_example(
                    entity["text"], gist_result["vector"], gist_class, db, now
                )

            typed_entities.append({
                **entity,
                "gist_class":      gist_class,
                "schema_org_type": schema_org_type,
                "gist_confidence": gist_result["confidence"],
                "vector":          gist_result.get("vector"),
            })

        # Step 1b filtering
        surviving_texts = {e["text"].lower() for e in typed_entities}
        surviving_step1b = [
            r for r in step1b_relations
            if (r["head"].lower() in surviving_texts or r["tail"].lower() in surviving_texts)
        ]
        deferred_relations = list(surviving_step1b)

        # Step 3b — Semantic relation extraction
        step1b_covered_pairs = {
            (r["head"].lower(), r["tail"].lower()) for r in surviving_step1b
        }
        if len(typed_entities) > 1:
            uncovered_pairs_exist = any(
                (e1["text"].lower(), e2["text"].lower()) not in step1b_covered_pairs
                for i, e1 in enumerate(typed_entities)
                for e2 in typed_entities[i+1:]
            )
            if uncovered_pairs_exist:
                step3b_relations = extract_semantic_relations(typed_entities, text, llm_step3b)
                for rel in step3b_relations:
                    pair = (rel["head"].lower(), rel["tail"].lower())
                    if pair not in step1b_covered_pairs:
                        deferred_relations.append(rel)
        
        summary["relations_found"] = len(deferred_relations)

    # ------------------------------------------------------------------
    # Steps 4–7 — Pattern matching → retrieval → arbitration → pathway
    # ------------------------------------------------------------------
    # concept_ids collects all concepts that cleared the noise floor
    # (both newly stored AND matched via additive) for CO_OCCURS_WITH wiring.
    concept_ids = []

    for entity in typed_entities:
        # Step 4 — Pattern Matching + Confidence Gating
        # L5 fix: pass entity_text so signal matching uses entity sentence context.
        # ISSUE-024 fix: pass role so assistant turns get confidence cap.
        step4_result = classify_artifact(
            text,
            entity.get("gist_class"),
            entity.get("schema_org_type"),
            entity_text=entity.get("text"),
            role=role,
        )

        # Emotion sense — 7th Cocktail Party sense (Amygdala)
        # Compute salience from full message text (emotional cues are
        # message-global, not entity-scoped like other senses).
        salience = compute_salience_multiplier(text)

        # Amygdala rescue: emotional content in the 0.45–0.60 dead zone
        # gets pulled above the noise floor. Below 0.45 stays noise —
        # emotion alone can't create memories from nothing.
        if (not step4_result["should_proceed"]
                and step4_result["confidence"] >= 0.45
                and salience >= 1.3):
            step4_result = {
                "artifact_type":  step4_result["artifact_type"] or "decision",
                "confidence":     NOISE_FLOOR + 0.02,  # 0.62
                "confidence_low": True,
                "should_proceed": True,
            }
            summary["salience_rescues"] = summary.get("salience_rescues", 0) + 1

        if not step4_result["should_proceed"]:
            summary["noise_count"] += 1
            continue

        # Step 4b — Associative Pattern Check (Anticipatory Engine)
        # Check if this entity matches stored Lessons/Procedures that need triggers.
        # Only runs when message contains error/action signals — near-zero cost otherwise.
        step4b_vector = entity.get("vector")
        if step4b_vector:
            step4b_result = await check_associative_triggers(
                entity_text=entity["text"],
                entity_vector=step4b_vector,
                full_message=text,
                db=db,
                config=config,
            )
            summary["triggers_bound"] += step4b_result["triggers_bound"]

        # O1 fix: reuse vector from Step 2 (already embedded there).
        vector = entity.get("vector")
        if not vector:
            vector = await asyncio.to_thread(emb.embed, entity["text"], model_name=embedding_model)

        # B12 — Anomaly Detection (before candidate retrieval)
        anomaly_result = await check_anomalies(entity["text"], vector, db, config)

        # Step 5 — Candidate Retrieval
        # L8 fix: pass already-created concept_ids from this run as exclusions
        # so entities earlier in the same message don't match each other as
        # "existing" concepts. retrieve_candidates uses the first exclude_id
        # for self-exclusion — pass the full list to skip all same-run concepts.
        candidates = retrieve_candidates(vector, "", db,
                                         exclude_ids=concept_ids)

        top = candidates[0] if candidates else None

        if top and top["similarity"] > GRAY_ZONE_UPPER:
            # Strong match → additive update, no new node
            result = await apply_additive(top["concept_id"], db, now)
            if result.get("action") == "additive":
                concept_ids.append(top["concept_id"])
                summary["additive_updates"] += 1
                # O7: re-score nearby confidence_low nodes
                await rescore_nearby_low_confidence(top["concept_id"], db)

        elif top and top["similarity"] >= MATCH_THRESHOLD:
            # Gray zone → Step 6 arbitration
            arb = arbitrate(
                {**entity, "text": entity["text"]},
                candidates,
                text,
                llm_step6,  # B16: per-step client (benefits most from frontier models)
            )

            if arb["classification"] == "additive":
                result = await apply_additive(top["concept_id"], db, now)
                if result.get("action") == "additive":
                    concept_ids.append(top["concept_id"])
                    summary["additive_updates"] += 1
                    # O7: re-score nearby confidence_low nodes
                    await rescore_nearby_low_confidence(top["concept_id"], db)

            elif arb["classification"] == "contradiction":
                # Create new concept node, then draw DEPRECATED_BY
                concept_id = await _store_concept(
                    entity, step4_result, vector, embedding_model, db, now,
                    anomaly_result=anomaly_result, salience=salience,
                )
                if concept_id:
                    summary["concepts_stored"] += 1
                    concept_ids.append(concept_id)
                    # B12: Store anomaly edges if flagged
                    if anomaly_result and anomaly_result.get("has_anomaly"):
                        for anomaly in anomaly_result["anomalies"]:
                            await store_anomaly_flag(
                                db, concept_id, "Concept", anomaly["type"],
                                anomaly["target_id"], anomaly["confidence"]
                            )
                            summary["anomalies_detected"] += 1
                    await apply_contradiction(
                        concept_id, top["concept_id"], message_id, db, now
                    )
                    summary["contradictions"] += 1
                    # O7: re-score nearby confidence_low nodes
                    await rescore_nearby_low_confidence(concept_id, db)
                    if not step4_result["confidence_low"]:
                        await _reify_concept(
                            concept_id, step4_result["artifact_type"],
                            entity, vector, embedding_model, db, now,
                            confidence=step4_result["confidence"],
                            message_id=message_id,
                            session_id=session_id,
                        )
                        summary["reified"] += 1
                        if summary["reified"] == 1 and llm_client is not None:
                            from campy.brain.hippocampus.quest import maybe_synthesize_purpose
                            await maybe_synthesize_purpose(
                                db, message_id, entity["text"],
                                llm_client, embedding_model, now,
                            )

            else:
                # "uncertain" — store both, both remain confidence_low
                concept_id = await _store_concept(
                    entity, step4_result, vector, embedding_model, db, now,
                    anomaly_result=anomaly_result, salience=salience,
                )
                if concept_id:
                    summary["concepts_stored"] += 1
                    concept_ids.append(concept_id)
                    # B12: Store anomaly edges if flagged
                    if anomaly_result and anomaly_result.get("has_anomaly"):
                        for anomaly in anomaly_result["anomalies"]:
                            await store_anomaly_flag(
                                db, concept_id, "Concept", anomaly["type"],
                                anomaly["target_id"], anomaly["confidence"]
                            )
                            summary["anomalies_detected"] += 1
                    # uncertain does not trigger REIFIED_AS (confidence_low stays true)
                    # B158: create a DisambiguationEvent for human curation
                    try:
                        ref_id = None
                        if arb.get("referenced_node_ids"):
                            ref_id = arb["referenced_node_ids"][0]
                        await _create_disambiguation_event(db, concept_id, ref_id,
                                                           top["similarity"] if top else 0.0,
                                                           now)
                    except Exception:
                        _logger.exception("Failed to create DisambiguationEvent")

        else:
            # No match — store as new concept
            concept_id = await _store_concept(
                entity, step4_result, vector, embedding_model, db, now,
                anomaly_result=anomaly_result, salience=salience,
            )
            if concept_id:
                summary["concepts_stored"] += 1
                concept_ids.append(concept_id)
                # B12: Store anomaly edges if flagged
                if anomaly_result and anomaly_result.get("has_anomaly"):
                    for anomaly in anomaly_result["anomalies"]:
                        await store_anomaly_flag(
                            db, concept_id, "Concept", anomaly["type"],
                            anomaly["target_id"], anomaly["confidence"]
                        )
                        summary["anomalies_detected"] += 1
                if not step4_result["confidence_low"]:
                    await _reify_concept(
                        concept_id, step4_result["artifact_type"],
                        entity, vector, embedding_model, db, now,
                        confidence=step4_result["confidence"],
                        message_id=message_id,
                        session_id=session_id,
                    )
                    summary["reified"] += 1
                    if summary["reified"] == 1 and llm_client is not None:
                        from campy.brain.hippocampus.quest import maybe_synthesize_purpose
                        await maybe_synthesize_purpose(
                            db, message_id, entity["text"],
                            llm_client, embedding_model, now,
                        )

    # Step 7 — CO_OCCURS_WITH for all concepts from this message
    if len(concept_ids) > 1:
        min_conf = 0.60  # noise floor minimum
        max_pairs = int(config.get("loop", {}).get("max_co_occurrence_pairs", 45))
        await write_co_occurs_with(concept_ids, min_conf, db, now, co_threshold,
                                   max_pairs=max_pairs)

    # Step 7.5 — Lesson extraction (indicator-based)
    lesson_result = await extract_lessons(
        message_id, text, db, llm_client, config, session_id=session_id
    )
    # Phase 3: extract_lessons now returns list[str] of IDs; handle both old and new
    summary["lessons_found"] = len(lesson_result) if isinstance(lesson_result, list) else lesson_result

    # B32 fix: flush deferred relations AFTER all Concept nodes are created.
    # _store_relation will ensure both endpoints exist before creating the edge.
    for rel in deferred_relations:
        await _store_relation(rel, db, now, embedding_model=embedding_model)

    return summary


from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.queries import REGISTRY


def _gateway(db) -> GraphGateway:
    if isinstance(db, GraphGateway):
        return db
    return GraphGateway(db, REGISTRY)


async def _create_disambiguation_event(
    db,
    concept_id_a: str,
    concept_id_b: str,
    similarity: float,
    now: str,
) -> None:
    """Create a pending `DisambiguationEvent` linking two concepts for review."""
    if not concept_id_a or not concept_id_b:
        return

    try:
        event_id = str(uuid.uuid4())
        gw = _gateway(db)
        await gw.run(
            "orchestrator.create_disambiguation_event",
            eid=event_id,
            a=concept_id_a,
            b=concept_id_b,
            sim=float(similarity),
            created_at=now,
        )
    except Exception:
        _logger.exception(
            "_create_disambiguation_event failed for %s %s",
            concept_id_a,
            concept_id_b,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _store_concept(entity: dict, step4: dict, vector: list[float],
                          embedding_model: str, db, now: str,
                          anomaly_result: dict | None = None,
                          salience: float = 1.0) -> str | None:
    """
    Create a Concept node for an entity that cleared the noise floor.

    B33 fix: check for exact text_raw duplicate (case-insensitive) before creating.
    The Step 5 vector search catches *similar* concepts but can miss exact-match
    duplicates when the embedding similarity falls below GRAY_ZONE_UPPER (e.g. on
    the first occurrence in a new session). This guard prevents "JWT" creating 3
    separate nodes across 3 sessions.
    If an exact match exists, return the existing concept_id and bump its
    last_accessed_at instead of creating a duplicate.

    B12: anomaly_result from check_anomalies is passed to flag anomalous nodes.
    """
    confidence = step4["confidence"]
    anomaly_type = None
    flagged_for_review = False

    if anomaly_result and anomaly_result.get("has_anomaly"):
        flagged_for_review = True
        if anomaly_result.get("anomalies"):
            # Use the first anomaly type for the node-level field
            anomaly_type = anomaly_result["anomalies"][0]["type"]

    # B33: exact-match dedup before creation
    gw = _gateway(db)
    try:
        existing = gw.run_sync(
            "orchestrator.find_concept_by_exact_text",
            t=entity["text"],
        )
        if existing:
            row = existing[0]
            existing_id = row.get("c.concept_id") if hasattr(row, "get") else row[0]
            existing_ps = row.get("c.pathway_strength") if hasattr(row, "get") else row[1]
            # Bump last_accessed_at and upgrade confidence_low if we're now more confident
            await gw.run(
                "orchestrator.touch_dedup_concept",
                id=existing_id,
                now=now,
                ps=max(confidence * salience, 0.50),
                conf=confidence,
                salience=salience,
            )
            _logger.debug("_store_concept: dedup hit for '%s' → %s", entity["text"], existing_id)
            return existing_id
    except Exception:
        pass  # On error, fall through to create new node

    concept_id = str(uuid.uuid4())
    try:  # noqa: SIM105 — structured logging on failure, return None sentinel
        await gw.run(
            "orchestrator.create_concept",
            concept_id=concept_id,
            text_raw=entity["text"],
            embedding=vector,
            embedding_model=embedding_model,
            embedding_dim=len(vector),
            gist_class=entity.get("gist_class", ""),
            schema_org_type=entity.get("schema_org_type", ""),
            confidence=confidence,
            confidence_low=step4["confidence_low"],
            pathway_strength=max(confidence * salience, 0.50),
            salience_score=salience,
            anomaly_type=anomaly_type,
            flagged_for_review=flagged_for_review,
            created_at=now,
        )
        return concept_id
    except Exception:
        _logger.exception("_store_concept failed for entity '%s'", entity.get("text"))
        return None


async def _reify_concept(concept_id: str, artifact_type: str, entity: dict,
                          vector: list[float], embedding_model: str, db, now: str,
                          confidence: float = 1.0, message_id: str = "",
                          session_id: str = "unknown"):
    """
    Create specific artifact node + REIFIED_AS edge for >90% confident concepts.
    D7 fix: also creates (Message)-[ESTABLISHED]->(artifact) provenance edge.
    B43 fix: also creates (artifact)-[ESTABLISHED_IN]->(Session) provenance edge
    for Decision, Constraint, Requirement, and ActionItem.
    """
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
    art_key = artifact_type.lower()
    gw = _gateway(db)

    try:
        await gw.run(
            f"orchestrator.create_artifact_{art_key}",
            artifact_id=artifact_id,
            text_raw=entity["text"],
            embedding=vector,
            embedding_model=embedding_model,
            embedding_dim=len(vector),
            confidence=confidence,
            pathway_strength=max(confidence, 0.50),
            created_at=now,
        )
        await gw.run(
            f"orchestrator.link_concept_reified_{art_key}",
            concept_id=concept_id,
            artifact_id=artifact_id,
        )
        # D7 fix: create ESTABLISHED provenance edge from Message to artifact.
        # Matches schema: (Message)-[ESTABLISHED]->(Decision | Constraint | ...)
        if message_id:
            try:
                await gw.run(
                    f"orchestrator.link_message_established_{art_key}",
                    mid=message_id,
                    artifact_id=artifact_id,
                )
            except Exception:
                _logger.exception(
                    "ESTABLISHED edge failed for message_id=%s artifact_id=%s",
                    message_id, artifact_id,
                )
        # B43 fix: create ESTABLISHED_IN provenance edge from artifact to Session.
        # Covers Decision, Constraint, Requirement, ActionItem — all reifiable types.
        # This is the session-level "who established this?" audit trail.
        if session_id and session_id != "unknown":
            try:
                await gw.run(
                    f"orchestrator.link_artifact_session_{art_key}",
                    artifact_id=artifact_id,
                    sid=session_id,
                )
            except Exception:
                _logger.exception(
                    "ESTABLISHED_IN edge failed for artifact_id=%s session_id=%s",
                    artifact_id, session_id,
                )
            # B192: link Decisions into a DECISION_CHAIN for timeline reconstruction
            try:
                if node_label == "Decision":
                    await create_decision_chain(artifact_id, session_id, db)
            except Exception:
                _logger.exception("DECISION_CHAIN creation failed for %s", artifact_id)
    except Exception:
        _logger.exception("_reify_concept failed for concept_id=%s type=%s",
                          concept_id, artifact_type)


async def _save_gist_example(text: str, vector: list[float], gist_class: str,
                              db, now: str) -> None:
    """
    M4: Persist a System 2 labeled example to GistExample.
    Background sweep will mean-pool these to update GistClass.centroid.
    """
    try:
        gw = _gateway(db)
        await gw.run(
            "orchestrator.create_gist_example",
            example_id=str(uuid.uuid4()),
            text=text,
            embedding=vector,
            gist_class=gist_class,
            created_at=now,
        )
    except Exception:
        _logger.exception("_save_gist_example failed for class=%s", gist_class)


async def _ensure_concept_exists(text: str, embedding_model: str, db, now: str) -> None:
    """
    B32 fix: Ensure a Concept node exists for the given text_raw.
    If it already exists, do nothing. If it doesn't exist, create a minimal
    confidence_low=True node. This is needed for relation endpoints that are
    noun chunks (not NER entities) — they won't be created by the normal
    Step 4-7 pipeline but need to exist for relation edges to work.

    Uses lookup first to avoid re-embedding if the node already exists.
    """
    gw = _gateway(db)
    # Check if concept already exists (case-insensitive)
    try:
        result = gw.run_sync(
            "orchestrator.find_concept_by_exact_text",
            t=text,
        )
        if result:
            return  # already exists
    except Exception:
        return  # on error, skip creation to avoid cascading failures

    # Create minimal concept node with embedding
    try:
        vector = await asyncio.to_thread(emb.embed, text, model_name=embedding_model)
        await gw.run(
            "orchestrator.create_minimal_concept",
            concept_id=str(uuid.uuid4()),
            text_raw=text,
            embedding=vector,
            embedding_model=embedding_model,
            embedding_dim=len(vector),
            created_at=now,
        )
    except Exception:
        _logger.debug("_ensure_concept_exists skipped for '%s' (may be duplicate)", text)


async def _store_relation(rel: dict, db, now: str,
                           embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"):
    """
    Store a named semantic relation between two Concept nodes.

    B32 fix: If the head or tail Concept doesn't exist yet (e.g., it's a noun
    chunk extracted by step1b rather than a NER entity), create a minimal
    confidence_low Concept node so the edge can be stored. This replaces the
    old "silently skip if not found" behaviour which produced zero graph edges.

    O3 note: Uses case-insensitive matching (toLower) to avoid duplicates
    from different capitalizations of the same entity name.
    """
    rel_type = rel["relation_type"]
    valid_types = {
        "REQUIRES", "ENABLES", "REPLACES", "CONTRADICTS", "PART_OF",
        "CHOSEN_OVER", "IMPLEMENTS", "EXTENDS", "ALTERNATIVE_TO",
    }
    if rel_type not in valid_types:
        return

    # Ensure both endpoints exist before creating the edge
    await _ensure_concept_exists(rel["head"], embedding_model, db, now)
    await _ensure_concept_exists(rel["tail"], embedding_model, db, now)

    try:
        # B32 fix: Kuzu 0.11.3 has issues with merge on relationships when
        # using MATCH+WHERE with toLower(). Use a two-step approach:
        # 1. Look up both node IDs with separate queries
        # 2. create/merge the edge using node IDs directly.
        gw = _gateway(db)
        h_result = gw.run_sync(
            "orchestrator.find_endpoint_concept",
            t=rel["head"],
        )
        t_result = gw.run_sync(
            "orchestrator.find_endpoint_concept",
            t=rel["tail"],
        )

        if not h_result or not t_result:
            _logger.warning("_store_relation: endpoint not found — head=%s tail=%s",
                            rel["head"], rel["tail"])
            return

        head_row = h_result[0]
        tail_row = t_result[0]
        head_id = head_row.get("c.concept_id") if hasattr(head_row, "get") else head_row[0]
        tail_id = tail_row.get("c.concept_id") if hasattr(tail_row, "get") else tail_row[0]

        # Use inline property matching (same pattern as CO_OCCURS_WITH which works)
        # rather than a WHERE clause — Kuzu 0.11.3 merge + WHERE has edge cases
        await gw.run(
            f"orchestrator.merge_semantic_rel_{rel_type.lower()}",
            hid=str(head_id),
            tid=str(tail_id),
            confidence=rel.get("confidence", 0.85),
            inferred_by=rel.get("inferred_by", "system"),
            now=now,
        )
        _logger.debug("_store_relation stored: %s -[%s]-> %s (hid=%s tid=%s)",
                      rel["head"], rel_type, rel["tail"], head_id, tail_id)
    except Exception:
        _logger.exception("_store_relation failed for %s -[%s]-> %s",
                          rel.get("head"), rel.get("relation_type"), rel.get("tail"))
