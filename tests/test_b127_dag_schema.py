import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from campy.brain.thalamus.tools.task_graph import (
    create_task_graph, add_task_node, add_task_dependency,
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
async def test_create_task_graph(db):
    graph_id = await create_task_graph(db, "Test Graph", "Testing DAG")
    assert graph_id
    assert db.execute_write.called
    args = db.execute_write.call_args[0][1]
    assert args["name"] == "Test Graph"

@pytest.mark.asyncio
async def test_add_task_node(db):
    task_id = await add_task_node(db, "g1", "Task 1", "First task")
    assert task_id
    assert db.execute_write.called
    args = db.execute_write.call_args[0][1]
    assert args["gid"] == "g1"
    assert args["name"] == "Task 1"

@pytest.mark.asyncio
async def test_cycle_detection(db):
    # Mock execute for _dag_has_cycle
    # Case 1: No cycle
    db.execute.return_value = _Result([[0]])
    has_cycle = await _dag_has_cycle(db, "t1", "t2")
    assert has_cycle is False
    
    # Case 2: Cycle detected
    db.execute.return_value = _Result([[1]])
    has_cycle = await _dag_has_cycle(db, "t1", "t2")
    assert has_cycle is True

@pytest.mark.asyncio
async def test_add_task_dependency_with_cycle_prevention(db):
    # Mock cycle detection to True
    db.execute.return_value = _Result([[1]])
    
    success = await add_task_dependency(db, "t2", "t1")
    assert success is False
    assert not any("CREATE (t)-[:DEPENDS_ON]->(dep)" in str(call) for call in db.execute_write.call_args_list)

    # Mock cycle detection to False
    db.execute.return_value = _Result([[0]])
    success = await add_task_dependency(db, "t2", "t1")
    assert success is True
    assert any("CREATE (t)-[:DEPENDS_ON]->(dep)" in str(call) for call in db.execute_write.call_args_list)

@pytest.mark.asyncio
async def test_get_ready_tasks_query(db):
    # Mock ready tasks
    tasks_data = [
        ["t1", "Ready Task", "desc", "pending", "input"]
    ]
    db.execute.return_value = _Result(tasks_data)
    
    ready = await _get_ready_tasks_query(db, "g1")
    assert len(ready) == 1
    assert ready[0]["task_id"] == "t1"
    assert "graph_id" in db.execute.call_args[0][1]
    assert db.execute.call_args[0][1]["graph_id"] == "g1"
