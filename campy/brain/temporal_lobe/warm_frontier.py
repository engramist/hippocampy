"""
mcp_engine/warm_frontier.py — Passive Graph Pre-Activation (B91)

Maintains a bounded 'warm frontier' of nodes that are likely to be needed soon.
Activated nodes are preferred in retrieval, enabling zero-latency context matching.
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient

from campy.brain.hippocampus.table_registry import tables_with
from campy.brain.hippocampus.graph.gateway import get_gateway

_logger = logging.getLogger(__name__)

# Activation Parameters — B375: these are now the *defaults*, overridable
# per the [retrieval.warm_frontier] config section (see config.py's
# _DEFAULT_CONFIG and campy.toml's documented example). Module-level
# constants stay in place so any caller that doesn't have a config dict
# handy (or omits the section) gets byte-identical behavior to before.
MAX_WARM_NODES = 20           # Bound the frontier size
SIMILARITY_WEIGHT = 0.6       # B279: weight applied to true cosine similarity
HOPS_DECAY = 0.5             # Multiplier for 1-hop neighbor activation
MIN_ACTIVATION = 0.3          # B279: minimum activation from true cosine-derived score

# Node type → primary key column mapping
NODE_PK_MAP = {table.name: table.pk for table in tables_with("warmable")}

_ARTIFACT_TABLES = [
    (table.name, table.vector_index, table.pk)
    for table in tables_with("warm_seed")
    if table.vector_index is not None
]

async def compute_warm_frontier(
    db: KuzuClient,
    session_id: str,
    message_vector: List[float],
    config: Dict[str, Any] = {},
) -> int:
    """
    Update the warm frontier for a session based on a new message vector.
    
    1. Phase 1: Direct Activation — vector search for nodes similar to message.
    2. Phase 2: Spread Activation — expand to 1-hop neighbors of Phase 1 nodes.
    3. Bounding: Keep top N nodes by activation_score.
    4. Persistence: Write WARM_NODE relationships.
    """
    if session_id == "unknown":
        return 0

    wf_config = (config or {}).get("retrieval", {}).get("warm_frontier", {})
    max_warm_nodes = wf_config.get("max_warm_nodes", MAX_WARM_NODES)
    similarity_weight = wf_config.get("similarity_weight", SIMILARITY_WEIGHT)
    hops_decay = wf_config.get("hops_decay", HOPS_DECAY)
    min_activation = wf_config.get("min_activation", MIN_ACTIVATION)
    supernode_degree_threshold = wf_config.get(
        "supernode_degree_threshold", SUPERNODE_DEGREE_THRESHOLD
    )
    supernode_top_n = wf_config.get("supernode_top_n", SUPERNODE_TOP_N)

    now = datetime.now(timezone.utc).isoformat()
    activated: Dict[str, Tuple[str, float]] = {}  # node_id -> (table, score)

    # Phase 1: Direct Activation (Vector Search)
    for table, index, pk in _ARTIFACT_TABLES:
        try:
            # Search for top 10 most similar nodes per table
            results = db.vector_search(table, index, message_vector, 10)
            for r in results:
                node = r["node"]
                if node.get("archived", False):
                    continue
                node_id = node.get(pk)
                score = r["score"] * similarity_weight
                if node_id:
                    activated[node_id] = (table, score)
        except Exception:
            _logger.debug("Phase 1 activation failed for table %s", table)

    # Phase 2: Spread Activation (1-hop Neighbors)
    # We only spread from nodes with strong direct activation
    seeds = [(nid, table, score) for nid, (table, score) in activated.items() if score > 0.4]

    for seed_id, seed_table, seed_score in seeds:
        try:
            # Simple 1-hop expansion to other artifacts
            # We follow relationships like ESTABLISHED, REIFIED_AS, HAS_PREF_LABEL etc.
            # For simplicity, we query common artifact relationships.
            neighbors = await _get_artifact_neighbors(
                db, seed_id, seed_table,
                supernode_degree_threshold=supernode_degree_threshold,
                supernode_top_n=supernode_top_n,
            )
            for n_id, n_table in neighbors:
                if n_id in activated:
                    # Boost existing score
                    table, old_score = activated[n_id]
                    activated[n_id] = (table, min(1.0, old_score + seed_score * hops_decay))
                else:
                    new_score = seed_score * hops_decay
                    if new_score >= min_activation:
                        activated[n_id] = (n_table, new_score)
        except Exception:
            pass

    # Phase 3: Bounding & Filtering
    # Sort by score descending and take top N
    sorted_nodes = sorted(
        [(nid, table, score) for nid, (table, score) in activated.items()],
        key=lambda x: x[2],
        reverse=True
    )[:max_warm_nodes]

    if not sorted_nodes:
        return 0

    # Phase 4: Persistence (WARM_NODE edges)
    gw = get_gateway(db)
    # Clear old warm frontier for this session first
    try:
        await gw.run("temporal_lobe.warm_clear_session", sid=session_id)
    except Exception:
        pass

    count = 0
    for nid, table, score in sorted_nodes:
        pk = NODE_PK_MAP.get(table)
        if not pk: continue
        
        try:
            qname = f"temporal_lobe.warm_link_{table.lower()}"
            await gw.run(qname, sid=session_id, nid=nid, score=score, now=now)
            count += 1
        except Exception:
            _logger.debug("Phase 4 activation write failed for %s", nid)

    # Update Session.last_warm_frontier_at
    try:
        await gw.run("temporal_lobe.warm_set_session_time", sid=session_id, now=now)
    except Exception:
        pass

    return count

# B375: dense-supernode safeguard thresholds — a node with more incident
# edges than this bypasses open expansion; only its top-N neighbors by
# pathway_strength survive, preventing background spread activation from
# exploding into a giant hub.
SUPERNODE_DEGREE_THRESHOLD = 50
SUPERNODE_TOP_N = 5


async def _get_artifact_neighbors(
    db: Any,
    node_id: str,
    table: str,
    supernode_degree_threshold: int = SUPERNODE_DEGREE_THRESHOLD,
    supernode_top_n: int = SUPERNODE_TOP_N,
) -> List[Tuple[str, str]]:
    """Helper to find related artifacts in the graph.

    B375: applies the dense-supernode safeguard — if a node's raw degree
    (across all followed relationships/directions) exceeds
    supernode_degree_threshold, only the top supernode_top_n neighbors by
    pathway_strength are kept, rather than spreading activation across
    every incident edge of a giant hub.
    """
    neighbors_with_strength: List[Tuple[str, str, float]] = []
    pk = NODE_PK_MAP.get(table)
    if not pk: return []
    gw = get_gateway(db)

    # Relationships to follow for spread activation
    # Concept -> Decision/Constraint/etc (REIFIED_AS)
    # Decision/Constraint -> Concept (ESTABLISHED via Message/Extract - handled via CO_OCCURS_WITH)
    # Concept -> Concept (CO_OCCURS_WITH, REQUIRES, ENABLES, etc)

    rels_to_follow = ["REIFIED_AS", "REQUIRES", "ENABLES", "PART_OF", "IMPLEMENTS", "CO_OCCURS_WITH"]

    for rel in rels_to_follow:
        for target_table, target_pk in NODE_PK_MAP.items():
            try:
                # Check both directions
                q_out_name = f"temporal_lobe.warm_neighbor_out_{table.lower()}_{rel.lower()}_{target_table.lower()}"
                r_out = await gw.run(q_out_name, id=node_id)
                for row in (r_out or []):
                    val = row.get(f"b.{target_pk}", row.get(target_pk)) if isinstance(row, dict) else row[0]
                    strength = row.get("b.pathway_strength", row.get("pathway_strength")) if isinstance(row, dict) else (row[1] if len(row) > 1 else None)
                    neighbors_with_strength.append((str(val), target_table, float(strength) if strength is not None else 0.0))

                q_in_name = f"temporal_lobe.warm_neighbor_in_{table.lower()}_{rel.lower()}_{target_table.lower()}"
                r_in = await gw.run(q_in_name, id=node_id)
                for row in (r_in or []):
                    val = row.get(f"b.{target_pk}", row.get(target_pk)) if isinstance(row, dict) else row[0]
                    strength = row.get("b.pathway_strength", row.get("pathway_strength")) if isinstance(row, dict) else (row[1] if len(row) > 1 else None)
                    neighbors_with_strength.append((str(val), target_table, float(strength) if strength is not None else 0.0))
            except Exception:
                pass

    # Dedup by (node_id, table), keeping the max observed pathway_strength
    # (the same neighbor can be reached via more than one relationship).
    deduped: Dict[Tuple[str, str], float] = {}
    for nid, ntable, strength in neighbors_with_strength:
        key = (nid, ntable)
        if key not in deduped or strength > deduped[key]:
            deduped[key] = strength

    if len(deduped) > supernode_degree_threshold:
        top = sorted(deduped.items(), key=lambda kv: kv[1], reverse=True)[:supernode_top_n]
        return [key for key, _ in top]

    return list(deduped.keys())

async def activate_warm_node(
    db: Any, session_id: str, node_id: str, table: str, score: float
) -> bool:
    """Pre-activate a single node into a session's warm frontier.

    B375 gap 4: Step 4b's associative trigger check matches an incoming
    turn's entity against stored Lessons/Procedures via vector search — a
    match above threshold should also land the node in the warm frontier
    immediately (so it is boosted on the very next retrieval), not just
    get a trigger_pattern bound for future hook-based injection.

    Unlike `compute_warm_frontier`, this does NOT clear the session's
    existing frontier first — it is an incremental single-node addition,
    not a full recompute.
    """
    if session_id == "unknown" or not node_id:
        return False
    pk = NODE_PK_MAP.get(table)
    if not pk:
        return False

    now = datetime.now(timezone.utc).isoformat()
    gw = get_gateway(db)
    try:
        qname = f"temporal_lobe.warm_link_{table.lower()}"
        await gw.run(qname, sid=session_id, nid=node_id, score=score, now=now)
        return True
    except Exception:
        _logger.debug("activate_warm_node failed for %s/%s", table, node_id)
        return False


def get_warm_nodes(db: Any, session_id: str) -> Dict[str, float]:
    """
    Retrieve warm frontier for a session.
    Returns node_id -> activation_score map.
    """
    warm = {}
    if session_id == "unknown":
        return warm
    gw = get_gateway(db)

    for table, pk in NODE_PK_MAP.items():
        try:
            qname = f"temporal_lobe.warm_get_{table.lower()}"
            rows = gw.run_sync(qname, sid=session_id)
            for row in (rows or []):
                nid = row.get(f"n.{pk}", row.get(pk)) if isinstance(row, dict) else row[0]
                score = row.get("w.activation_score", row.get("activation_score")) if isinstance(row, dict) else (row[1] if len(row) > 1 else 0.0)
                if nid:
                    warm[str(nid)] = float(score or 0.0)
        except Exception:
            pass
            
    return warm
