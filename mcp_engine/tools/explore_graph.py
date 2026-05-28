"""
mcp_engine/tools/explore_graph.py — compatibility shim

Canonical implementation has moved to:
    campy.brain.thalamus.tools.explore_graph
"""
# ruff: noqa: F401

from campy.brain.thalamus.tools.explore_graph import (
    _TRAVERSABLE_RELS,
    _NODE_TABLES,
    _MAX_DEPTH,
    explore_graph,
    _get_pk_for_table,
    _get_node_data,
    _get_neighbors,
    _add_temporal_context,
    _bfs_traversal,
    _dfs_traversal,
)
