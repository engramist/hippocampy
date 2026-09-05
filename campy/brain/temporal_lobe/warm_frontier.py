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
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

from campy.brain.hippocampus.table_registry import tables_with
from campy.brain.hippocampus.graph.gateway import get_gateway

_logger = logging.getLogger(__name__)

# Activation Parameters
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
                score = r["score"] * SIMILARITY_WEIGHT
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
            neighbors = await _get_artifact_neighbors(db, seed_id, seed_table)
            for n_id, n_table in neighbors:
                if n_id in activated:
                    # Boost existing score
                    table, old_score = activated[n_id]
                    activated[n_id] = (table, min(1.0, old_score + seed_score * HOPS_DECAY))
                else:
                    new_score = seed_score * HOPS_DECAY
                    if new_score >= MIN_ACTIVATION:
                        activated[n_id] = (n_table, new_score)
        except Exception:
            pass

    # Phase 3: Bounding & Filtering
    # Sort by score descending and take top N
    sorted_nodes = sorted(
        [(nid, table, score) for nid, (table, score) in activated.items()],
        key=lambda x: x[2],
        reverse=True
    )[:MAX_WARM_NODES]

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

async def _get_artifact_neighbors(db: Any, node_id: str, table: str) -> List[Tuple[str, str]]:
    """Helper to find related artifacts in the graph."""
    neighbors = []
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
                    neighbors.append((str(val), target_table))

                q_in_name = f"temporal_lobe.warm_neighbor_in_{table.lower()}_{rel.lower()}_{target_table.lower()}"
                r_in = await gw.run(q_in_name, id=node_id)
                for row in (r_in or []):
                    val = row.get(f"b.{target_pk}", row.get(target_pk)) if isinstance(row, dict) else row[0]
                    neighbors.append((str(val), target_table))
            except Exception:
                pass
                
    return list(set(neighbors)) # Dedup

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
