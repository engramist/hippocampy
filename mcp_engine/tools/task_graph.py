"""
mcp_engine/tools/task_graph.py — compatibility shim

Canonical implementation has moved to:
    campy.brain.thalamus.tools.task_graph
"""
# ruff: noqa: F401

from campy.brain.thalamus.tools.task_graph import (
    create_task_graph,
    add_task_node,
    add_task_dependency,
    _dag_has_cycle,
    _get_ready_tasks_query,
    register_task_graph,
    get_ready_tasks,
    advance_task,
    fail_task,
    get_task_graph,
)
