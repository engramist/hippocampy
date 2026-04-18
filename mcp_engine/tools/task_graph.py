"""
mcp_engine/tools/task_graph.py — DAG Task Graph Schema Helpers (B127/B128)

Provides helper logic for managing TaskGraph and TaskNode DAGs,
including cycle detection and ready-frontier queries.
"""

from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_engine.graph.kuzu_client import KuzuClient

_logger = logging.getLogger(__name__)


async def create_task_graph(db: KuzuClient, name: str, description: str = "") -> str:
    """Backward-compatible helper for creating a TaskGraph node."""
    graph_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.execute_write(
        """
        CREATE (g:TaskGraph {
            graph_id: $id,
            name: $name,
            description: $description,
            label: $name,
            status: 'active',
            version: 1,
            created_at: timestamp($now)
        })
        """,
        {"id": graph_id, "name": name, "description": description, "now": now},
    )
    return graph_id


async def add_task_node(db: KuzuClient, graph_id: str, name: str, description: str = "") -> str:
    """Backward-compatible helper for adding a task node to a graph."""
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    await db.execute_write(
        """
        CREATE (t:TaskNode {
            task_id: $tid,
            graph_id: $gid,
            name: $name,
            label: $name,
            description: $description,
            status: 'pending',
            created_at: timestamp($now)
        })
        WITH t
        MATCH (g:TaskGraph {graph_id: $gid})
        CREATE (t)-[:TASK_OF]->(g)
        """,
        {
            "tid": task_id,
            "gid": graph_id,
            "name": name,
            "description": description,
            "now": now,
        },
    )
    return task_id


async def add_task_dependency(db: KuzuClient, task_id: str, depends_on_task_id: str) -> bool:
    """Backward-compatible helper that adds a dependency edge with cycle prevention."""
    if await _dag_has_cycle(db, depends_on_task_id, task_id):
        return False

    await db.execute_write(
        """
        MATCH (t:TaskNode {task_id: $tid}), (dep:TaskNode {task_id: $did})
        CREATE (t)-[:DEPENDS_ON]->(dep)
        """,
        {"tid": task_id, "did": depends_on_task_id},
    )
    return True

async def _dag_has_cycle(db: KuzuClient, from_task_id: str, to_task_id: str) -> bool:
    """
    Check if adding an edge (from_task_id)-[:DEPENDS_ON]->(to_task_id) would create a cycle.
    A cycle exists if there is already a path from to_task_id to from_task_id.
    """
    try:
        q = """
        MATCH (a:TaskNode {task_id: $to_id}), (b:TaskNode {task_id: $from_id})
        MATCH p = (a)-[:DEPENDS_ON*]->(b)
        RETURN count(p)
        """
        r = db.execute(q, {"to_id": to_task_id, "from_id": from_task_id})
        if r.has_next():
            count = r.get_next()[0]
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
        q = """
        MATCH (t:TaskNode)-[:TASK_OF]->(g:TaskGraph {graph_id: $graph_id})
        WHERE t.status = 'pending'
        AND NOT EXISTS {
            MATCH (t)-[:DEPENDS_ON]->(dep:TaskNode)
            WHERE NOT (dep.status IN ['complete', 'skipped'])
        }
        RETURN t.task_id, t.name, t.description, t.status, t.owner
        """
        r = db.execute(q, {"graph_id": graph_id})
        while r.has_next():
            row = r.get_next()
            tasks.append({
                "task_id": row[0],
                "label": row[1],
                "description": row[2],
                "status": row[3],
                "owner": row[4]
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
    
    # 1. Create TaskGraph node
    await db.execute_write(
        """
        CREATE (g:TaskGraph {
            graph_id: $id,
            name: $label,
            label: $label,
            version: 1,
            session_id: $sid,
            owner: $owner,
            status: 'active',
            created_at: timestamp($now)
        })
        """,
        {"id": graph_id, "label": label, "sid": session_id, "owner": owner, "now": now}
    )
    
    # 2. Create TaskNode nodes
    task_ids = []
    for t in tasks_input:
        tid = t["task_id"]
        task_ids.append(tid)
        await db.execute_write(
            """
            CREATE (t:TaskNode {
                task_id: $tid,
                graph_id: $gid,
                name: $label,
                label: $label,
                description: $description,
                status: 'pending',
                owner: $owner,
                created_at: timestamp($now)
            })
            WITH t
            MATCH (g:TaskGraph {graph_id: $gid})
            CREATE (t)-[:TASK_OF]->(g)
            """,
            {
                "tid": tid, 
                "gid": graph_id, 
                "label": t["label"], 
                "description": t.get("description", ""), 
                "owner": owner,
                "now": now
            }
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
                
            await db.execute_write(
                """
                MATCH (t:TaskNode {task_id: $tid}), (dep:TaskNode {task_id: $did})
                CREATE (t)-[:DEPENDS_ON]->(dep)
                """,
                {"tid": tid, "did": dep_id}
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
    
    update_fields = "SET t.status = $status"
    if status == 'active':
        update_fields += ", t.started_at = timestamp($now)"
    elif status in ('complete', 'skipped'):
        update_fields += ", t.completed_at = timestamp($now)"
        
    if result:
        update_fields += ", t.result = $result"
        
    await db.execute_write(
        f"MATCH (t:TaskNode {{task_id: $tid}}) {update_fields}",
        {"tid": task_id, "status": status, "now": now, "result": result}
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
    
    await db.execute_write(
        """
        MATCH (t:TaskNode {task_id: $tid})
        SET t.status = 'failed', t.result = $reason, t.completed_at = timestamp($now)
        """,
        {"tid": task_id, "reason": reason, "now": now}
    )
    
    # Find blocked dependents
    blocked = []
    try:
        # A dependent is blocked if it depends on this failed task (directly or indirectly)
        # and its status is still 'pending'
        q = """
        MATCH (t:TaskNode {task_id: $tid})<-[:DEPENDS_ON*]-(dep:TaskNode)
        WHERE dep.status = 'pending'
        RETURN DISTINCT dep.task_id
        """
        r = db.execute(q, {"tid": task_id})
        while r.has_next():
            blocked.append(r.get_next()[0])
    except Exception:
        pass
        
    return {
        "task_id": task_id,
        "status": "failed",
        "blocked_dependents": blocked
    }

async def get_task_graph(params: dict, db: KuzuClient, config: dict) -> dict:
    graph_id = params["graph_id"]
    
    # Get graph metadata
    label = ""
    status = ""
    version = 1
    try:
        r = db.execute(
            "MATCH (g:TaskGraph {graph_id: $gid}) RETURN g.label, g.status, g.version",
            {"gid": graph_id}
        )
        if r.has_next():
            row = r.get_next()
            label, status, version = row[0], row[1], row[2]
    except Exception:
        pass
        
    # Get tasks
    tasks = []
    try:
        r = db.execute(
            """
            MATCH (t:TaskNode)-[:TASK_OF]->(g:TaskGraph {graph_id: $gid})
            RETURN t.task_id, t.label, t.description, t.status, t.owner, t.result
            """,
            {"gid": graph_id}
        )
        while r.has_next():
            row = r.get_next()
            tasks.append({
                "task_id": row[0],
                "label": row[1],
                "description": row[2],
                "status": row[3],
                "owner": row[4],
                "result": row[5]
            })
    except Exception:
        pass
        
    # Get edges
    edges = []
    try:
        r = db.execute(
            """
            MATCH (t1:TaskNode)-[:DEPENDS_ON]->(t2:TaskNode)
            MATCH (t1)-[:TASK_OF]->(g:TaskGraph {graph_id: $gid})
            RETURN t1.task_id, t2.task_id
            """,
            {"gid": graph_id}
        )
        while r.has_next():
            row = r.get_next()
            edges.append({"from": row[0], "to": row[1]})
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
