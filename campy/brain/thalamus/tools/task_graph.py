from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import GraphGateway
from campy.brain.hippocampus.graph.queries import REGISTRY


def _gateway(db) -> GraphGateway:
    if isinstance(db, GraphGateway):
        return db
    return GraphGateway(db, REGISTRY)

"""
mcp_engine/tools/task_graph.py — DAG Task Graph Schema Helpers (B127/B128)

Provides helper logic for managing TaskGraph and TaskNode DAGs,
including cycle detection and ready-frontier queries.

B323 extends this module (rather than adding a sibling) with declared
task dependency edges — TASK_BLOCKS / TASK_ENABLES between MainQuest,
SideQuest, and ActionItem nodes. This is deliberately a separate mechanism
from the TaskGraph/TaskNode DAG above: TaskGraph/TaskNode is B127/B128's
own internal execution DAG, while TASK_BLOCKS/TASK_ENABLES declares
dependency between backlog-card-level work items. Both use the same
bounded-cycle-check pattern (see _dag_has_cycle above vs.
_task_dependency_cycle_path below).
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# B323 — declared task dependency graph (TASK_BLOCKS / TASK_ENABLES)
# ---------------------------------------------------------------------------

# Node tables TASK_BLOCKS/TASK_ENABLES are defined over (schema.py), and
# each table's primary-key column.
TASK_DEPENDENCY_TABLES: dict[str, str] = {
    "MainQuest": "quest_id",
    "SideQuest": "quest_id",
    "ActionItem": "action_item_id",
}

_TASK_DEPENDENCY_REL_TYPES = ("TASK_BLOCKS", "TASK_ENABLES")

# B323: bounded cycle-check depth. The card is explicit that this is a
# bounded traversal, not full transitive-closure maintenance — a genuine
# cycle 11+ hops away in a same-type dependency chain would be missed, but
# that is judged vanishingly unlikely for hand-declared card dependencies
# and is the same tradeoff the card's own spec calls for ("*..10").
_CYCLE_CHECK_BOUND = 10


class TaskDependencyCycleError(ValueError):
    """Raised when a TASK_BLOCKS/TASK_ENABLES edge would close a cycle."""


async def _task_dependency_cycle_path(
    db: KuzuClient, rel_type: str, table: str, pk: str, from_id: str, to_id: str
) -> Optional[List[str]]:
    """Return the existing path (list of node ids, `to_id` first) if a path
    already exists from `to_id` back to `from_id` — meaning the caller's
    proposed (from_id)-[:rel_type]->(to_id) edge would close a cycle.

    Bounded to _CYCLE_CHECK_BOUND hops (`*1..10`), matching the card's
    instruction to check with a bounded traversal rather than maintain full
    transitive closure. Mirrors _dag_has_cycle's direction convention above
    (probe from the target back to the source).
    """
    gw = _gateway(db)
    qname = f"task_graph.cycle_check_{rel_type.lower()}_{table.lower()}"
    try:
        rows = gw.run_sync(qname, to_id=to_id, from_id=from_id)
        if rows:
            row = rows[0]
            path_nodes = row.get("path_nodes") or row.get("NODES(p)") or (row[0] if isinstance(row, (list, tuple)) else next(iter(row.values()), None))
            if path_nodes:
                return [str(dict(n).get(pk)) for n in path_nodes]
    except Exception:
        _logger.exception(
            "_task_dependency_cycle_path failed for %s %s -> %s", rel_type, from_id, to_id
        )
    return None


async def add_task_dependency_edge(
    db: KuzuClient,
    *,
    rel_type: str,
    table: str,
    from_id: str,
    to_id: str,
    declared_by: str,
    confidence: float = 1.0,
    source: Optional[str] = None,
    source_version: Optional[str] = None,
    authority: Optional[str] = None,
    observed_at: Optional[str] = None,
) -> Dict[str, Any]:
    """B323 — declare a TASK_BLOCKS or TASK_ENABLES edge between two
    same-type task nodes (MainQuest/SideQuest/ActionItem), rejecting the
    write if it would close a cycle.

    Raises:
        ValueError: unsupported rel_type/table.
        TaskDependencyCycleError: the edge would close a cycle (self-edge,
            or a path already exists from `to_id` back to `from_id` within
            the bounded check depth). The error message names the cycle
            path when one was found by the bounded traversal.
    """
    if rel_type not in _TASK_DEPENDENCY_REL_TYPES:
        raise ValueError(
            f"unsupported rel_type {rel_type!r}; must be one of {_TASK_DEPENDENCY_REL_TYPES}"
        )
    pk = TASK_DEPENDENCY_TABLES.get(table)
    if pk is None:
        raise ValueError(
            f"unsupported table {table!r} for task dependency edges; "
            f"must be one of {sorted(TASK_DEPENDENCY_TABLES)}"
        )
    if from_id == to_id:
        raise TaskDependencyCycleError(
            f"{rel_type}: {from_id!r} cannot depend on itself"
        )

    cycle_path = await _task_dependency_cycle_path(db, rel_type, table, pk, from_id, to_id)
    if cycle_path:
        # cycle_path is [to_id, ..., from_id] (the existing path back to the
        # source); prepending from_id renders the full loop the new edge
        # would close without repeating from_id at both ends.
        full_path = " -> ".join([from_id] + cycle_path)
        raise TaskDependencyCycleError(
            f"{rel_type} edge {from_id} -> {to_id} would close a cycle: {full_path}"
        )

    now_iso = observed_at or datetime.now(timezone.utc).isoformat()
    gw = _gateway(db)
    qname = f"task_graph.merge_dependency_edge_{rel_type.lower()}_{table.lower()}"
    await gw.run(
        qname,
        from_id=from_id,
        to_id=to_id,
        declared_by=declared_by,
        confidence=confidence,
        now=now_iso,
        source=source,
        source_version=source_version,
        authority=authority,
    )
    return {
        "rel_type": rel_type,
        "table": table,
        "from_id": from_id,
        "to_id": to_id,
        "status": "created",
    }


async def create_task_graph(db: KuzuClient, name: str, description: str = "") -> str:
    """Backward-compatible helper for creating a TaskGraph node."""
    graph_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    gw = _gateway(db)
    await gw.run("task_graph.create_task_graph", id=graph_id, name=name, description=description, now=now)
    return graph_id


async def add_task_node(db: KuzuClient, graph_id: str, name: str, description: str = "") -> str:
    """Backward-compatible helper for adding a task node to a graph."""
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    gw = _gateway(db)
    await gw.run("task_graph.create_task_node_with_graph", tid=task_id, gid=graph_id, name=name, description=description, now=now)
    return task_id


async def add_task_dependency(db: KuzuClient, task_id: str, depends_on_task_id: str) -> bool:
    """Backward-compatible helper that adds a dependency edge with cycle prevention."""
    if await _dag_has_cycle(db, depends_on_task_id, task_id):
        return False

    gw = _gateway(db)
    await gw.run("task_graph.create_task_dependency", tid=task_id, did=depends_on_task_id)
    return True

async def _dag_has_cycle(db: KuzuClient, from_task_id: str, to_task_id: str) -> bool:
    """
    Check if adding an edge (from_task_id)-[:DEPENDS_ON]->(to_task_id) would create a cycle.
    A cycle exists if there is already a path from to_task_id to from_task_id.
    """
    try:
        gw = _gateway(db)
        r = gw.run_sync("task_graph.check_dag_cycle", to_id=to_task_id, from_id=from_task_id)
        if r:
            row = r[0]
            if isinstance(row, dict):
                count = row.get("cnt") or row.get("COUNT(p)") or next(iter(row.values()), 0)
            else:
                count = row[0]
            return count > 0
    except Exception as e:
        _logger.error("Error in _dag_has_cycle: %s", e)
    return False

async def _get_ready_tasks_query(db: KuzuClient, graph_id: str) -> List[Dict[str, Any]]:
    """
    Return all TaskNodes in a TaskGraph that are 'pending' and have no 'pending', 'active' 
    or 'failed' prerequisites (all DEPENDS_ON neighbors are 'complete' or 'skipped').
    """
    tasks = []
    try:
        gw = _gateway(db)
        rows = gw.run_sync("task_graph.get_ready_tasks", graph_id=graph_id)
        for row in rows:
            tasks.append({
                "task_id": row.get("t.task_id") if hasattr(row, "get") else row[0],
                "label": row.get("t.name") if hasattr(row, "get") else row[1],
                "description": row.get("t.description") if hasattr(row, "get") else row[2],
                "status": row.get("t.status") if hasattr(row, "get") else row[3],
                "owner": row.get("t.owner") if hasattr(row, "get") else row[4],
            })
    except Exception as e:
        _logger.error("Error in _get_ready_tasks_query: %s", e)
    return tasks

async def register_task_graph(params: dict, db: KuzuClient, config: dict) -> dict:
    """Declare a full DAG of tasks."""
    label = params.get("label", "Untitled Graph")
    session_id = params.get("session_id", "unknown")
    owner = params.get("owner", "unknown")
    tasks_input = params.get("tasks", [])
    
    graph_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    gw = _gateway(db)
    # 1. Create TaskGraph node
    await gw.run(
        "task_graph.init_task_graph",
        id=graph_id, label=label, sid=session_id, owner=owner, now=now
    )
    
    # 2. Create TaskNode nodes
    task_ids = []
    for t in tasks_input:
        tid = t["task_id"]
        task_ids.append(tid)
        await gw.run(
            "task_graph.merge_task_node_with_graph",
            tid=tid, 
            gid=graph_id, 
            label=t["label"], 
            description=t.get("description", ""), 
            owner=owner,
            now=now,
        )
        
    # 3. Create DEPENDS_ON edges with cycle detection
    cycle_errors = []
    for t in tasks_input:
        tid = t["task_id"]
        deps = t.get("depends_on", [])
        for dep_id in deps:
            if await _dag_has_cycle(db, dep_id, tid):
                cycle_errors.append(f"Cycle detected: {tid} cannot depend on {dep_id}")
                continue
                
            await gw.run(
                "task_graph.merge_task_dependency",
                tid=tid, did=dep_id
            )
            
    # 4. Get initial ready tasks
    ready = await _get_ready_tasks_query(db, graph_id)
    
    return {
        "graph_id": graph_id,
        "task_ids": task_ids,
        "ready_tasks": ready,
        "cycle_errors": cycle_errors
    }

async def get_ready_tasks(params: dict, db: KuzuClient, config: dict) -> dict:
    graph_id = params["graph_id"]
    ready = await _get_ready_tasks_query(db, graph_id)
    return {"graph_id": graph_id, "ready": ready}

async def advance_task(params: dict, db: KuzuClient, config: dict) -> dict:
    graph_id = params["graph_id"]
    task_id = params["task_id"]
    status = params["status"]
    result = params.get("result")
    
    now = datetime.now(timezone.utc).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    gw = _gateway(db)
    await gw.run(
        "task_graph.update_task_node",
        tid=task_id,
        status=status,
        now=now,
        has_result=bool(result),
        result=result or "",
    )
    
    newly_unblocked = []
    if status in ('complete', 'skipped'):
        # Find tasks that might have been unblocked
        # A task is newly unblocked if it is now 'ready' but was not before
        # For simplicity, we just return the new ready frontier
        ready = await _get_ready_tasks_query(db, graph_id)
        newly_unblocked = [r["task_id"] for r in ready]
        
    return {
        "task_id": task_id,
        "new_status": status,
        "newly_unblocked": newly_unblocked
    }

async def fail_task(params: dict, db: KuzuClient, config: dict) -> dict:
    graph_id = params["graph_id"]
    task_id = params["task_id"]
    reason = params["reason"]
    
    now = datetime.now(timezone.utc).isoformat()
    
    gw = _gateway(db)
    await gw.run("task_graph.fail_task", tid=task_id, reason=reason, now=now)
    
    # Find blocked dependents
    blocked = []
    try:
        # A dependent is blocked if it depends on this failed task (directly or indirectly)
        # and its status is still 'pending'
        rows = gw.run_sync("task_graph.get_blocked_dependents", tid=task_id)
        for row in rows:
            blocked.append(row.get("dep.task_id") if hasattr(row, "get") else row[0])
    except Exception:
        pass
        
    return {
        "task_id": task_id,
        "status": "failed",
        "blocked_dependents": blocked
    }

async def get_task_graph(params: dict, db: KuzuClient, config: dict) -> dict:
    graph_id = params["graph_id"]
    
    gw = _gateway(db)
    # Get graph metadata
    label = ""
    status = ""
    version = 1
    try:
        rows = gw.run_sync("task_graph.get_graph_metadata", gid=graph_id)
        if rows:
            row = rows[0]
            label = row.get("g.label") if hasattr(row, "get") else row[0]
            status = row.get("g.status") if hasattr(row, "get") else row[1]
            version = row.get("g.version") if hasattr(row, "get") else row[2]
    except Exception:
        pass
        
    # Get tasks
    tasks = []
    try:
        rows = gw.run_sync("task_graph.get_graph_tasks", gid=graph_id)
        for row in rows:
            tasks.append({
                "task_id": row.get("t.task_id") if hasattr(row, "get") else row[0],
                "label": row.get("t.label") if hasattr(row, "get") else row[1],
                "description": row.get("t.description") if hasattr(row, "get") else row[2],
                "status": row.get("t.status") if hasattr(row, "get") else row[3],
                "owner": row.get("t.owner") if hasattr(row, "get") else row[4],
                "result": row.get("t.result") if hasattr(row, "get") else row[5],
            })
    except Exception:
        pass
        
    # Get edges
    edges = []
    try:
        rows = gw.run_sync("task_graph.get_graph_edges", gid=graph_id)
        for row in rows:
            edges.append({
                "from": row.get("t1.task_id") if hasattr(row, "get") else row[0],
                "to": row.get("t2.task_id") if hasattr(row, "get") else row[1],
            })
    except Exception:
        pass
        
    return {
        "graph_id": graph_id,
        "label": label,
        "status": status,
        "version": version,
        "tasks": tasks,
        "edges": edges
    }
