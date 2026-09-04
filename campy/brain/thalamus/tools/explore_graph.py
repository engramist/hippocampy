from __future__ import annotations
import logging
from typing import TYPE_CHECKING, List, Dict, Any, Tuple

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
from campy.brain.hippocampus.graph.gateway import get_gateway
from campy.brain.hippocampus.graph.queries.explore import build_frontier_query as _build_frontier_query, internal_id_literal as _internal_id_literal

from campy.brain.hippocampus.schema import get_relationship_types
from campy.brain.hippocampus.table_registry import pk_for, tables_with

_logger = logging.getLogger(__name__)

# Traversal is constrained to allowlisted relationship types.
# Derived dynamically from schema.py REL_TABLES (B72).
_TRAVERSABLE_RELS = frozenset(get_relationship_types())

# Node tables to search when resolving start_node_id
_NODE_TABLES = [(table.name, table.pk) for table in tables_with("traversable")]

def _get_pk_for_table(table: str) -> str | None:
    return pk_for(table)

_MAX_DEPTH = 5
_MAX_NODES = 1000
_TEMPORAL_CONTEXT_RELS = frozenset(
    rel for rel in ("NEXT_MESSAGE", "CAUSED_BY", "ESTABLISHED_IN") if rel in _TRAVERSABLE_RELS
)


def _node_payload(node: Dict[str, Any] | None, fallback_id: str = "") -> Dict[str, Any]:
    node = node or {}
    label = str(node.get("_label") or "")
    pk = _get_pk_for_table(label) if label else None
    node_id = ""
    if pk:
        node_id = str(node.get(pk) or "")
    if not node_id:
        node_id = str(node.get("id") or fallback_id or "")
    return {
        "node_id": node_id,
        "node_type": label,
        "text": str(node.get("text_raw") or "")[:200],
        "confidence": float(node.get("confidence") or 0.0),
    }


def _edge_payload(src_id: str, dst_id: str, rel_type: str, rel_conf: Any) -> Dict[str, Any]:
    try:
        confidence = float(rel_conf) if rel_conf is not None else 1.0
    except (TypeError, ValueError):
        confidence = 1.0
    return {
        "from": src_id,
        "to": dst_id,
        "type": rel_type,
        "confidence": confidence,
    }


# _internal_id_literal and _build_frontier_query are centralized in queries.explore


def _execute_frontier_query(db: KuzuClient, frontier_internal_ids: List[Dict[str, int]],
                            edge_types: List[str], direction: str) -> List[Dict[str, Any]]:
    if not frontier_internal_ids:
        return []

    query = _build_frontier_query(edge_types, direction, frontier_internal_ids)
    rows: List[Dict[str, Any]] = []
    try:
        result = db.execute(query)
        while result.has_next():
            row = result.get_next()
            if not row:
                continue
            current_node = row[0] if len(row) > 0 else {}
            neighbor_node = row[1] if len(row) > 1 else {}
            rel_type = str(row[2] or "") if len(row) > 2 else ""
            rel_conf = row[3] if len(row) > 3 else 1.0
            current_payload = _node_payload(current_node)
            neighbor_payload = _node_payload(neighbor_node)
            if not current_payload["node_id"] or not neighbor_payload["node_id"]:
                continue
            neighbor_internal_id = neighbor_node.get("_id") if isinstance(neighbor_node, dict) else None
            rows.append({
                "current_id": current_payload["node_id"],
                "current_table": current_payload["node_type"],
                "neighbor_id": neighbor_payload["node_id"],
                "neighbor_table": neighbor_payload["node_type"],
                "current_node": current_node,
                "neighbor_node": neighbor_node,
                "neighbor_internal_id": neighbor_internal_id,
                "rel_type": rel_type,
                "rel_conf": rel_conf,
                "direction": direction,
            })
    except Exception:
        _logger.exception("Frontier expansion failed for %s", direction)
    return rows


def _expand_frontier(db: KuzuClient, frontier_internal_ids: List[Dict[str, int]],
                     edge_types: List[str], direction: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if direction in ("outgoing", "both"):
        rows.extend(_execute_frontier_query(db, frontier_internal_ids, edge_types, "outgoing"))
    if direction in ("incoming", "both"):
        rows.extend(_execute_frontier_query(db, frontier_internal_ids, edge_types, "incoming"))
    return rows


def _reconstruct_paths(start_id: str, start_node_data: Dict[str, Any],
                       parents: Dict[str, Tuple[str, Dict[str, Any]]],
                       node_cache: Dict[str, Dict[str, Any]],
                       discovery_order: List[str]) -> List[Dict[str, Any]]:
    paths: List[Dict[str, Any]] = []
    for node_id in discovery_order:
        curr_id = node_id
        curr_nodes = [node_cache.get(curr_id, {"node_id": curr_id, "node_type": "", "text": "", "confidence": 0.0})]
        curr_edges = []
        while curr_id != start_id and curr_id in parents:
            parent_id, edge = parents[curr_id]
            curr_edges.append(edge)
            curr_id = parent_id
            curr_nodes.append(node_cache.get(curr_id, start_node_data if curr_id == start_id else {
                "node_id": curr_id,
                "node_type": "",
                "text": "",
                "confidence": 0.0,
            }))
        curr_nodes.reverse()
        curr_edges.reverse()
        path_strength = sum(n["confidence"] for n in curr_nodes) / len(curr_nodes) if curr_nodes else 0.0
        paths.append({
            "nodes": curr_nodes,
            "edges": curr_edges,
            "path_depth": max(len(curr_nodes) - 1, 0),
            "path_strength": round(path_strength, 3),
        })
    return paths


def _traverse(db: KuzuClient, start_id: str, start_node_data: Dict[str, Any],
              start_internal_id: Dict[str, int], max_depth: int,
              edge_types: List[str], direction: str, max_nodes: int,
              strategy: str) -> Tuple[List[Dict[str, Any]], int, Dict[str, Dict[str, int]]]:
    visited_node_ids = {start_id}
    node_cache = {start_id: start_node_data}
    # Internal ids drive the next hop's query (see _internal_id_literal) and
    # are kept separate from node_cache/the public node payload - they must
    # never leak into the response shape.
    internal_id_cache: Dict[str, Dict[str, int]] = {start_id: start_internal_id}
    parents: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    discovery_order: List[str] = []
    frontier_internal_ids = [start_internal_id]

    for _depth_level in range(1, max_depth + 1):
        if not frontier_internal_ids or len(visited_node_ids) >= max_nodes:
            break

        edges = _expand_frontier(db, frontier_internal_ids, edge_types, direction)
        next_frontier_internal_ids: List[Dict[str, int]] = []
        for edge in edges:
            dst_id = edge["neighbor_id"]
            if dst_id in visited_node_ids:
                continue

            visited_node_ids.add(dst_id)
            node_cache[dst_id] = _node_payload(edge["neighbor_node"], dst_id)
            internal_id_cache[dst_id] = edge["neighbor_internal_id"]
            parents[dst_id] = (
                edge["current_id"],
                _edge_payload(
                    edge["neighbor_id"] if edge["direction"] == "incoming" else edge["current_id"],
                    edge["current_id"] if edge["direction"] == "incoming" else edge["neighbor_id"],
                    edge["rel_type"],
                    edge["rel_conf"],
                ),
            )
            discovery_order.append(dst_id)
            if edge["neighbor_internal_id"] is not None:
                next_frontier_internal_ids.append(edge["neighbor_internal_id"])

            if len(visited_node_ids) >= max_nodes:
                break

        frontier_internal_ids = next_frontier_internal_ids

    ordered_ids = discovery_order if strategy == "bfs" else list(reversed(discovery_order))
    paths = _reconstruct_paths(start_id, node_cache[start_id], parents, node_cache, ordered_ids)
    return paths, len(visited_node_ids), internal_id_cache

async def explore_graph(params: Dict[str, Any], db: KuzuClient, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Traverse knowledge graph from a seed node, following relationships up to N hops.
    Enables LLMs to follow causal chains and multi-hop relationships.

    B125: Optional context_window parameter (0-3) returns temporal/causal neighbors around each node.
    """
    start_id = params.get("start_node_id", "").strip()
    session_id = params.get("session_id", "").strip()
    depth = min(max(int(params.get("depth", 3)), 1), _MAX_DEPTH)
    strategy = params.get("strategy", "dfs").lower()
    edge_types = params.get("edge_types", [])
    direction = params.get("direction", "both").lower()
    context_window = min(max(int(params.get("context_window", 0)), 0), 3)  # B125

    if not start_id:
        return {"error": "start_node_id is required"}
    if not session_id:
        return {"error": "session_id is required"}
    
    # Filter edge types to only allowed ones
    if edge_types:
        if isinstance(edge_types, str):
            edge_types = [edge_types]
        valid_edge_types = [t.upper() for t in edge_types if t.upper() in _TRAVERSABLE_RELS]
        if not valid_edge_types:
             return {
                 "error": "No valid traversable edge types provided", 
                 "provided": edge_types,
                 "allowed": sorted(_TRAVERSABLE_RELS)
             }
        edge_types_to_use = valid_edge_types
    else:
        edge_types_to_use = list(_TRAVERSABLE_RELS)

    if direction not in ("outgoing", "incoming", "both"):
        direction = "both"

    # 1. Find start node. Fetching id(n) alongside the node itself means we
    # never need a separate _get_node_data() round-trip - the node's own
    # properties and its internal id (needed to seed the frontier) both
    # come back from this one query.
    start_table = None
    start_node_data = None
    start_internal_id = None
    gw = get_gateway(db)
    for table, pk in _NODE_TABLES:
        try:
            rows = gw.run_sync(f"explore.start_node_{table.lower()}", id=start_id)
            if rows:
                row = rows[0]
                node_dict = row[0] if len(row) > 0 else {}
                start_internal_id = row[1] if len(row) > 1 else None
                start_node_data = _node_payload(node_dict, start_id)
                start_table = table
                break
        except Exception:
            continue

    if not start_table or start_internal_id is None:
        return {
            "start_node_id": start_id,
            "paths": [],
            "total_nodes_visited": 0,
            "exploration_complete": False,
            "error": f"Start node {start_id} not found"
        }

    # 2. Traversal logic
    paths, total_visited, internal_id_cache = _traverse(
        db,
        start_id,
        start_node_data,
        start_internal_id,
        depth,
        edge_types_to_use,
        direction,
        _MAX_NODES,
        strategy,
    )

    # B125: Add context around nodes if context_window > 0
    if context_window > 0:
        paths = _add_temporal_context(db, paths, context_window, internal_id_cache)

    return {
        "paths": paths,
        "total_nodes_visited": total_visited,
        "exploration_complete": True,
        "exploration_truncated": total_visited >= _MAX_NODES,
        "context_window": context_window,  # B125: Track if context was included
    }


def _add_temporal_context(db: KuzuClient, paths: List[Dict[str, Any]], context_window: int,
                          internal_id_cache: Dict[str, Dict[str, int]]) -> List[Dict[str, Any]]:
    """B125: Add temporal/causal context neighbors around each node in paths.

    For each node, fetch up to context_window neighbors connected by temporal edges
    (NEXT_MESSAGE, CAUSED_BY, ESTABLISHED_IN) and format as context slices.
    Context text is truncated to 200 chars per neighbor.
    """
    if context_window <= 0:
        return paths
    if not _TEMPORAL_CONTEXT_RELS:
        return paths

    enhanced_paths = []
    node_refs: Dict[str, str] = {}
    for path in paths:
        for node in path.get("nodes", []):
            node_id = node.get("node_id")
            node_table = node.get("node_type")
            if node_id and node_table:
                node_refs[node_id] = node_table

    if not node_refs:
        return paths

    frontier_internal_ids = [
        internal_id_cache[node_id] for node_id in node_refs
        if internal_id_cache.get(node_id) is not None
    ]
    if not frontier_internal_ids:
        return paths

    context_rows = _expand_frontier(db, frontier_internal_ids, list(_TEMPORAL_CONTEXT_RELS), "both")
    context_by_source: Dict[str, List[str]] = {}
    for row in context_rows:
        src_id = row["current_id"]
        if src_id not in node_refs:
            continue
        dst_payload = _node_payload(row.get("neighbor_node") if isinstance(row.get("neighbor_node"), dict) else None, row["neighbor_id"])
        if not dst_payload["text"]:
            continue
        context_by_source.setdefault(src_id, []).append(dst_payload["text"])

    for path in paths:
        enhanced_nodes = []
        for node in path.get("nodes", []):
            enhanced_node = dict(node)
            node_id = node.get("node_id")
            if node_id and node_id in context_by_source:
                context_items = context_by_source[node_id][:context_window]
                if context_items:
                    enhanced_node["context_neighbors"] = [text[:200] for text in context_items]
                    enhanced_node["context_count"] = len(context_items)
            enhanced_nodes.append(enhanced_node)
        enhanced_path = dict(path)
        enhanced_path["nodes"] = enhanced_nodes
        enhanced_paths.append(enhanced_path)

    return enhanced_paths
