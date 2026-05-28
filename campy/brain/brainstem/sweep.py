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
from datetime import datetime, timezone, timedelta
import asyncio

_logger = logging.getLogger(__name__)

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
    from mcp_engine.llm.provider import LLMClient

from campy.brain.temporal_lobe.loop.step7_pathway import pathway_strength_decay
from campy.brain.hippocampus.graph import embeddings as emb
from campy.brain.thalamus.wiki_projection import export_wiki_projection

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
        config: full campy.toml config dict
        llm_client: LLMClient or None — Hebbian Trigger 2 skipped if None
    """
    from campy.brain.brainstem.phase import set_phase
    set_phase("sweeping")
    try:
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
            "patterns_discovered": 0,    # Phase 4
            "pattern_candidates": 0,     # Phase 4
            "frustration_clusters": 0,   # Basal Ganglia: avoidance Procedures
            "maturity_updates": 0,       # Basal Ganglia: maturity lifecycle
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

        # Step 3.75: Consistency audit (B196) — LLM-assisted pairwise lesson contradiction detection
        try:
            a, e = await _audit_consistency(db, config, llm_client)
            summary["consistency_audits"] = a
            summary["errors"] += e
        except Exception:
            summary["errors"] += 1

        # Step 4: Recompute GistClass centroids from accumulated System 2 examples (M4)
        c, e = await _recompute_centroids(db)
        summary["centroids_updated"]  = c
        summary["errors"]            += e

        # Step 5: B68 Layer C retrospective plan inference
        rp, e = await _infer_retrospective_plans(db, config)
        summary["retrospective_plans"] += rp
        summary["errors"] += e

        # Step 6: Knowledge gap detection (B193)
        g, e = await _detect_knowledge_gaps(db, config)
        summary["gaps_detected"] = g
        summary["errors"] += e

        # Step 7: Wiki Projection (B222)
        try:
            wiki_summary = await export_wiki_projection(db, config)
            summary["wiki_projection"] = wiki_summary
        except Exception:
            summary["errors"] += 1

        # Step 7.5: Offline pattern discovery (Phase 4 — Anticipatory Engine)
        try:
            from campy.brain.brainstem.sweep_patterns import discover_patterns
            pat_summary = await discover_patterns(db, config, llm_client)
            summary["patterns_discovered"] = pat_summary.get("triggers_written", 0)
            summary["pattern_candidates"] = pat_summary.get("candidates_found", 0)
            summary["errors"] += pat_summary.get("errors", 0)
        except Exception:
            _logger.warning("[Sweep] Pattern discovery failed", exc_info=True)
            summary["errors"] += 1

        return summary
    finally:
        set_phase("idle")


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


async def _detect_knowledge_gaps(db, config: dict) -> tuple[int, int]:
    """
    Detect knowledge gaps across domains and archetypes.

    Heuristics implemented:
      - Domain with < 2 Lessons but > 5 Messages mentioning it => missing_lessons
      - Archetype (Plan.strategy) with solved_count > 0 but lesson_count == 0 => no_lessons_for_archetype
      - Domain where avg Lesson confidence < 0.5 => low_quality

    Creates or updates `KnowledgeGap` nodes and links them via IDENTIFIED_GAP_IN.
    Returns (n_detected, n_errors).
    """
    detected = errors = 0
    now = datetime.now(timezone.utc).isoformat()

    # 1) Aggregate lesson counts and average confidence by domain
    lesson_map: dict[str, int] = {}
    avg_conf_map: dict[str, float] = {}
    try:
        r = db.execute(
            "MATCH (l:Lesson) WHERE l.archived = false AND l.domain IS NOT NULL "
            "RETURN l.domain, count(l) AS lesson_count, avg(l.confidence) AS avg_conf"
        )
        while r.has_next():
            row = r.get_next()
            dom = row[0] or ""
            lesson_map[dom] = int(row[1] or 0)
            avg_conf_map[dom] = float(row[2] or 0.0)
    except Exception:
        return 0, 1

    # 2) Count messages that reference Concepts by gist_class
    msg_map: dict[str, int] = {}
    try:
        rm = db.execute(
            "MATCH (m:Message)-[:ESTABLISHED]->(c:Concept) "
            "WHERE c.gist_class IS NOT NULL RETURN c.gist_class, count(m) AS msg_count"
        )
        while rm.has_next():
            row = rm.get_next()
            gist = row[0] or ""
            msg_map[gist] = int(row[1] or 0)
    except Exception:
        # Non-fatal: continue with empty msg_map
        msg_map = {}

    # 3) Completed plan strategies (archetype proxy)
    plan_map: dict[str, int] = {}
    try:
        rp = db.execute(
            "MATCH (p:Plan) WHERE p.status = 'completed' AND p.strategy IS NOT NULL RETURN p.strategy, count(p) AS solved_count"
        )
        while rp.has_next():
            row = rp.get_next()
            strat = row[0] or ""
            plan_map[strat] = int(row[1] or 0)
    except Exception:
        plan_map = {}

    # Candidate domains to evaluate
    candidates = set(list(lesson_map.keys()) + list(msg_map.keys()) + list(plan_map.keys()))

    for dom in candidates:
        lesson_count = lesson_map.get(dom, 0)
        msg_count = msg_map.get(dom, 0)
        plan_count = plan_map.get(dom, 0)
        avg_conf = avg_conf_map.get(dom, 0.0)

        gap_type = None
        if lesson_count < 2 and msg_count > 5:
            gap_type = "missing_lessons"
        elif plan_count > 0 and lesson_count == 0:
            gap_type = "no_lessons_for_archetype"
        elif lesson_count > 0 and avg_conf < 0.5:
            gap_type = "low_quality"

        # If no gap detected, consider resolving existing unresolved gap
        if not gap_type:
            try:
                rr = db.execute(
                    "MATCH (g:KnowledgeGap {domain: $d, resolved: false}) RETURN g.gap_id LIMIT 1",
                    {"d": dom},
                )
                if rr.has_next():
                    gid = rr.get_next()[0]
                    # Resolve if criteria now satisfied
                    if lesson_count >= 2 or (lesson_count > 0 and avg_conf >= 0.5):
                        try:
                            await db.execute_write(
                                "MATCH (g:KnowledgeGap {gap_id: $gid}) SET g.resolved = true, g.resolved_at = timestamp($now)",
                                {"gid": gid, "now": now},
                            )
                            detected += 1
                        except Exception:
                            errors += 1
                continue
            except Exception:
                errors += 1
                continue

        # Compute severity: message_count / max(1, lesson_count) scaled
        try:
            if lesson_count == 0:
                severity = min(1.0, float(msg_count) / 10.0)
            else:
                severity = min(1.0, (float(msg_count) / float(max(1, lesson_count))) / 10.0)
            # Boost severity for archetype-without-lessons
            if gap_type == "no_lessons_for_archetype" and severity < 0.5:
                severity = 0.6

            desc = f"Detected knowledge gap ({gap_type}) for domain '{dom}': {msg_count} messages, {lesson_count} lessons"

            # Create or update KnowledgeGap node
            ex = db.execute(
                "MATCH (g:KnowledgeGap {domain: $d, resolved: false}) RETURN g.gap_id LIMIT 1",
                {"d": dom},
            )
            if ex.has_next():
                gid = ex.get_next()[0]
                await db.execute_write(
                    "MATCH (g:KnowledgeGap {gap_id: $gid}) "
                    "SET g.gap_type = $gap_type, g.description = $desc, g.severity = $severity, "
                    "g.message_count = $msg_count, g.lesson_count = $lesson_count",
                    {"gid": gid, "gap_type": gap_type, "desc": desc, "severity": severity, "msg_count": msg_count, "lesson_count": lesson_count},
                )
            else:
                gid = str(uuid.uuid4())
                await db.execute_write(
                    "CREATE (g:KnowledgeGap {gap_id: $gid, domain: $domain, gap_type: $gap_type, description: $desc, severity: $severity, message_count: $msg_count, lesson_count: $lesson_count, resolved: false, created_at: timestamp($now)})",
                    {"gid": gid, "domain": dom, "gap_type": gap_type, "desc": desc, "severity": severity, "msg_count": msg_count, "lesson_count": lesson_count, "now": now},
                )

            # Try to link to a Concept (gist_class) or a MainQuest
            try:
                cr = db.execute(
                    "MATCH (c:Concept {gist_class: $domain}) RETURN c.concept_id LIMIT 1",
                    {"domain": dom},
                )
                if cr.has_next():
                    cid = cr.get_next()[0]
                    await db.execute_write(
                        "MATCH (g:KnowledgeGap {gap_id: $gid}), (c:Concept {concept_id: $cid}) MERGE (g)-[:IDENTIFIED_GAP_IN]->(c)",
                        {"gid": gid, "cid": cid},
                    )
                else:
                    qr = db.execute(
                        "MATCH (q:MainQuest) WHERE lower(q.name) CONTAINS lower($domain) RETURN q.quest_id LIMIT 1",
                        {"domain": dom},
                    )
                    if qr.has_next():
                        qid = qr.get_next()[0]
                        await db.execute_write(
                            "MATCH (g:KnowledgeGap {gap_id: $gid}), (q:MainQuest {quest_id: $qid}) MERGE (g)-[:IDENTIFIED_GAP_IN]->(q)",
                            {"gid": gid, "qid": qid},
                        )
            except Exception:
                pass

            detected += 1
        except Exception:
            errors += 1

    return detected, errors


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

    Config (campy.toml):
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

    # After lesson synthesis, attempt procedure synthesis (B194)
    try:
        p_count, p_err = await _synthesize_procedures(db, config, llm_client)
        synthesized += p_count
        errors += p_err
    except Exception:
        errors += 1

    # Basal Ganglia: frustration cluster detection (no LLM needed)
    try:
        fc_count, fc_err = await _detect_frustration_clusters(db, config)
        synthesized += fc_count
        errors += fc_err
    except Exception:
        errors += 1

    # Basal Ganglia: update Procedure maturity stages
    try:
        maturity_result = await _update_procedure_maturity(db, config)
        _logger.info("[BasalGanglia] maturity update: %s", maturity_result)
    except Exception:
        errors += 1

    return synthesized, errors


async def _update_procedure_maturity(db, config: dict) -> dict:
    """
    Basal Ganglia — Maturity Lifecycle.

    Update maturity_stage for all active Procedures based on application stats.
    Also detect degradation and archive deeply degraded Procedures.

    Returns summary dict.
    """
    result = {"updated": 0, "degraded": 0, "archived": 0, "errors": 0}

    # 1) Promote: nascent -> developing -> mature
    try:
        await db.execute_write(
            "MATCH (p:Procedure) WHERE p.archived = false "
            "AND coalesce(p.maturity_stage, 'nascent') != 'degraded' "
            "SET p.maturity_stage = CASE "
            "  WHEN p.application_count >= 5 AND p.success_rate >= 0.75 THEN 'mature' "
            "  WHEN p.application_count >= 3 AND p.success_rate >= 0.50 THEN 'developing' "
            "  ELSE 'nascent' END"
        )
        result["updated"] += 1
    except Exception:
        result["errors"] += 1

    # 2) Degrade: application_count >= 3 AND success_rate < 0.30
    try:
        await db.execute_write(
            "MATCH (p:Procedure) WHERE p.archived = false "
            "AND p.application_count >= 3 AND p.success_rate < 0.30 "
            "AND coalesce(p.maturity_stage, 'nascent') != 'degraded' "
            "SET p.maturity_stage = 'degraded', "
            "    p.pathway_strength = p.pathway_strength * 0.5"
        )
        result["degraded"] += 1
    except Exception:
        result["errors"] += 1

    # 3) Archive: already degraded AND still failing
    try:
        await db.execute_write(
            "MATCH (p:Procedure) WHERE p.archived = false "
            "AND p.maturity_stage = 'degraded' "
            "AND p.success_rate < 0.20 "
            "SET p.archived = true"
        )
        result["archived"] += 1
    except Exception:
        result["errors"] += 1

    return result


async def _call_llm(llm_client: Optional[object], prompt: str) -> str:
    """Call the LLM client in a sync/async safe way and return raw text."""
    if llm_client is None:
        return ""
    try:
        if hasattr(llm_client, "achat"):
            res = llm_client.achat([{"role": "user", "content": prompt}])
        else:
            res = llm_client.chat([{"role": "user", "content": prompt}])
        if asyncio.iscoroutine(res):
            return await res
        return res
    except Exception:
        return ""


async def _detect_frustration_clusters(db, config: dict) -> tuple[int, int]:
    """
    Basal Ganglia — Avoidance Archetype.

    Query high-salience nodes, cluster by embedding similarity, and synthesize
    avoidance Procedures. No LLM calls — pure graph traversal.

    Returns (procedures_created, error_count).
    """
    import numpy as np

    synthesized = errors = 0
    now = datetime.now(timezone.utc).isoformat()

    bg_cfg = config.get("sweep", {}).get("basal_ganglia", {})
    min_cluster = int(bg_cfg.get("min_cluster_size", 3))
    sim_threshold = float(bg_cfg.get("similarity_threshold", 0.65))
    salience_floor = float(bg_cfg.get("salience_floor", 1.3))
    max_per_sweep = int(bg_cfg.get("max_per_sweep", 3))
    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    # 1) Query high-salience nodes across GCL node types (deduplicate by id)
    seen_ids: set[str] = set()
    all_nodes = []
    for table, id_col in [("Concept", "concept_id"), ("Decision", "decision_id"),
                          ("Constraint", "constraint_id")]:
        try:
            rows = await db.execute_read(
                f"MATCH (n:{table}) WHERE n.archived = false "
                f"  AND n.salience_score >= $floor "
                f"RETURN n.{id_col} AS id, n.text_raw AS name, "
                f"  coalesce(n.text_raw, '') AS desc, n.embedding AS emb, "
                f"  n.salience_score AS salience "
                f"ORDER BY n.salience_score DESC LIMIT 50",
                {"floor": salience_floor},
            )
            for row in (rows or []):
                node_id = row.get("id", "")
                if row.get("emb") and node_id not in seen_ids:
                    seen_ids.add(node_id)
                    all_nodes.append(row)
        except Exception:
            errors += 1

    if len(all_nodes) < min_cluster:
        return 0, errors

    # 2) Greedy single-linkage clustering
    visited = set()
    clusters = []

    for i, node_i in enumerate(all_nodes):
        if i in visited:
            continue
        cluster = [i]
        visited.add(i)
        vec_i = np.array(node_i["emb"])
        norm_i = np.linalg.norm(vec_i)
        if norm_i == 0:
            continue

        for j, node_j in enumerate(all_nodes):
            if j in visited:
                continue
            vec_j = np.array(node_j["emb"])
            norm_j = np.linalg.norm(vec_j)
            if norm_j == 0:
                continue
            sim = float(np.dot(vec_i, vec_j) / (norm_i * norm_j))
            if sim >= sim_threshold:
                cluster.append(j)
                visited.add(j)

        if len(cluster) >= min_cluster:
            clusters.append(cluster)

    # 3) Synthesize avoidance Procedures from clusters
    for cluster_indices in clusters:
        if synthesized >= max_per_sweep:
            break

        cluster_nodes = [all_nodes[i] for i in cluster_indices]
        topic = cluster_nodes[0].get("name", "unknown")[:60]
        avg_salience = sum(n.get("salience", 1.0) for n in cluster_nodes) / len(cluster_nodes)

        steps = []
        for n in cluster_nodes[:5]:
            desc = n.get("desc", "")
            if desc:
                steps.append({
                    "step": len(steps) + 1,
                    "action": f"Avoid: {desc[:100]}",
                    "warning": "This pattern has caused repeated frustration",
                })

        proc_id = str(uuid.uuid4())
        name = f"Avoid: {topic}"
        description = (
            f"Auto-generated avoidance procedure from {len(cluster_nodes)} "
            f"high-salience nodes. Average salience: {avg_salience:.2f}."
        )
        steps_json = json.dumps(steps)

        try:
            proc_emb = emb.embed(description, model_name=embedding_model)
        except Exception:
            proc_emb = [0.0] * 384

        try:
            await db.execute_write(
                """
                CREATE (pr:Procedure {
                    procedure_id: $pid, name: $name,
                    domain: $domain, archetype: $archetype,
                    description: $description, steps_json: $steps_json,
                    embedding: $embedding, embedding_model: $embedding_model,
                    embedding_dim: $embedding_dim,
                    success_count: 0, application_count: 0, success_rate: 0.0,
                    salience_score: $salience_score,
                    confidence: $confidence, pathway_strength: $pathway_strength,
                    maturity_stage: 'nascent',
                    archived: false, created_at: timestamp($now)
                })
                """,
                {
                    "pid": proc_id, "name": name,
                    "domain": "auto-discovered", "archetype": "avoidance",
                    "description": description, "steps_json": steps_json,
                    "embedding": proc_emb, "embedding_model": embedding_model,
                    "embedding_dim": len(proc_emb),
                    "salience_score": avg_salience,
                    "confidence": min(avg_salience / 1.6, 1.0),
                    "pathway_strength": min(avg_salience * 0.6, 1.0),
                    "now": now,
                },
            )

            for node in cluster_nodes:
                try:
                    node_id = node.get("id", "")
                    if node_id:
                        await db.execute_write(
                            "MATCH (pr:Procedure {procedure_id: $pid}), (c:Concept {concept_id: $cid}) "
                            "MERGE (pr)-[r:DISTILLED_FROM]->(c) "
                            "ON CREATE SET r.synthesized_at = timestamp($now)",
                            {"pid": proc_id, "cid": node_id, "now": now},
                        )
                except Exception:
                    pass

            synthesized += 1
            _logger.info(
                "[BasalGanglia] avoidance Procedure %s from %d nodes: %s",
                proc_id[:8], len(cluster_nodes), name,
            )
        except Exception:
            _logger.exception("[BasalGanglia] Failed to create avoidance Procedure")
            errors += 1

    return synthesized, errors


async def _synthesize_procedures(db, config: dict, llm_client: Optional[object]) -> tuple[int, int]:
    """
    Synthesize Procedure nodes from clusters of similar successful Plans.

    Heuristic: group completed Plans by identical `strategy` string and synthesize
    a Procedure when at least `min_cluster_size` plans share the same strategy.
    This is a pragmatic first-pass implementation of B194 suitable for unit tests.
    """
    synthesized = errors = 0
    now = datetime.now(timezone.utc).isoformat()

    proc_cfg = config.get("sweep", {}).get("procedural", {})
    min_cluster = int(proc_cfg.get("min_cluster_size", 2))
    min_valence = float(proc_cfg.get("min_valence", 0.5))
    max_per_sweep = int(proc_cfg.get("max_syntheses_per_sweep", 3))
    embedding_model = config.get("embeddings", {}).get(
        "model", "sentence-transformers/all-MiniLM-L6-v2"
    )

    try:
        q = (
            "MATCH (p:Plan) WHERE p.valence > $min_valence AND p.status = 'completed' "
            "AND p.strategy IS NOT NULL RETURN DISTINCT p.strategy"
        )
        r = db.execute(q, {"min_valence": min_valence})
    except Exception:
        return 0, 1

    strategies = []
    while r.has_next():
        row = r.get_next()
        s = row[0] or ""
        if s:
            strategies.append(s)

    for strategy in strategies:
        if synthesized >= max_per_sweep:
            break

        try:
            pr = db.execute(
                "MATCH (p:Plan) WHERE p.strategy = $strategy AND p.valence > $min_valence "
                "AND p.status = 'completed' RETURN p.plan_id, p.goal, p.embedding, p.pathway_strength, p.confidence LIMIT 20",
                {"strategy": strategy, "min_valence": min_valence},
            )
        except Exception:
            errors += 1
            continue

        plans = []
        while pr.has_next():
            row = pr.get_next()
            pid = row[0]
            goal = row[1] or ""
            emb_vec = row[2]
            pathway = float(row[3] or 0.0)
            conf = float(row[4] or 0.0)
            plans.append({"plan_id": pid, "goal": goal, "emb": emb_vec, "pathway": pathway, "confidence": conf})

        if len(plans) < min_cluster:
            continue

        # Basal Ganglia: skip if an automation Procedure already exists for this strategy
        try:
            dup_check = db.execute(
                "MATCH (p:Procedure) WHERE p.archetype = $strategy AND p.archived = false "
                "RETURN count(p) > 0",
                {"strategy": strategy},
            )
            if dup_check.has_next() and dup_check.get_next()[0]:
                continue
        except Exception:
            pass

        # Build prompt and call LLM
        excerpts = "\n\n".join(f"- Goal: {p['goal']}" for p in plans)
        prompt = (
            f"Synthesize a reusable, parameterized Procedure template from these successful Plans "
            f"(strategy='{strategy}').\n\nPlans:\n{excerpts}\n\n"
            "Return a JSON object with keys: name (string), description (string), steps (array of {step, precondition, action, expected_outcome}). "
            "Keep steps concise (3-8 steps)."
        )

        raw = await _call_llm(llm_client, prompt)
        if not raw:
            # no LLM output — skip
            continue

        try:
            proc_obj = json.loads(raw)
        except Exception:
            # Fallback: create a minimal procedure from the strategy string
            proc_obj = {
                "name": strategy,
                "description": f"Procedure synthesized from plans using strategy '{strategy}'",
                "steps": [{"step": strategy, "precondition": "", "action": strategy, "expected_outcome": ""}],
            }

        # Prepare Procedure node params
        proc_text = proc_obj.get("description") or proc_obj.get("name") or strategy
        try:
            proc_emb = emb.embed(proc_text, model_name=embedding_model)
        except Exception:
            proc_emb = [0.0] * 384

        proc_id = str(uuid.uuid4())
        steps_json = json.dumps(proc_obj.get("steps", []))
        success_count = len(plans)
        avg_conf = sum(p.get("confidence", 0.0) for p in plans) / len(plans)
        max_path = max(p.get("pathway", 0.0) for p in plans)
        pathway_strength = min(1.0, max_path * 1.1)

        try:
            await db.execute_write(
                """
                CREATE (pr:Procedure {
                    procedure_id: $pid,
                    name: $name,
                    domain: $domain,
                    archetype: $archetype,
                    description: $description,
                    steps_json: $steps_json,
                    embedding: $embedding,
                    embedding_model: $embedding_model,
                    embedding_dim: $embedding_dim,
                    success_count: $success_count,
                    application_count: 0,
                    success_rate: 0.0,
                    confidence: $confidence,
                    pathway_strength: $pathway_strength,
                    archived: false,
                    created_at: timestamp($now)
                })
                """,
                {
                    "pid": proc_id,
                    "name": proc_obj.get("name", strategy),
                    "domain": proc_obj.get("domain", "planning"),
                    "archetype": "automation",
                    "description": proc_obj.get("description", ""),
                    "steps_json": steps_json,
                    "embedding": proc_emb,
                    "embedding_model": embedding_model,
                    "embedding_dim": len(proc_emb),
                    "success_count": success_count,
                    "confidence": avg_conf,
                    "pathway_strength": pathway_strength,
                    "now": now,
                },
            )

            # Link Procedure -> Plan (DISTILLED_FROM)
            for p in plans:
                try:
                    await db.execute_write(
                        "MATCH (pr:Procedure {procedure_id: $pid}), (pl:Plan {plan_id: $plan_id}) "
                        "MERGE (pr)-[r:DISTILLED_FROM]->(pl) "
                        "ON CREATE SET r.synthesized_at = timestamp($now)",
                        {"pid": proc_id, "plan_id": p["plan_id"], "now": now},
                    )
                except Exception:
                    pass

            # Create or MERGE archetype Concept and link
            try:
                concept_id = f"procedure_archetype:{uuid.uuid5(uuid.NAMESPACE_URL, strategy)}"
                await db.execute_write(
                    "MERGE (c:Concept {concept_id: $cid}) "
                    "ON CREATE SET c.text_raw = $text, c.pathway_strength = 0.6, c.archived = false, c.created_at = timestamp($now)",
                    {"cid": concept_id, "text": strategy, "now": now},
                )
                await db.execute_write(
                    "MATCH (pr:Procedure {procedure_id: $pid}), (c:Concept {concept_id: $cid}) MERGE (pr)-[:APPLIES_TO_ARCHETYPE]->(c)",
                    {"pid": proc_id, "cid": concept_id},
                )
            except Exception:
                pass

            synthesized += 1
        except Exception:
            errors += 1

    return synthesized, errors


async def _audit_consistency(db, config: dict, llm_client: Optional[object]) -> tuple[int, int]:
    """
    B196: Internal Consistency Audit

    - For each domain, select top-N Lessons by pathway_strength.
    - Pairwise compare embeddings; if similarity > threshold, ask LLM whether
      they contradict, supersede, or are both valid in different contexts.
    - Create DisambiguationEvent for contradictions/nuanced cases or
      DEPRECATED_BY + archive when one supersedes the other.
    - Flag stale Lessons (older than 30 days with no outgoing linkage).
    - Flag orphan Lessons (no inbound provenance edges).

    Returns: (audits_performed, errors)
    """
    audited = 0
    errors = 0
    now = datetime.now(timezone.utc).isoformat()

    cons_cfg = (config.get("sweep", {}) or {}).get("consistency", {})
    top_k = int(cons_cfg.get("top_lessons", 20))
    sim_thresh = float(cons_cfg.get("sim_threshold", 0.70))
    max_llm = int(cons_cfg.get("max_llm_calls", 10))
    min_path = float(cons_cfg.get("min_pathway_strength", 0.3))
    stale_days = int(cons_cfg.get("stale_days", 30))

    # 1) Get all domains with lessons
    domains = []
    try:
        r = db.execute("MATCH (l:Lesson) WHERE l.archived = false RETURN DISTINCT l.domain")
        while r.has_next():
            d = r.get_next()[0]
            if d:
                domains.append(d)
    except Exception:
        return 0, 1

    candidate_pairs: list[tuple[dict, dict, float]] = []

    for domain in domains:
        try:
            q = (
                "MATCH (l:Lesson) WHERE l.domain = $domain AND l.archived = false "
                "AND l.pathway_strength > $min_path ORDER BY l.pathway_strength DESC LIMIT $limit "
                "RETURN l.lesson_id, l.embedding, l.text_raw, l.confidence, l.pathway_strength, l.created_at, l.last_audited_at"
            )
            res = db.execute(q, {"domain": domain, "min_path": min_path, "limit": top_k})
        except Exception:
            errors += 1
            continue

        lessons = []
        while res.has_next():
            row = res.get_next()
            lid = row[0]
            emb_vec = row[1]
            text = row[2] or ""
            conf = float(row[3] or 0.0)
            pathway = float(row[4] or 0.0)
            last_aud = row[6] if len(row) > 6 else None
            if lid and emb_vec:
                lessons.append({"id": lid, "emb": emb_vec, "text": text, "conf": conf, "pathway": pathway, "last_audited_at": last_aud})

        if len(lessons) < 2:
            continue

        # Normalize embeddings for cosine similarity
        for l in lessons:
            vec = l["emb"]
            try:
                norm = sum(float(v) * float(v) for v in vec) ** 0.5
                if norm > 0:
                    l["emb_norm"] = [float(v) / norm for v in vec]
                else:
                    l["emb_norm"] = [float(v) for v in vec]
            except Exception:
                l["emb_norm"] = [float(v) for v in vec]

        # Pairwise compare
        for i in range(len(lessons)):
            for j in range(i + 1, len(lessons)):
                a = lessons[i]
                b = lessons[j]
                # Skip if both recently audited
                try:
                    skip = False
                    if a.get("last_audited_at") and b.get("last_audited_at"):
                        # If both have any last_audited_at, skip (keeps audit budget bounded)
                        skip = True
                    if skip:
                        continue
                except Exception:
                    pass

                va = a.get("emb_norm")
                vb = b.get("emb_norm")
                denom = (sum(x * x for x in va) ** 0.5) * (sum(x * x for x in vb) ** 0.5)
                sim = 0.0
                if denom > 0:
                    sim = sum(x * y for x, y in zip(va, vb)) / denom

                if sim >= sim_thresh:
                    candidate_pairs.append((a, b, sim))

    # Sort by similarity desc
    candidate_pairs.sort(key=lambda t: t[2], reverse=True)

    llm_calls = 0
    processed_lessons = set()

    for a, b, sim in candidate_pairs:
        if llm_calls >= max_llm or llm_client is None:
            break
        try:
            prompt = (
                f"You are auditing two extracted lessons for domain '{(a.get('text') or '')[:40]}'.\n"
                "Decide whether the two lessons: 1) directly contradict each other, 2) one supersedes the other (specify which as 'a' or 'b'), 3) are both valid but for different contexts, or 4) are consistent.\n"
                "Return a JSON object with keys: action ('contradict'|'supersedes'|'both_valid'|'no_issue'), winner (optional 'a'|'b'), explanation (string), confidence (0.0-1.0)."
            )
            raw = await _call_llm(llm_client, prompt)
            if not raw:
                llm_calls += 1
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                obj = {}

            action = obj.get("action", "")
            winner = obj.get("winner")

            # Handle actions
            if action == "contradict":
                # Create DisambiguationEvent for human review
                try:
                    eid = str(uuid.uuid4())
                    await db.execute_write(
                        """
                        CREATE (e:DisambiguationEvent {
                            event_id: $eid,
                            concept_id_a: $a,
                            concept_id_b: $b,
                            similarity: $sim,
                            status: 'pending',
                            resolved_at: NULL,
                            resolved_by: NULL,
                            created_at: timestamp($now)
                        })
                        """,
                        {"eid": eid, "a": a["id"], "b": b["id"], "sim": float(sim), "now": now},
                    )
                    audited += 1
                except Exception:
                    errors += 1

            elif action == "supersedes" and winner in ("a", "b"):
                # Archive the loser and draw DEPRECATED_BY loser -> winner
                try:
                    loser = b["id"] if winner == "a" else a["id"]
                    win = a["id"] if winner == "a" else b["id"]
                    await db.execute_write(
                        "MATCH (l:Lesson {lesson_id: $lid}) SET l.archived = true",
                        {"lid": loser},
                    )
                    await db.execute_write(
                        "MATCH (old:Lesson {lesson_id: $old}), (new:Lesson {lesson_id: $new}) MERGE (old)-[:DEPRECATED_BY]->(new)",
                        {"old": loser, "new": win},
                    )
                    audited += 1
                except Exception:
                    errors += 1

            elif action == "both_valid":
                # Create DisambiguationEvent for human review (nuanced)
                try:
                    eid = str(uuid.uuid4())
                    await db.execute_write(
                        "CREATE (e:DisambiguationEvent {event_id: $eid, concept_id_a: $a, concept_id_b: $b, similarity: $sim, status: 'pending', resolved_at: NULL, resolved_by: NULL, created_at: timestamp($now)})",
                        {"eid": eid, "a": a["id"], "b": b["id"], "sim": float(sim), "now": now},
                    )
                    audited += 1
                except Exception:
                    errors += 1

            llm_calls += 1
            processed_lessons.add(a["id"])
            processed_lessons.add(b["id"])
        except Exception:
            errors += 1

    # Update last_audited_at for processed lessons
    try:
        for lid in processed_lessons:
            try:
                await db.execute_write(
                    "MATCH (l:Lesson {lesson_id: $lid}) SET l.last_audited_at = timestamp($now)",
                    {"lid": lid, "now": now},
                )
            except Exception:
                pass
    except Exception:
        pass

    # Stale detection: older than stale_days with no outgoing APPLIES_TO|RELATED_TO|GENERALIZES_LESSON
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).isoformat()
        sr = db.execute(
            "MATCH (l:Lesson) WHERE l.archived = false AND l.lesson_type <> 'synthesis' AND l.created_at < timestamp($cutoff) "
            "AND NOT EXISTS { MATCH (l)-[:APPLIES_TO|RELATED_TO|GENERALIZES_LESSON]->() } RETURN l.lesson_id, l.text_raw",
            {"cutoff": cutoff},
        )
        stale_count = 0
        while sr.has_next():
            row = sr.get_next()
            lid = row[0]
            try:
                await db.execute_write(
                    "MATCH (l:Lesson {lesson_id: $lid}) SET l.stale_flagged = true, l.stale_flagged_at = timestamp($now)",
                    {"lid": lid, "now": now},
                )
                stale_count += 1
            except Exception:
                errors += 1
        audited += stale_count
    except Exception:
        errors += 1

    # Orphan detection: no inbound CONTAINS_LESSON|PRODUCED_LESSON|PRODUCED_PLAN_LESSON|LEARNED
    try:
        orr = db.execute(
            "MATCH (l:Lesson) WHERE l.archived = false AND NOT EXISTS { MATCH ()-[:CONTAINS_LESSON|PRODUCED_LESSON|PRODUCED_PLAN_LESSON|LEARNED]->(l) } RETURN l.lesson_id, l.text_raw",
            {},
        )
        orphan_count = 0
        while orr.has_next():
            row = orr.get_next()
            lid = row[0]
            try:
                await db.execute_write(
                    "MATCH (l:Lesson {lesson_id: $lid}) SET l.orphan_flagged = true, l.orphan_flagged_at = timestamp($now)",
                    {"lid": lid, "now": now},
                )
                orphan_count += 1
            except Exception:
                errors += 1
        audited += orphan_count
    except Exception:
        errors += 1

    return audited, errors
