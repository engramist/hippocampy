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

from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone

from mcp_engine.loop.step1_ner       import extract_entities

_logger = logging.getLogger(__name__)
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
    apply_additive, apply_contradiction, write_co_occurs_with,
    rescore_nearby_low_confidence,
)
from mcp_engine.graph import embeddings as emb


async def run_loop(message_id: str, text: str, db, llm_client,
                   config: dict, centroids: dict,
                   role: str = "user",
                   session_id: str = "unknown") -> dict:
    """
    Run the Gated Consolidation Loop on a single message.
    Returns a summary dict of what was created/stored.
    Designed to run as a background asyncio task — does not block notify_turn.

    role: "user" or "assistant" — assistant turns get a confidence cap
    in Step 4 to prevent hallucination poisoning of the graph.

    session_id: passed through to _reify_concept so ESTABLISHED_IN edges
    (artifact → Session) are written for all artifact types (B43).
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
        "reified":           0,
    }

    # ------------------------------------------------------------------
    # Precondition: ensure Message node exists (O5 fix)
    # The contradiction audit trail (Message)-[TRIGGERED]->(MergeEvent)
    # requires a Message node. If the caller didn't create one, the
    # MATCH in apply_contradiction silently fails and the audit is lost.
    # ------------------------------------------------------------------
    try:
        result = db.execute(
            "MATCH (m:Message {message_id: $mid}) RETURN m.message_id",
            {"mid": message_id}
        )
        if not result.has_next():
            import logging
            logging.getLogger(__name__).warning(
                f"Message node {message_id} not found — "
                f"contradiction audit trails will be incomplete"
            )
    except Exception:
        pass

    # ------------------------------------------------------------------
    # Step 1 — NER (spaCy)
    # ------------------------------------------------------------------
    doc, entities = extract_entities(text, model_name=spacy_model)
    summary["entities_found"] = len(entities)

    if not entities:
        return summary  # nothing to process

    # ------------------------------------------------------------------
    # Step 1b — Verb Pattern Relation Extraction
    # O4 fix: extract relations but defer storage until AFTER Step 2 noise
    # filtering. Storing relations before noise filtering creates Concept
    # references for entities that may be dropped as noise by Step 2.
    # ------------------------------------------------------------------
    step1b_relations = extract_relations(doc, entities)

    # ------------------------------------------------------------------
    # Steps 2, 3, 3b — Per-entity classification + routing
    # ------------------------------------------------------------------
    typed_entities = []

    for entity in entities:
        gist_result = classify_concept(
            entity["text"], embedding_model, centroids, llm_client,
            context=text,
        )

        if gist_result["system"] == "noise":
            summary["noise_count"] += 1
            continue

        gist_class = gist_result["gist_class"]
        schema_result = route_to_schema_org(gist_class, entity.get("label"))
        schema_org_type = schema_result["schema_org_type"]

        # M4: save System 2 labeled example for centroid improvement.
        # Deferred to DB write (not blocking the hot path result).
        if gist_result["system"] == "2" and gist_class:
            await _save_gist_example(
                entity["text"], gist_result["vector"], gist_class, db, now
            )

        typed_entities.append({
            **entity,
            "gist_class":      gist_class,
            "schema_org_type": schema_org_type,
            "gist_confidence": gist_result["confidence"],
            # O1 fix: carry the embedding from Step 2 to avoid re-embedding
            # at Step 5. Step 2 always computes and returns the vector.
            "vector":          gist_result.get("vector"),
        })

    # O4 fix: now that noise has been filtered, collect Step 1b relations.
    # B32 fix part 1: DEFER actual storage until AFTER Step 4-7 loop creates Concept nodes.
    # B32 fix part 2: No longer filter by "both endpoints must be NER entities" —
    # _store_relation now calls _ensure_concept_exists for noun-chunk endpoints
    # (e.g. "fast graph traversal", "persistent storage") that aren't in the NER
    # entity list but ARE valid relation endpoints from the dep tree.
    # Only filter: head entity must have survived Step 2 noise filter (we trust
    # the NER subject; the object can be any noun chunk).
    surviving_texts = {e["text"].lower() for e in typed_entities}
    surviving_step1b = [
        r for r in step1b_relations
        if r["head"].lower() in surviving_texts  # head must be a known entity
        # tail can be any noun chunk — _ensure_concept_exists handles missing ones
    ]
    summary["relations_found"] += len(surviving_step1b)

    # Step 3b — Ollama semantic relation extraction
    # O6 fix: run for all entity pairs NOT already covered by a Step 1b edge,
    # not just when Step 1b found zero relations entirely.
    # B32 fix: collect for deferred storage, same reason as above.
    step1b_covered_pairs = {
        (r["head"].lower(), r["tail"].lower()) for r in surviving_step1b
    }
    deferred_relations: list[dict] = list(surviving_step1b)  # start with step1b

    if len(typed_entities) > 1:
        uncovered_pairs_exist = any(
            (e1["text"].lower(), e2["text"].lower()) not in step1b_covered_pairs
            for i, e1 in enumerate(typed_entities)
            for e2 in typed_entities[i+1:]
        )
        if uncovered_pairs_exist:
            step3b_relations = extract_semantic_relations(typed_entities, text, llm_client)
            # Only store relations for pairs not already handled by Step 1b
            for rel in step3b_relations:
                pair = (rel["head"].lower(), rel["tail"].lower())
                if pair not in step1b_covered_pairs:
                    summary["relations_found"] += 1
                    deferred_relations.append(rel)

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

        if not step4_result["should_proceed"]:
            summary["noise_count"] += 1
            continue

        # O1 fix: reuse vector from Step 2 (already embedded there).
        vector = entity.get("vector") or emb.embed(entity["text"], model_name=embedding_model)

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
                llm_client,
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
                    entity, step4_result, vector, embedding_model, db, now
                )
                if concept_id:
                    summary["concepts_stored"] += 1
                    concept_ids.append(concept_id)
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
                            from mcp_engine.quest import maybe_synthesize_purpose
                            await maybe_synthesize_purpose(
                                db, message_id, entity["text"],
                                llm_client, embedding_model, now,
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
                        entity, vector, embedding_model, db, now,
                        confidence=step4_result["confidence"],
                        message_id=message_id,
                        session_id=session_id,
                    )
                    summary["reified"] += 1
                    if summary["reified"] == 1 and llm_client is not None:
                        from mcp_engine.quest import maybe_synthesize_purpose
                        await maybe_synthesize_purpose(
                            db, message_id, entity["text"],
                            llm_client, embedding_model, now,
                        )

    # Step 7 — CO_OCCURS_WITH for all concepts from this message
    if len(concept_ids) > 1:
        min_conf = 0.60  # noise floor minimum
        await write_co_occurs_with(concept_ids, min_conf, db, now, co_threshold)

    # B32 fix: flush deferred relations AFTER all Concept nodes are created.
    # _store_relation will ensure both endpoints exist before creating the edge.
    for rel in deferred_relations:
        await _store_relation(rel, db, now, embedding_model=embedding_model)

    return summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _store_concept(entity: dict, step4: dict, vector: list[float],
                          embedding_model: str, db, now: str) -> str | None:
    """
    Create a Concept node for an entity that cleared the noise floor.

    B33 fix: check for exact text_raw duplicate (case-insensitive) before creating.
    The Step 5 vector search catches *similar* concepts but can miss exact-match
    duplicates when the embedding similarity falls below GRAY_ZONE_UPPER (e.g. on
    the first occurrence in a new session). This guard prevents "JWT" creating 3
    separate nodes across 3 sessions.
    If an exact match exists, return the existing concept_id and bump its
    last_accessed_at instead of creating a duplicate.
    """
    confidence = step4["confidence"]

    # B33: exact-match dedup before CREATE
    try:
        existing = db.execute(
            "MATCH (c:Concept) WHERE toLower(c.text_raw) = toLower($t) AND c.archived = false "
            "RETURN c.concept_id, c.pathway_strength LIMIT 1",
            {"t": entity["text"]}
        )
        if existing.has_next():
            row = existing.get_next()
            existing_id, existing_ps = row[0], row[1]
            # Bump last_accessed_at and upgrade confidence_low if we're now more confident
            await db.execute_write(
                "MATCH (c:Concept {concept_id: $id}) "
                "SET c.last_accessed_at = timestamp($now), "
                "    c.pathway_strength = CASE WHEN $ps > c.pathway_strength THEN $ps "
                "                              ELSE c.pathway_strength END, "
                "    c.confidence_low = CASE WHEN $conf >= 0.80 THEN false "
                "                           ELSE c.confidence_low END",
                {"id": existing_id, "now": now,
                 "ps": max(confidence, 0.50), "conf": confidence}
            )
            _logger.debug("_store_concept: dedup hit for '%s' → %s", entity["text"], existing_id)
            return existing_id
    except Exception:
        pass  # On error, fall through to create new node

    concept_id = str(uuid.uuid4())
    try:  # noqa: SIM105 — structured logging on failure, return None sentinel
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
                created_at:       timestamp($created_at),
                last_accessed_at: timestamp($created_at)
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

    try:
        await db.execute_write(
            f"""
            CREATE (a:{node_label} {{
                {pk_field}:        $artifact_id,
                text_raw:          $text_raw,
                embedding:         $embedding,
                embedding_model:   $embedding_model,
                embedding_dim:     $embedding_dim,
                confidence:        $confidence,
                confidence_low:    false,
                pathway_strength:  $pathway_strength,
                archived:          false,
                created_at:        timestamp($created_at)
            }})
            """,
            {
                "artifact_id":      artifact_id,
                "text_raw":         entity["text"],
                "embedding":        vector,
                "embedding_model":  embedding_model,
                "embedding_dim":    len(vector),
                "confidence":       confidence,
                "pathway_strength": max(confidence, 0.50),
                "created_at":       now,
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
        # D7 fix: create ESTABLISHED provenance edge from Message to artifact.
        # Matches schema: (Message)-[ESTABLISHED]->(Decision | Constraint | ...)
        if message_id:
            try:
                await db.execute_write(
                    f"""
                    MATCH (m:Message {{message_id: $mid}}),
                          (a:{node_label} {{{pk_field}: $artifact_id}})
                    MERGE (m)-[:ESTABLISHED]->(a)
                    """,
                    {"mid": message_id, "artifact_id": artifact_id}
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
                await db.execute_write(
                    f"""
                    MATCH (a:{node_label} {{{pk_field}: $artifact_id}}),
                          (s:Session {{session_id: $sid}})
                    MERGE (a)-[:ESTABLISHED_IN]->(s)
                    """,
                    {"artifact_id": artifact_id, "sid": session_id}
                )
            except Exception:
                _logger.exception(
                    "ESTABLISHED_IN edge failed for artifact_id=%s session_id=%s",
                    artifact_id, session_id,
                )
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
        await db.execute_write(
            """
            CREATE (e:GistExample {
                example_id: $example_id,
                text:       $text,
                embedding:  $embedding,
                gist_class: $gist_class,
                source:     'system2',
                created_at: timestamp($created_at)
            })
            """,
            {
                "example_id": str(uuid.uuid4()),
                "text":       text,
                "embedding":  vector,
                "gist_class": gist_class,
                "created_at": now,
            }
        )
    except Exception:
        _logger.exception("_save_gist_example failed for class=%s", gist_class)


async def _ensure_concept_exists(text: str, embedding_model: str, db, now: str) -> None:
    """
    B32 fix: Ensure a Concept node exists for the given text_raw.
    If it already exists, do nothing. If it doesn't exist, create a minimal
    confidence_low=True node. This is needed for relation endpoints that are
    noun chunks (not NER entities) — they won't be created by the normal
    Step 4-7 pipeline but need to exist for MERGE edges to work.

    Uses MATCH first to avoid re-embedding if the node already exists.
    """
    # Check if concept already exists (case-insensitive)
    try:
        result = db.execute(
            "MATCH (c:Concept) WHERE toLower(c.text_raw) = toLower($t) AND c.archived = false "
            "RETURN c.concept_id LIMIT 1",
            {"t": text}
        )
        if result.has_next():
            return  # already exists
    except Exception:
        return  # on error, skip creation to avoid cascading failures

    # Create minimal concept node with embedding
    try:
        vector = emb.embed(text, model_name=embedding_model)
        await db.execute_write(
            """
            CREATE (c:Concept {
                concept_id:       $concept_id,
                text_raw:         $text_raw,
                embedding:        $embedding,
                embedding_model:  $embedding_model,
                embedding_dim:    $embedding_dim,
                gist_class:       '',
                schema_org_type:  '',
                confidence:       0.60,
                confidence_low:   true,
                pathway_strength: 0.60,
                archived:         false,
                created_at:       timestamp($created_at),
                last_accessed_at: timestamp($created_at)
            })
            """,
            {
                "concept_id":      str(uuid.uuid4()),
                "text_raw":        text,
                "embedding":       vector,
                "embedding_model": embedding_model,
                "embedding_dim":   len(vector),
                "created_at":      now,
            }
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
        # B32 fix: Kuzu 0.11.3 has issues with MERGE on relationships when
        # using MATCH+WHERE with toLower(). Use a two-step approach:
        # 1. Look up both node IDs with separate queries
        # 2. CREATE/MERGE the edge using node IDs directly.
        h_result = db.execute(
            "MATCH (c:Concept) WHERE toLower(c.text_raw) = toLower($t) AND c.archived = false "
            "RETURN c.concept_id ORDER BY c.pathway_strength DESC LIMIT 1",
            {"t": rel["head"]}
        )
        t_result = db.execute(
            "MATCH (c:Concept) WHERE toLower(c.text_raw) = toLower($t) AND c.archived = false "
            "RETURN c.concept_id ORDER BY c.pathway_strength DESC LIMIT 1",
            {"t": rel["tail"]}
        )

        if not h_result.has_next() or not t_result.has_next():
            _logger.warning("_store_relation: endpoint not found — head=%s tail=%s",
                            rel["head"], rel["tail"])
            return

        head_id = h_result.get_next()[0]
        tail_id = t_result.get_next()[0]

        # Use inline property matching (same pattern as CO_OCCURS_WITH which works)
        # rather than a WHERE clause — Kuzu 0.11.3 MERGE + WHERE has edge cases
        await db.execute_write(
            f"""
            MATCH (h:Concept {{concept_id: $hid}}),
                  (t:Concept {{concept_id: $tid}})
            MERGE (h)-[r:{rel_type}]->(t)
            ON CREATE SET r.confidence   = $confidence,
                          r.inferred_by  = $inferred_by,
                          r.inferred_at  = timestamp($now)
            """,
            {
                "hid":         str(head_id),
                "tid":         str(tail_id),
                "confidence":  rel.get("confidence", 0.85),
                "inferred_by": rel.get("inferred_by", "system"),
                "now":         now,
            }
        )
        _logger.debug("_store_relation stored: %s -[%s]-> %s (hid=%s tid=%s)",
                      rel["head"], rel_type, rel["tail"], head_id, tail_id)
    except Exception:
        _logger.exception("_store_relation failed for %s -[%s]-> %s",
                          rel.get("head"), rel.get("relation_type"), rel.get("tail"))
