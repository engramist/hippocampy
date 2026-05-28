import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from campy.brain.thalamus.tools.task_graph import (
    register_task_graph, get_ready_tasks, advance_task, fail_task, get_task_graph,
    _dag_has_cycle, _get_ready_tasks_query
)
from campy.brain.hippocampus.graph.kuzu_client import KuzuClient

class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []
        self._idx = 0
    def has_next(self): return self._idx < len(self._rows)
    def get_next(self): 
        row = self._rows[self._idx]
        self._idx += 1
        return row

@pytest.fixture
def db():
    mock = MagicMock(spec=KuzuClient)
    mock.execute_write = AsyncMock()
    return mock

@pytest.mark.asyncio
async def test_register_task_graph(db):
    params = {
        "label": "Test Graph",
        "session_id": "s1",
        "owner": "test",
        "tasks": [
            {"task_id": "t1", "label": "Task 1", "depends_on": []},
            {"task_id": "t2", "label": "Task 2", "depends_on": ["t1"]}
        ]
    }
    
    # Mock for cycle detection (no cycle)
    db.execute.return_value = _Result([[0]])
    
    resp = await register_task_graph(params, db, {})
    assert "graph_id" in resp
    assert len(resp["task_ids"]) == 2
    # execute_write called for Graph + 2 Nodes + 1 Dependency
    assert db.execute_write.call_count >= 4

@pytest.mark.asyncio
async def test_register_task_graph_with_cycle(db):
    params = {
        "label": "Cycle Graph",
        "session_id": "s1",
        "owner": "test",
        "tasks": [
            {"task_id": "t1", "label": "Task 1", "depends_on": ["t2"]},
            {"task_id": "t2", "label": "Task 2", "depends_on": ["t1"]}
        ]
    }
    
    # Mock for cycle detection: first call no cycle, second call cycle
    # register_task_graph calls _dag_has_cycle for each dependency
    db.execute.side_effect = [
        _Result([[0]]), # first edge t1 -> t2 ok
        _Result([[1]]), # second edge t2 -> t1 cycle!
        _Result([])     # final ready query
    ]
    
    resp = await register_task_graph(params, db, {})
    assert len(resp["cycle_errors"]) == 1
    assert "Cycle detected" in resp["cycle_errors"][0]

@pytest.mark.asyncio
async def test_advance_task(db):
    params = {
        "graph_id": "g1",
        "task_id": "t1",
        "status": "complete",
        "result": "it worked"
    }
    # Mock ready query after advance
    db.execute.return_value = _Result([["t2", "Task 2", "desc", "pending", "owner"]])
    
    resp = await advance_task(params, db, {})
    assert resp["task_id"] == "t1"
    assert resp["new_status"] == "complete"
    assert "t2" in resp["newly_unblocked"]
    assert db.execute_write.called

@pytest.mark.asyncio
async def test_fail_task(db):
    params = {
        "graph_id": "g1",
        "task_id": "t1",
        "reason": "failed hard"
    }
    # Mock blocked dependents query
    db.execute.return_value = _Result([["t2"], ["t3"]])
    
    resp = await fail_task(params, db, {})
    assert resp["task_id"] == "t1"
    assert resp["status"] == "failed"
    assert "t2" in resp["blocked_dependents"]
    assert "t3" in resp["blocked_dependents"]

@pytest.mark.asyncio
async def test_get_task_graph(db):
    params = {"graph_id": "g1"}
    # Mock 3 queries: graph meta, tasks, edges
    db.execute.side_effect = [
        _Result([["My Graph", "active", 1]]), # Meta
        _Result([["t1", "L1", "D1", "complete", "O1", "R1"], ["t2", "L2", "D2", "pending", "O1", None]]), # Tasks
        _Result([["t2", "t1"]]) # Edges (t2 depends on t1)
    ]
    
    resp = await get_task_graph(params, db, {})
    assert resp["label"] == "My Graph"
    assert len(resp["tasks"]) == 2
    assert len(resp["edges"]) == 1
    assert resp["edges"][0]["from"] == "t2"
