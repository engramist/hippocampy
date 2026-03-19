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
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from mcp_engine.graph.kuzu_client import KuzuClient
    from mcp_engine.llm.provider import LLMClient

from mcp_engine.loop.step7_pathway import pathway_strength_decay

# ---------------------------------------------------------------------------
# Sweep table registry
# (table_name, pk_col, decay_config_key, index_name)
# ---------------------------------------------------------------------------

SWEEP_TABLES = [
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
        "sweep_at": datetime.now(timezone.utc).isoformat(),
    }

    # Step 1: Decay pathway_strength + archive below threshold
    d, a, e = await _decay_and_archive(db, decay_rates, interval_days, archive_threshold)
    summary["decayed"]  += d
    summary["archived"] += a
    summary["errors"]   += e

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

    # Step 4: Recompute GistClass centroids from accumulated System 2 examples (M4)
    c, e = await _recompute_centroids(db)
    summary["centroids_updated"]  = c
    summary["errors"]            += e

    return summary


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
