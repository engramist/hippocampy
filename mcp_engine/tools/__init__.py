"""
mcp_engine/tools/__init__.py — compatibility shim

Canonical implementation has moved to:
    campy.brain.thalamus.tools

All public and tested names are re-exported here for backwards compatibility.
"""
# ruff: noqa: F401

# Re-export the embeddings sub-module as `emb` so that tests that monkeypatch
# `mcp_engine.tools.emb.embed` continue to work.
from mcp_engine.graph import embeddings as emb  # noqa: F401

from campy.brain.thalamus.tools import (
    # Dispatch table
    TOOL_HANDLERS,
    # Public lifecycle helpers
    init_loop_queue,
    # Tool handler functions (all public names used by tests/importers)
    notify_turn,
    reconstruct_timeline,
    current_truth,
    branch_quest,
    diff_since,
    get_knowledge_gaps,
    get_open_loops,
    get_disambiguation_queue,
    resolve_disambiguation,
    reload_domain_dictionary,
    analogical_search,
    ingest_document,
    ingest_data,
    compile_context,
    complete_quest,
    upsert_lesson,
    recall_relevant_lessons,
    recall_scene_graph_priors,
    set_quest,
    get_anomalies,
    context_status,
    register_plan,
    report_outcome,
    recall_plans,
    recall_procedures,
    get_openclaw_prompt,
    memory_decision,
    # Arc tools
    ingest_arc_artifacts,
    publish_mechanic_summary,
    recall_mechanic_priors,
    # Task graph tools
    register_task_graph,
    get_ready_tasks,
    advance_task,
    fail_task,
    get_task_graph,
    # Explore graph tool
    explore_graph,
)
