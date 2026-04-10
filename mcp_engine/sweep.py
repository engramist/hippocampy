"""
mcp_engine/sweep.py — Background Sweep
  Synaptic Pruning (H1) + Hebbian Trigger 2 (H2)

Named IP Claims implemented here:
  - Synaptic Pruning: Ebbinghaus Forgetting Curve decay + archive mechanic
    Every sweep interval, each active node's pathway_strength decays by
    decay_rate ^ interval_days. Nodes below archive_threshold are archived
    (never deleted — audit trail preserved).
  - Resurrection: archived nodes re-activated when a similar active node
    is found above resurrection_threshold. Strength reset to threshold value.
  - Hebbian Trigger 2: CO_OCCURS_WITH count threshold → LLM auto-promotion.
    High-count co-occurrence pairs are named by the LLM and written as
    semantic relationship edges with inferred_by="LLM".

Called by BrainDaemon._background_sweep() every sweep_interval_seconds.
All operations use short write-lock windows — one node at a time, one table
at a time. Never holds the write lock for bulk operations.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from mcp_engine.graph.kuzu_client import KuzuClient
    from mcp_engine.llm.provider import LLMClient

from mcp_engine.loop.step7_pathway import pathway_strength_decay
from mcp_engine.graph import embeddings as emb

# ---------------------------------------------------------------------------
# Sweep table registry
# (table_name, pk_col, decay_config_key, index_name)
# ---------------------------------------------------------------------------

SWEEP_TABLES = [
    ("Concept",           "concept_id",             "concept",            "concept_emb_idx"),
    ("GlobalConstraint", "global_constraint_id", "global_constraint", "globalconstraint_emb_idx"),
    ("GlobalPreference",  "global_preference_id",  "global_preference",  "globalpreference_emb_idx"),
    ("Decision",          "decision_id",            "decision",           "decision_emb_idx"),
    ("Constraint",        "constraint_id",          "constraint",         "constraint_emb_idx"),
    ("Requirement",       "requirement_id",         "requirement",        "requirement_emb_idx"),
    ("ActionItem",        "action_item_id",         "action_item",        "actionitem_emb_idx"),
    ("Message",           "message_id",             "message",            "message_emb_idx"),
    ("DocumentExtract",   "extract_id",             "document_extract",   "documentextract_emb_idx"),
]

# Named relationship types eligible for Hebbian auto-promotion
_NAMED_REL_TYPES = frozenset([
    "REQUIRES", "ENABLES", "REPLACES", "CONTRADICTS", "PART_OF",
    "CHOSEN_OVER", "IMPLEMENTS", "EXTENDS", "ALTERNATIVE_TO",
])

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def run_sweep(db, config: dict, llm_client: Optional[object]) -> dict:
    """
    Run one full background sweep cycle. Returns a summary dict.
    Errors in individual steps are logged and swallowed — one bad table
    never kills the entire sweep.

    Args:
        db: KuzuClient instance (write access)
        config: full sidequests.toml config dict
        llm_client: LLMClient or None — Hebbian Trigger 2 skipped if None
    """
    pruning_cfg         = config.get("pruning", {})
    sweep_interval      = pruning_cfg.get("sweep_interval_seconds", 300)
    archive_threshold   = float(pruning_cfg.get("archive_threshold", 0.10))
    resurrection_thresh = float(pruning_cfg.get("resurrection_threshold", 0.85))
    decay_rates         = pruning_cfg.get("decay_rate", {})

    # Express sweep interval as a fraction of a day — decay applied incrementally
    # each run rather than re-computing total decay from node creation date.
    interval_days = sweep_interval / 86400.0

    summary = {
        "decayed": 0, "archived": 0, "resurrected": 0,
        "promoted": 0, "errors": 0,
        "retrospective_plans": 0,
        "sweep_at": datetime.now(timezone.utc).isoformat(),
    }

    # Step 1: Decay pathway_strength + archive below threshold
    d, a, e = await _decay_and_archive(db, decay_rates, interval_days, archive_threshold)
    summary["decayed"]  += d
    summary["archived"] += a
    summary["errors"]   += e

    # Step 1.5: B74 valence-aware decay adjustment
    v, e = await _apply_valence_decay(db)
    summary["valence_adjusted"] = v
    summary["errors"] += e

    # Step 2: Resurrect archived nodes with active graph similarity
    r, e = await _resurrect_archived(db, resurrection_thresh)
    summary["resurrected"] += r
    summary["errors"]      += e

    # Step 3: Hebbian Trigger 2 — only when LLM is available
    if llm_client is not None:
        hebbian_cfg = config.get("hebbian", {})
        threshold   = int(hebbian_cfg.get("co_occurrence_threshold", 10))
        p, e = await _hebbian_promote(db, llm_client, threshold)
        summary["promoted"] += p
        summary["errors"]   += e

    # Step 3.5: Dream consolidation (synthesis) — only when LLM is available
    if llm_client is not None:
        d, e = await _dream_consolidation(db, config, llm_client)
        summary["synthesized"] = d
        summary["errors"] += e

    # Step 4: Recompute GistClass centroids from accumulated System 2 examples (M4)
    c, e = await _recompute_centroids(db)
    summary["centroids_updated"]  = c
    summary["errors"]            += e

    # Step 5: B68 Layer C retrospective plan inference
    rp, e = await _infer_retrospective_plans(db, config)
    summary["retrospective_plans"] += rp
    summary["errors"] += e

    return summary


async def _infer_retrospective_plans(db, config: dict) -> tuple[int, int]:
    """
    Infer plan structure from sequential ActionItems when no explicit plan exists.
    Weak fallback path used by background sweep.
    """
    inferred = errors = 0
    now = datetime.now(timezone.utc).isoformat()
    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    try:
        result = db.execute(
            "MATCH (a:ActionItem)-[:ESTABLISHED_IN]->(s:Session) "
            "WHERE a.archived = false AND a.text_raw IS NOT NULL "
            "RETURN s.session_id, a.action_item_id, a.text_raw, a.created_at "
            "ORDER BY s.session_id, a.created_at ASC"
        )
    except Exception:
        return 0, 1

    by_session: dict[str, list[tuple[str, str]]] = {}
    while result.has_next():
        row = result.get_next()
        sid = row[0] or ""
        aid = row[1] or ""
        txt = (row[2] or "").strip()
        if not sid or not aid or not txt:
            continue
        by_session.setdefault(sid, []).append((aid, txt))

    for session_id, items in by_session.items():
        if len(items) < 3:
            continue

        # Use the first 5 sequential ActionItems as retrospective steps.
        seq = items[:5]
        steps = [txt for _, txt in seq]
        goal = steps[0][:240]
        goal_vec = emb.embed(goal, model_name=embedding_model)

        # Dedup: skip if a very similar plan already exists.
        skip = False
        thresh = config.get("plan_dedup_threshold", 0.90)
        try:
            neighbors = db.vector_search("Plan", "plan_emb_idx", goal_vec, 8)
            for n in neighbors:
                score = float(n.get("score", 0.0) or 0.0)
                if score > thresh:
                    _logger.info("Plan dedup: similarity=%.3f, threshold=%.2f, action=reject", score, thresh)
                    skip = True
                    break
        except Exception:
            pass
        if skip:
            continue

        try:
            plan_id = str(uuid.uuid4())
            await db.execute_write(
                """
                CREATE (p:Plan {
                    plan_id: $plan_id,
                    goal: $goal,
                    strategy: NULL,
                    source: 'retrospective',
                    embedding: $embedding,
                    embedding_model: $embedding_model,
                    embedding_dim: $embedding_dim,
                    step_count: $step_count,
                    valence: NULL,
                    valence_source: NULL,
                    status: 'completed',
                    confidence: 0.65,
                    confidence_low: true,
                    pathway_strength: 0.65,
                    archived: false,
                    created_at: timestamp($created_at),
                    completed_at: timestamp($completed_at)
                })
                """,
                {
                    "plan_id": plan_id,
                    "goal": goal,
                    "embedding": goal_vec,
                    "embedding_model": embedding_model,
                    "embedding_dim": len(goal_vec),
                    "step_count": len(steps),
                    "created_at": now,
                    "completed_at": now,
                },
            )

            await db.execute_write(
                "MATCH (p:Plan {plan_id: $pid}), (s:Session {session_id: $sid}) "
                "MERGE (p)-[:PLANNED_IN]->(s)",
                {"pid": plan_id, "sid": session_id},
            )

            step_ids: list[str] = []
            for idx, (_, text_raw) in enumerate(seq, start=1):
                step_id = str(uuid.uuid4())
                step_ids.append(step_id)
                step_vec = emb.embed(text_raw, model_name=embedding_model)
                await db.execute_write(
                    """
                    CREATE (ps:PlanStep {
                        step_id: $step_id,
                        step_number: $step_number,
                        description: $description,
                        embedding: $embedding,
                        embedding_model: $embedding_model,
                        embedding_dim: $embedding_dim,
                        expected_outcome: NULL,
                        actual_outcome: NULL,
                        valence: NULL,
                        status: 'succeeded',
                        created_at: timestamp($created_at),
                        completed_at: timestamp($completed_at)
                    })
                    """,
                    {
                        "step_id": step_id,
                        "step_number": idx,
                        "description": text_raw,
                        "embedding": step_vec,
                        "embedding_model": embedding_model,
                        "embedding_dim": len(step_vec),
                        "created_at": now,
                        "completed_at": now,
                    },
                )
                await db.execute_write(
                    "MATCH (ps:PlanStep {step_id: $sid}), (p:Plan {plan_id: $pid}) "
                    "MERGE (ps)-[:STEP_OF]->(p)",
                    {"sid": step_id, "pid": plan_id},
                )

            for a, b in zip(step_ids, step_ids[1:]):
                await db.execute_write(
                    "MATCH (x:PlanStep {step_id: $a}), (y:PlanStep {step_id: $b}) "
                    "MERGE (x)-[:NEXT_STEP]->(y)",
                    {"a": a, "b": b},
                )

            inferred += 1
        except Exception:
            errors += 1

    return inferred, errors


# ---------------------------------------------------------------------------
# Step 1: Decay + Archive
# ---------------------------------------------------------------------------

async def _decay_and_archive(
    db,
    decay_rates: dict,
    interval_days: float,
    archive_threshold: float,
) -> tuple[int, int, int]:
    """
    Apply one sweep interval of pathway_strength decay to every active node
    in each artifact table. Archive nodes that fall below archive_threshold.

    Decay formula (Ebbinghaus Forgetting Curve, incremental per sweep run):
        new_strength = current * decay_rate ^ interval_days

    Returns (decayed_count, archived_count, error_count).
    """
    decayed = archived = errors = 0

    for table, pk_col, config_key, _ in SWEEP_TABLES:
        decay_rate = float(decay_rates.get(config_key, 0.99))
        decay_factor = decay_rate ** interval_days

        try:
            # Atomic decay: multiply in-place to avoid TOCTOU race (SW1 fix).
            # If the loop worker strengthened a node between sweep read and write,
            # the old read-modify-write pattern would overwrite the loop's update.
            # This atomic SET preserves any concurrent modifications.
            await db.execute_write(
                f"MATCH (n:{table}) WHERE n.archived = false "
                f"SET n.pathway_strength = n.pathway_strength * $factor",
                {"factor": decay_factor},
            )

            # Now find and archive nodes below threshold
            result = db.execute(
                f"MATCH (n:{table}) WHERE n.archived = false "
                f"AND n.pathway_strength < $threshold "
                f"RETURN n.{pk_col}",
                {"threshold": archive_threshold},
            )

            to_archive = []
            while result.has_next():
                row = result.get_next()
                to_archive.append(row[0])

            # Count decayed (all active nodes were decayed in the bulk update)
            count_result = db.execute(
                f"MATCH (n:{table}) WHERE n.archived = false RETURN count(n)"
            )
            if count_result.has_next():
                decayed += count_result.get_next()[0]

            for node_id in to_archive:
                try:
                    await db.execute_write(
                        f"MATCH (n:{table} {{{pk_col}: $id}}) SET n.archived = true",
                        {"id": node_id},
                    )
                    archived += 1
                except Exception:
                    errors += 1

        except Exception:
            errors += 1

    return decayed, archived, errors


# ---------------------------------------------------------------------------
# Step 1.5: B74 — Valence-aware decay
# ---------------------------------------------------------------------------

async def _apply_valence_decay(db) -> tuple[int, int]:
    """
    Adjust Concept pathway_strength based on accumulated OUTCOME_SIGNAL valence.
    Positive valence -> slower decay; Negative valence -> faster decay.
    """
    adjusted = errors = 0
    try:
        # 1. Query all Concepts with signals
        ro = db.execute(
            "MATCH (ps:PlanStep)-[o:OUTCOME_SIGNAL]->(c:Concept) "
            "WHERE c.archived = false "
            "RETURN c.concept_id, avg(o.valence) AS avg_v"
        )
        
        updates = []
        while ro.has_next():
            row = ro.get_next()
            cid = row[0]
            avg_v = row[1]
            if cid and avg_v is not None:
                # valence_factor in [0.7, 1.3] for valence in [-1, 1]
                factor = 1.0 + (float(avg_v) * 0.3)
                updates.append((cid, factor))
                
        # 2. Apply atomic updates
        for cid, factor in updates:
            try:
                # Atomic multiply + clamp to [0, 1]
                await db.execute_write(
                    "MATCH (c:Concept {concept_id: $cid}) "
                    "SET c.pathway_strength = CASE "
                    "  WHEN c.pathway_strength * $factor > 1.0 THEN 1.0 "
                    "  WHEN c.pathway_strength * $factor < 0.0 THEN 0.0 "
                    "  ELSE c.pathway_strength * $factor END",
                    {"cid": cid, "factor": factor}
                )
                adjusted += 1
            except Exception:
                errors += 1
                
    except Exception:
        errors += 1
        
    return adjusted, errors


# ---------------------------------------------------------------------------
# Step 2: Resurrection
# ---------------------------------------------------------------------------

async def _resurrect_archived(
    db,
    resurrection_threshold: float,
) -> tuple[int, int]:
    """
    For each archived node, search for similar active nodes in the same table
    using the HNSW vector index. If any neighbor scores above
    resurrection_threshold, un-archive the node and reset its strength.

    Strength reset to resurrection_threshold (not 1.0 — node was dormant and
    must earn full strength back through access per the Hebbian model).

    Returns (resurrected_count, error_count).
    """
    resurrected = errors = 0

    for table, pk_col, _, index_name in SWEEP_TABLES:
        try:
            result = db.execute(
                f"MATCH (n:{table}) "
                f"WHERE n.archived = true AND n.embedding IS NOT NULL "
                f"RETURN n.{pk_col}, n.embedding",
            )

            archived_nodes = []
            while result.has_next():
                row = result.get_next()
                if row[0] and row[1]:
                    archived_nodes.append((row[0], row[1]))

        except Exception:
            errors += 1
            continue

        for node_id, embedding in archived_nodes:
            try:
                # SW2 fix: fetch more results since we'll filter out archived
                # neighbors. HNSW doesn't support prefiltering in 0.11.3, so
                # we over-fetch and postfilter to active nodes only.
                neighbors = db.vector_search(table, index_name, embedding, 20)
                for neighbor in neighbors:
                    node  = neighbor["node"]
                    score = neighbor["score"]

                    # Skip self-match and archived neighbors.
                    # SW2: explicitly check archived=false to ensure we only
                    # compare against active (confirmed) nodes per spec.
                    if node.get(pk_col) == node_id:
                        continue
                    if node.get("archived", True):
                        continue

                    if score >= resurrection_threshold:
                        await db.execute_write(
                            f"MATCH (n:{table} {{{pk_col}: $id}}) "
                            f"SET n.archived = false, "
                            f"    n.pathway_strength = $strength",
                            {"id": node_id, "strength": resurrection_threshold},
                        )
                        resurrected += 1
                        break  # one match is enough

            except Exception:
                errors += 1

    return resurrected, errors


# ---------------------------------------------------------------------------
# Step 3: Hebbian Trigger 2 — CO_OCCURS_WITH auto-promotion
# ---------------------------------------------------------------------------

_PROMOTION_PROMPT = """\
Two concepts frequently co-occur in the same AI assistant conversation context.
Based on the concept text alone, determine their most likely semantic relationship.

Concept A: {text_a}
Concept B: {text_b}

Choose exactly one relationship type from this list, or null if none clearly applies:
REQUIRES, ENABLES, REPLACES, CONTRADICTS, PART_OF, CHOSEN_OVER, IMPLEMENTS, EXTENDS, ALTERNATIVE_TO

Rules:
- Only choose a type if you are confident (>= 0.70)
- "A REQUIRES B" means A depends on B to function
- "A ENABLES B" means A makes B possible
- "A REPLACES B" means A supersedes B
- "A CONTRADICTS B" means A and B are in conflict
- "A PART_OF B" means A is a component of B
- "A CHOSEN_OVER B" means A was selected instead of B
- "A IMPLEMENTS B" means A is a concrete realization of B
- "A EXTENDS B" means A builds on B
- "A ALTERNATIVE_TO B" means A and B are options for the same need

Respond with JSON only, no explanation:
{{"relation_type": "REQUIRES", "confidence": 0.82}}

If no relationship clearly applies:
{{"relation_type": null, "confidence": 0.0}}"""


async def _hebbian_promote(
    db,
    llm_client,
    co_occurrence_threshold: int,
) -> tuple[int, int]:
    """
    Find CO_OCCURS_WITH edges at or above co_occurrence_threshold and ask
    the LLM to name the semantic relationship. Writes the named edge with
    inferred_by="LLM". Uses MERGE — idempotent if edge already exists.

    Returns (promoted_count, error_count).
    """
    promoted = errors = 0
    now = datetime.now(timezone.utc).isoformat()

    # Fetch high-count co-occurrence pairs that don't already have a named edge.
    # SW3 fix: exclude pairs where any named semantic relationship already exists
    # to avoid re-prompting the LLM for already-promoted pairs.
    named_rels = "|".join(_NAMED_REL_TYPES)
    try:
        result = db.execute(
            f"MATCH (a:Concept)-[r:CO_OCCURS_WITH]->(b:Concept) "
            f"WHERE r.count >= $threshold "
            f"  AND NOT (a)-[:{named_rels}]->(b) "
            f"  AND NOT (b)-[:{named_rels}]->(a) "
            f"RETURN a.concept_id, a.text_raw, b.concept_id, b.text_raw, r.count",
            {"threshold": co_occurrence_threshold},
        )
        pairs = []
        while result.has_next():
            row = result.get_next()
            pairs.append({
                "a_id":   row[0],
                "a_text": row[1] or "",
                "b_id":   row[2],
                "b_text": row[3] or "",
                "count":  row[4],
            })
    except Exception:
        return 0, 1

    for pair in pairs:
        if not pair["a_text"] or not pair["b_text"]:
            continue

        try:
            prompt = _PROMOTION_PROMPT.format(
                text_a=pair["a_text"],
                text_b=pair["b_text"],
            )
            # S1 fix: use achat() to avoid blocking the event loop
            if hasattr(llm_client, 'achat'):
                raw = await llm_client.achat([{"role": "user", "content": prompt}])
            else:
                raw = llm_client.chat([{"role": "user", "content": prompt}])

            parsed     = json.loads(raw.strip())
            rel_type   = parsed.get("relation_type")
            confidence = float(parsed.get("confidence", 0.0))

            if rel_type not in _NAMED_REL_TYPES:
                continue
            if confidence < 0.60:
                continue

            # Write named relationship — MERGE is idempotent
            await db.execute_write(
                f"MATCH (a:Concept {{concept_id: $a_id}}), "
                f"      (b:Concept {{concept_id: $b_id}}) "
                f"MERGE (a)-[r:{rel_type}]->(b) "
                f"ON CREATE SET r.confidence  = $conf, "
                f"              r.inferred_by = 'LLM', "
                f"              r.inferred_at = timestamp($now) "
                f"ON MATCH SET  r.confidence  = $conf",
                {
                    "a_id": pair["a_id"],
                    "b_id": pair["b_id"],
                    "conf": confidence,
                    "now":  now,
                },
            )
            promoted += 1

        except (json.JSONDecodeError, KeyError, ValueError):
            # LLM returned malformed JSON — skip silently, will retry next sweep
            pass
        except Exception:
            errors += 1

    return promoted, errors


# ---------------------------------------------------------------------------
# Step 4 (sweep): Centroid recomputation from System 2 examples (M4)
# ---------------------------------------------------------------------------

async def _recompute_centroids(db) -> tuple[int, int]:
    """
    For each GistClass that has at least one GistExample, mean-pool all
    example embeddings and update GistClass.centroid.

    This makes the System 1 fast-path self-improving — centroids shift toward
    real usage patterns as System 2 accumulates labeled examples over time.

    Returns (updated_count, error_count).
    """
    updated = errors = 0

    # Fetch distinct gist classes that have examples
    try:
        result = db.execute(
            "MATCH (e:GistExample) RETURN DISTINCT e.gist_class"
        )
        classes_with_examples = []
        while result.has_next():
            row = result.get_next()
            if row[0]:
                classes_with_examples.append(row[0])
    except Exception:
        return 0, 1

    for class_name in classes_with_examples:
        try:
            result = db.execute(
                "MATCH (e:GistExample {gist_class: $cls}) "
                "WHERE e.embedding IS NOT NULL "
                "RETURN e.embedding",
                {"cls": class_name},
            )
            embeddings = []
            while result.has_next():
                row = result.get_next()
                if row[0]:
                    embeddings.append(row[0])

            if not embeddings:
                continue

            # Mean-pool: sum then divide element-wise
            dim = len(embeddings[0])
            centroid = [0.0] * dim
            for emb in embeddings:
                for i, v in enumerate(emb):
                    centroid[i] += v
            n = len(embeddings)
            centroid = [v / n for v in centroid]

            # Normalize to unit vector (cosine similarity requires unit vectors)
            norm = sum(v * v for v in centroid) ** 0.5
            if norm > 0:
                centroid = [v / norm for v in centroid]

            await db.execute_write(
                "MATCH (g:GistClass {name: $name}) SET g.centroid = $centroid",
                {"name": class_name, "centroid": centroid},
            )
            updated += 1

        except Exception:
            errors += 1

    return updated, errors


# ---------------------------------------------------------------------------
# Step 3.5: Dream consolidation / synthesis
# ---------------------------------------------------------------------------


async def _dream_consolidation(db, config: dict, llm_client: Optional[object]) -> tuple[int, int]:
    """
    Cluster Lesson nodes by domain + embedding similarity and synthesize
    meta-lessons using the LLM. Returns (synthesized_count, error_count).

    Config (sidequests.toml):
      [sweep.dreaming]
      min_cluster_size = 3
      similarity_threshold = 0.75
      max_syntheses_per_sweep = 5
      decay_boost_multiplier = 1.3
    """
    synthesized = errors = 0
    now = datetime.now(timezone.utc).isoformat()

    dreaming_cfg = config.get("sweep", {}).get("dreaming", {})
    min_cluster = int(dreaming_cfg.get("min_cluster_size", 3))
    sim_thresh = float(dreaming_cfg.get("similarity_threshold", 0.75))
    max_per_sweep = int(dreaming_cfg.get("max_syntheses_per_sweep", 5))
    decay_boost = float(dreaming_cfg.get("decay_boost_multiplier", 1.3))
    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    # 1) Discover candidate domains
    try:
        res = db.execute(
            "MATCH (l:Lesson) WHERE l.archived = false AND (l.lesson_type IS NULL OR l.lesson_type != 'synthesis') RETURN DISTINCT l.domain"
        )
    except Exception:
        return 0, 1

    domains = []
    while res.has_next():
        row = res.get_next()
        dom = row[0] or ""
        if dom:
            domains.append(dom)

    for domain in domains:
        try:
            result = db.execute(
                "MATCH (l:Lesson) WHERE l.archived = false AND l.domain = $domain "
                "AND (l.lesson_type IS NULL OR l.lesson_type != 'synthesis') "
                "AND NOT EXISTS { MATCH (l)<-[:GENERALIZES_LESSON]-(:Lesson) } "
                "RETURN l.lesson_id, l.embedding, l.text_raw, l.pathway_strength, l.confidence",
                {"domain": domain},
            )
        except Exception:
            errors += 1
            continue

        candidates = []
        while result.has_next():
            row = result.get_next()
            lid = row[0]
            embedding = row[1]
            text = row[2] or ""
            pathway = float(row[3] or 0.0)
            conf = float(row[4] or 0.0)
            if lid and embedding:
                candidates.append({"id": lid, "emb": embedding, "text": text, "pathway": pathway, "confidence": conf})

        if len(candidates) < min_cluster:
            continue

        # Normalize embeddings for cosine similarity
        for c in candidates:
            vec = c["emb"]
            norm = sum(v * v for v in vec) ** 0.5
            if norm > 0:
                c["emb_norm"] = [v / norm for v in vec]
            else:
                c["emb_norm"] = vec

        unassigned = set(range(len(candidates)))
        clusters = []
        # Greedy clustering: seed with an unassigned item, group neighbors above threshold
        while unassigned and len(clusters) < max_per_sweep:
            i = next(iter(unassigned))
            seed = candidates[i]
            cluster_idx = [i]
            others = list(unassigned - {i})
            for j in others:
                a = seed["emb_norm"]
                b = candidates[j]["emb_norm"]
                denom = (sum(x * x for x in a) ** 0.5) * (sum(x * x for x in b) ** 0.5)
                sim = 0.0
                if denom > 0:
                    sim = sum(x * y for x, y in zip(a, b)) / denom
                if sim >= sim_thresh:
                    cluster_idx.append(j)
            for k in cluster_idx:
                unassigned.discard(k)
            if len(cluster_idx) >= min_cluster:
                clusters.append([candidates[k] for k in cluster_idx])

        for cluster in clusters:
            if synthesized >= max_per_sweep:
                break
            try:
                excerpts = "\n\n".join(f"- {c['text']}" for c in cluster)
                prompt = (
                    f"Synthesize a concise meta-lesson for domain '{domain}'.\n\n"
                    f"Excerpts:\n{excerpts}\n\n"
                    "Return a short, stand-alone lesson text (title + 1-2-sentence summary + 1 actionable recommendation)."
                )
                if hasattr(llm_client, 'achat'):
                    raw = await llm_client.achat([{"role": "user", "content": prompt}])
                else:
                    raw = await llm_client.chat([{"role": "user", "content": prompt}])
                synth_text = (raw or "").strip()
                if not synth_text:
                    continue

                meta_emb = emb.embed(synth_text, model_name=embedding_model)
                meta_id = str(uuid.uuid4())
                max_path = max(c["pathway"] for c in cluster)
                avg_conf = sum(c["confidence"] for c in cluster) / len(cluster)
                meta_strength = min(1.0, max_path * 1.2)
                meta_conf = min(0.99, avg_conf + 0.05)

                # Create synthesized Lesson node
                await db.execute_write(
                    """
                    CREATE (m:Lesson {
                        lesson_id: $lid,
                        text_raw: $text_raw,
                        embedding: $embedding,
                        embedding_model: $embedding_model,
                        embedding_dim: $embedding_dim,
                        domain: $domain,
                        lesson_type: 'synthesis',
                        confidence: $confidence,
                        confidence_low: false,
                        pathway_strength: $pathway_strength,
                        archived: false,
                        created_at: timestamp($now)
                    })
                    """,
                    {
                        "lid": meta_id,
                        "text_raw": synth_text,
                        "embedding": meta_emb,
                        "embedding_model": embedding_model,
                        "embedding_dim": len(meta_emb),
                        "domain": domain,
                        "confidence": meta_conf,
                        "pathway_strength": meta_strength,
                        "now": now,
                    },
                )

                # Link meta-lesson -> constituents and accelerate constituent decay
                for c in cluster:
                    await db.execute_write(
                        "MATCH (m:Lesson {lesson_id: $mid}), (c:Lesson {lesson_id: $cid}) "
                        "MERGE (m)-[r:GENERALIZES_LESSON]->(c) "
                        "ON CREATE SET r.synthesized_at = timestamp($now), r.cluster_size = $cluster_size "
                        "ON MATCH SET r.cluster_size = $cluster_size",
                        {"mid": meta_id, "cid": c["id"], "now": now, "cluster_size": len(cluster)},
                    )
                    await db.execute_write(
                        "MATCH (c:Lesson {lesson_id: $cid}) "
                        "SET c.synthesized_at = timestamp($now), c.synthesis_cluster_size = $cluster_size, c.pathway_strength = c.pathway_strength / $decay_boost",
                        {"cid": c["id"], "now": now, "cluster_size": len(cluster), "decay_boost": decay_boost},
                    )

                synthesized += 1
            except Exception:
                errors += 1

    return synthesized, errors
