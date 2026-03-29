from __future__ import annotations
import logging
from typing import TYPE_CHECKING, List, Dict, Any, Set, Optional, Tuple

if TYPE_CHECKING:
    from mcp_engine.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)

# Traversal is constrained to allowlisted relationship types.
_TRAVERSABLE_RELS = frozenset({
    "REQUIRES", "ENABLES", "REPLACES", "CONTRADICTS", "PART_OF",
    "CHOSEN_OVER", "IMPLEMENTS", "EXTENDS", "ALTERNATIVE_TO",
    "CO_OCCURS_WITH", "REIFIED_AS", "DEPRECATED_BY",
    "BELONGS_TO", "DERIVED_FROM", "ESTABLISHED",
    "HAS_PREF_LABEL", "HAS_ALT_LABEL",
    "PRODUCED_LESSON",
    "ESTABLISHED_IN",
})

# Node tables to search when resolving start_node_id
_NODE_TABLES = [
    ("Concept",          "concept_id"),
    ("Decision",         "decision_id"),
    ("Constraint",       "constraint_id"),
    ("Requirement",      "requirement_id"),
    ("ActionItem",       "action_item_id"),
    ("GlobalConstraint", "global_constraint_id"),
    ("GlobalPreference", "global_preference_id"),
    ("MainQuest",        "quest_id"),
    ("SideQuest",        "quest_id"),
    ("Message",          "message_id"),
    ("Document",         "document_id"),
    ("Lesson",           "lesson_id"),
]

def _get_pk_for_table(table: str) -> str | None:
    for t, pk in _NODE_TABLES:
        if t == table:
            return pk
    return None

_MAX_DEPTH = 5

async def explore_graph(params: Dict[str, Any], db: KuzuClient, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Traverse knowledge graph from a seed node, following relationships up to N hops.
    Enables LLMs to follow causal chains and multi-hop relationships.
    """
    start_id = params.get("start_node_id", "").strip()
    session_id = params.get("session_id", "").strip()
    depth = min(max(int(params.get("depth", 3)), 1), _MAX_DEPTH)
    strategy = params.get("strategy", "dfs").lower()
    edge_types = params.get("edge_types", [])
    direction = params.get("direction", "both").lower()

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

    # 1. Find start node
    start_table = None
    for table, pk in _NODE_TABLES:
        try:
            r = db.execute(f"MATCH (n:{table}) WHERE n.{pk} = $id RETURN n LIMIT 1", {"id": start_id})
            if r.has_next():
                start_table = table
                break
        except Exception:
            continue
    
    if not start_table:
        return {
            "start_node_id": start_id,
            "paths": [],
            "total_nodes_visited": 0,
            "exploration_complete": False,
            "error": f"Start node {start_id} not found"
        }

    # 2. Traversal logic
    # Max nodes visited to prevent runaway traversal
    MAX_NODES = 1000
    
    if strategy == "bfs":
        paths, total_visited = _bfs_traversal(db, start_id, start_table, depth, edge_types_to_use, direction, MAX_NODES)
    else:
        paths, total_visited = _dfs_traversal(db, start_id, start_table, depth, edge_types_to_use, direction, MAX_NODES)

    return {
        "paths": paths,
        "total_nodes_visited": total_visited,
        "exploration_complete": True
    }

def _get_node_data(db: KuzuClient, node_id: str, table: str) -> Dict[str, Any]:
    pk = _get_pk_for_table(table)
    # Most tables have text_raw and confidence.
    query = f"MATCH (n:{table}) WHERE n.{pk} = $id RETURN n.text_raw, n.confidence"
    try:
        r = db.execute(query, {"id": node_id})
        if r.has_next():
            row = r.get_next()
            return {
                "node_id": node_id,
                "node_type": table,
                "text": str(row[0] or "")[:200],
                "confidence": float(row[1] or 0.0)
            }
    except Exception:
        pass
    return {"node_id": node_id, "node_type": table, "text": "", "confidence": 0.0}

def _get_neighbors(db: KuzuClient, node_id: str, node_table: str, edge_types: List[str], direction: str) -> List[Dict[str, Any]]:
    pk = _get_pk_for_table(node_table)
    neighbors = []
    
    for target_table, target_pk in _NODE_TABLES:
        for rel in edge_types:
            queries = []
            if direction in ("outgoing", "both"):
                queries.append((
                    f"MATCH (a:{node_table})-[r:{rel}]->(b:{target_table}) WHERE a.{pk} = $id "
                    f"RETURN b.{target_pk}, r.confidence", "out", rel, target_table
                ))
            if direction in ("incoming", "both"):
                queries.append((
                    f"MATCH (a:{node_table})<-[r:{rel}]-(b:{target_table}) WHERE a.{pk} = $id "
                    f"RETURN b.{target_pk}, r.confidence", "in", rel, target_table
                ))
            
            for query, qdir, qrel, qtable in queries:
                try:
                    r = db.execute(query, {"id": node_id})
                    while r.has_next():
                        row = r.get_next()
                        target_id = str(row[0])
                        # Kuzu might return None for missing properties on REL
                        try:
                            rel_conf = float(row[1]) if row[1] is not None else 1.0
                        except (IndexError, TypeError, ValueError):
                            rel_conf = 1.0
                            
                        neighbors.append({
                            "id": target_id,
                            "table": qtable,
                            "rel_type": qrel,
                            "rel_conf": rel_conf,
                            "direction": qdir
                        })
                except Exception:
                    continue
    return neighbors

def _bfs_traversal(db: KuzuClient, start_id: str, start_table: str, max_depth: int, edge_types: List[str], direction: str, max_nodes: int) -> Tuple[List[Dict[str, Any]], int]:
    paths = []
    visited_node_ids = {start_id}
    start_node_data = _get_node_data(db, start_id, start_table)
    
    # queue of (current_node_id, current_node_table, current_path_nodes, current_path_edges, current_depth)
    queue = [(start_id, start_table, [start_node_data], [], 0)]
    
    while queue and len(visited_node_ids) < max_nodes:
        curr_id, curr_table, curr_nodes, curr_edges, curr_depth = queue.pop(0)
        
        # Every node reached (other than start) completes a path from start
        if curr_depth > 0:
            path_strength = sum(n["confidence"] for n in curr_nodes) / len(curr_nodes) if curr_nodes else 0.0
            paths.append({
                "nodes": curr_nodes,
                "edges": curr_edges,
                "path_depth": curr_depth,
                "path_strength": round(path_strength, 3)
            })

        if curr_depth < max_depth:
            neighbors = _get_neighbors(db, curr_id, curr_table, edge_types, direction)
            for nbr in neighbors:
                # To avoid cycles within a single path
                if nbr["id"] in [n["node_id"] for n in curr_nodes]:
                    continue
                
                nbr_node_data = _get_node_data(db, nbr["id"], nbr["table"])
                visited_node_ids.add(nbr["id"])
                
                new_nodes = curr_nodes + [nbr_node_data]
                if nbr["direction"] == "out":
                    new_edge = {"from": curr_id, "to": nbr["id"], "type": nbr["rel_type"], "confidence": nbr["rel_conf"]}
                else:
                    new_edge = {"from": nbr["id"], "to": curr_id, "type": nbr["rel_type"], "confidence": nbr["rel_conf"]}
                
                new_edges = curr_edges + [new_edge]
                queue.append((nbr["id"], nbr["table"], new_nodes, new_edges, curr_depth + 1))
                
                if len(visited_node_ids) >= max_nodes:
                    break
                
    return paths, len(visited_node_ids)

def _dfs_traversal(db: KuzuClient, start_id: str, start_table: str, max_depth: int, edge_types: List[str], direction: str, max_nodes: int) -> Tuple[List[Dict[str, Any]], int]:
    paths = []
    visited_node_ids = {start_id}
    start_node_data = _get_node_data(db, start_id, start_table)
    
    def _dfs(curr_id: str, curr_table: str, curr_nodes: List[Dict[str, Any]], curr_edges: List[Dict[str, Any]], curr_depth: int):
        if len(visited_node_ids) >= max_nodes:
            return

        if curr_depth > 0:
            path_strength = sum(n["confidence"] for n in curr_nodes) / len(curr_nodes) if curr_nodes else 0.0
            paths.append({
                "nodes": curr_nodes,
                "edges": curr_edges,
                "path_depth": curr_depth,
                "path_strength": round(path_strength, 3)
            })
            
        if curr_depth < max_depth:
            neighbors = _get_neighbors(db, curr_id, curr_table, edge_types, direction)
            for nbr in neighbors:
                if nbr["id"] in [n["node_id"] for n in curr_nodes]:
                    continue
                
                nbr_node_data = _get_node_data(db, nbr["id"], nbr["table"])
                visited_node_ids.add(nbr["id"])
                
                new_nodes = curr_nodes + [nbr_node_data]
                if nbr["direction"] == "out":
                    new_edge = {"from": curr_id, "to": nbr["id"], "type": nbr["rel_type"], "confidence": nbr["rel_conf"]}
                else:
                    new_edge = {"from": nbr["id"], "to": curr_id, "type": nbr["rel_type"], "confidence": nbr["rel_conf"]}
                
                new_edges = curr_edges + [new_edge]
                _dfs(nbr["id"], nbr["table"], new_nodes, new_edges, curr_depth + 1)
                
                if len(visited_node_ids) >= max_nodes:
                    break

    _dfs(start_id, start_table, [start_node_data], [], 0)
    return paths, len(visited_node_ids)
