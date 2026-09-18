import os
import shutil
import pytest
import uuid
from campy.brain.hippocampus.graph.oxigraph_client import OxigraphClient
from campy.brain.hippocampus.schema import init_schema
from campy.brain.thalamus.tools.task_graph import register_task_graph

@pytest.mark.asyncio
async def test_b219_register_task_graph_parser_fix():
    """
    B219 Regression Test:
    Ensures register_task_graph no longer fails with a Kuzu parser exception
    due to $desc reserved word usage.
    """
    db_path = "./test_b219_regression.db"
    if os.path.exists(db_path):
        if os.path.isdir(db_path):
            shutil.rmtree(db_path)
        else:
            os.remove(db_path)

    # B427: migrated off KuzuClient. register_task_graph is fully
    # GraphGateway-routed, and OxigraphClient needs no CREATE TABLE step
    # at all (NODE_COLUMNS/REL_COLUMNS come from schema.py globally) --
    # the hand-rolled TaskGraph/TaskNode DDL this test used to declare
    # (kept in sync with schema.py by hand) is simply unnecessary now.
    db = OxigraphClient(db_path)

    try:
        params = {
            "label": "Regression Graph",
            "session_id": "s1",
            "owner": "tester",
            "tasks": [
                {
                    "task_id": "t1",
                    "label": "Task 1",
                    "description": "This used to fail because of $desc",
                    "depends_on": []
                },
                {
                    "task_id": "t2",
                    "label": "Task 2",
                    "description": "Dependent task",
                    "depends_on": ["t1"]
                }
            ]
        }
        
        # This is what used to fail
        resp = await register_task_graph(params, db, {})
        
        assert resp["graph_id"]
        assert len(resp["task_ids"]) == 2
        assert "t1" in resp["task_ids"]
        assert "t2" in resp["task_ids"]
        assert len(resp["ready_tasks"]) == 1
        assert resp["ready_tasks"][0]["task_id"] == "t1"
        assert len(resp["cycle_errors"]) == 0

    finally:
        db.close()
        if os.path.exists(db_path):
            if os.path.isdir(db_path):
                shutil.rmtree(db_path)
            else:
                os.remove(db_path)
