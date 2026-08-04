"""Frustration cluster detection — Basal Ganglia avoidance learning.

Query high-salience nodes, cluster by embedding similarity, and synthesize
avoidance Procedures. No LLM calls — pure graph traversal.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import numpy as np

_logger = logging.getLogger(__name__)

# Source tables scanned for high-salience clustering, and their pk column -
# used to build the correctly-labeled DISTILLED_FROM edge per node (B277:
# previously hardcoded to :Concept regardless of which table a clustered
# node actually came from).
_SOURCE_ID_COLUMNS = {
    "Concept": "concept_id",
    "Decision": "decision_id",
    "Constraint": "constraint_id",
}


async def detect_frustration_clusters(db, config: dict) -> tuple[int, int]:
    """
    Basal Ganglia — Avoidance Archetype.

    Query high-salience nodes, cluster by embedding similarity, and synthesize
    avoidance Procedures. No LLM calls — pure graph traversal.

    Returns (procedures_created, error_count).
    """
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
            # B277: `desc` is a reserved keyword in Kuzu's Cypher dialect
            # (collides with ORDER BY ... DESC) - aliasing to it raised a
            # Parser exception on every call, so this query - the very
            # first step of frustration cluster detection - never
            # successfully returned a single row in production.
            rows = await db.execute_read(
                f"MATCH (n:{table}) WHERE n.archived = false "
                f"  AND n.salience_score >= $floor "
                f"RETURN n.{id_col} AS id, n.text_raw AS name, "
                f"  coalesce(n.text_raw, '') AS description, n.embedding AS emb, "
                f"  n.salience_score AS salience "
                f"ORDER BY n.salience_score DESC LIMIT 50",
                {"floor": salience_floor},
            )
            for row in (rows or []):
                node_id = row.get("id", "")
                if row.get("emb") and node_id not in seen_ids:
                    seen_ids.add(node_id)
                    # B277: remember which table this node came from - the
                    # DISTILLED_FROM edge below needs the real label, not a
                    # hardcoded :Concept (Decision/Constraint-sourced
                    # cluster members previously failed to link at all).
                    row["_source_table"] = table
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
            desc = n.get("description", "")
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
            from campy.brain.hippocampus.graph.embeddings import embed
            proc_emb = embed(description, model_name=embedding_model)
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
                node_id = node.get("id", "")
                source_table = node.get("_source_table", "Concept")
                id_col = _SOURCE_ID_COLUMNS.get(source_table, "concept_id")
                if not node_id:
                    continue
                try:
                    await db.execute_write(
                        f"MATCH (pr:Procedure {{procedure_id: $pid}}), "
                        f"(c:{source_table} {{{id_col}: $cid}}) "
                        "MERGE (pr)-[r:DISTILLED_FROM]->(c) "
                        "ON CREATE SET r.synthesized_at = timestamp($now)",
                        {"pid": proc_id, "cid": node_id, "now": now},
                    )
                except Exception:
                    _logger.exception(
                        "[BasalGanglia] Failed to link avoidance Procedure %s to %s %s",
                        proc_id[:8], source_table, node_id,
                    )

            synthesized += 1
            _logger.info(
                "[BasalGanglia] avoidance Procedure %s from %d nodes: %s",
                proc_id[:8], len(cluster_nodes), name,
            )
        except Exception:
            _logger.exception("[BasalGanglia] Failed to create avoidance Procedure")
            errors += 1

    return synthesized, errors
