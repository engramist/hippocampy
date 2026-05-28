import os
import shutil
import pytest
import uuid
from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
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
            
    db = KuzuClient(db_path)
    
    # Minimal schema init to avoid slow embeddings if possible
    # but task_graph depends on TaskGraph and TaskNode tables.
    # We use a mock-like approach for schema if init_schema is too slow, 
    # but let's try real init first.
    
    try:
        # Actually, let's just create the tables we need to keep it fast
        # but matching campy/brain/hippocampus/schema.py
        db.execute("CREATE NODE TABLE TaskGraph (graph_id STRING, name STRING, label STRING, description STRING, session_id STRING, owner STRING, version INT64, status STRING, created_at TIMESTAMP, completed_at TIMESTAMP, PRIMARY KEY (graph_id))")
        db.execute("CREATE NODE TABLE TaskNode (task_id STRING, graph_id STRING, name STRING, label STRING, description STRING, owner STRING, status STRING, input_data STRING, output_data STRING, error_msg STRING, result STRING, created_at TIMESTAMP, started_at TIMESTAMP, completed_at TIMESTAMP, PRIMARY KEY (task_id))")
        db.execute("CREATE REL TABLE TASK_OF (FROM TaskNode TO TaskGraph)")
        db.execute("CREATE REL TABLE DEPENDS_ON (FROM TaskNode TO TaskNode)")

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
