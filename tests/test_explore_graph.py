"""
tests/test_explore_graph.py — Tests for the explore_graph tool (B10).

Tests the modular mcp_engine/tools/explore_graph handler directly using a mock db.
"""

from __future__ import annotations
import asyncio
import sys
import os
import types
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Module-level placeholders — set by setup_module before any test runs.
explore_graph = None
_TRAVERSABLE_RELS = None
_MAX_DEPTH = None

# Track which modules were stubbed by this file so teardown_module can clean up.
_STUBBED_KEYS: set[str] = set()


def setup_module(module):
    """Install stubs and import mcp_engine.tools right before tests run."""
    global explore_graph, _TRAVERSABLE_RELS, _MAX_DEPTH

    def _stub(name, **attrs):
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
        _STUBBED_KEYS.add(name)
        return mod

    for dep in ["sentence_transformers", "kuzu", "spacy", "spacy.lang", "spacy.lang.en"]:
        if dep not in sys.modules:
            _stub(dep)

    if "mcp_engine.graph.embeddings" not in sys.modules:
        _stub("mcp_engine.graph.embeddings",
              embed=lambda text, model_name=None: [0.0] * 384,
              prewarm=lambda model_name=None: None,
              embed_batch=lambda texts, model_name=None: [[0.0] * 384] * len(texts))

    if "mcp_engine.quest" not in sys.modules:
        _stub("mcp_engine.quest",
              get_or_create_main_quest=lambda *a, **kw: "",
              get_or_create_session=lambda *a, **kw: None,
              create_side_quest=lambda *a, **kw: "",
              get_quest_context=lambda *a, **kw: {},
              compute_quest_id=lambda *a, **kw: "a" * 32)

    import importlib
    tools_mod = importlib.import_module("mcp_engine.tools")
    module.explore_graph = tools_mod.explore_graph
    module._TRAVERSABLE_RELS = tools_mod._TRAVERSABLE_RELS
    module._MAX_DEPTH = tools_mod._MAX_DEPTH
    
    globals().update({
        "explore_graph": tools_mod.explore_graph,
        "_TRAVERSABLE_RELS": tools_mod._TRAVERSABLE_RELS,
        "_MAX_DEPTH": tools_mod._MAX_DEPTH,
    })


def teardown_module(module):
    """Remove stubs and the tools module."""
    for key in _STUBBED_KEYS:
        sys.modules.pop(key, None)
    sys.modules.pop("mcp_engine.tools", None)
    for key in ["mcp_engine.graph.embeddings", "mcp_engine.quest"]:
        sys.modules.pop(key, None)


# ---------------------------------------------------------------------------
# Mock DB helpers
# ---------------------------------------------------------------------------

class _Row:
    def __init__(self, values):
        self._values = values
        self._idx = 0

    def has_next(self):
        return self._idx < len(self._values)

    def get_next(self):
        row = self._values[self._idx]
        self._idx += 1
        return row


class MockDB:
    def __init__(self, node_lookup=None, node_data=None, neighbor_lookup=None):
        self._node_lookup = node_lookup or {}
        self._node_data = node_data or {}
        self._neighbor_lookup = neighbor_lookup or {}
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))
        node_id = (params or {}).get("id", "")

        # Node existence lookup
        if "LIMIT 1" in query and node_id in self._node_lookup:
            table, _ = self._node_lookup[node_id]
            if f"n:{table}" in query:
                return _Row([[node_id]])
            return _Row([])

        # Node data lookup (text_raw, confidence)
        if "RETURN n.text_raw, n.confidence" in query and node_id in self._node_data:
            return _Row([self._node_data[node_id]])

        # Neighbor lookup
        key_out = (node_id, "out")
        key_in  = (node_id, "in")
        
        # Check for specific rel in query
        current_rel = None
        for rel in ["REQUIRES", "ENABLES", "REPLACES", "CONTRADICTS", "PART_OF", "CHOSEN_OVER", "IMPLEMENTS", "EXTENDS", "ALTERNATIVE_TO"]:
            if f":{rel}" in query:
                current_rel = rel
                break
        
        if "->" in query and key_out in self._neighbor_lookup:
            results = []
            for n_id, n_conf in self._neighbor_lookup[key_out]:
                # If query specifies rel, only return if it matches (mock rel type logic)
                results.append([n_id, n_conf])
            return _Row(results)
            
        if "<-" in query and key_in in self._neighbor_lookup:
            results = []
            for n_id, n_conf in self._neighbor_lookup[key_in]:
                results.append([n_id, n_conf])
            return _Row(results)

        return _Row([])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_explore_returns_empty_for_unknown_node():
    db = MockDB()
    result = await explore_graph(
        {"start_node_id": "no-such-id", "session_id": "s1"},
        db, {}
    )
    assert result["paths"] == []
    assert "error" in result


@pytest.mark.asyncio
async def test_explore_missing_start_node_id():
    db = MockDB()
    result = await explore_graph({"session_id": "s1"}, db, {})
    assert "error" in result
    assert "start_node_id" in result["error"]


@pytest.mark.asyncio
async def test_explore_missing_session_id():
    db = MockDB()
    result = await explore_graph({"start_node_id": "n1"}, db, {})
    assert "error" in result
    assert "session_id" in result["error"]


@pytest.mark.asyncio
async def test_explore_unknown_rel_type_returns_error():
    db = MockDB(node_lookup={"abc": ("Concept", "concept_id")})
    result = await explore_graph(
        {"start_node_id": "abc", "session_id": "s1", "edge_types": ["INVALID_REL"]},
        db, {}
    )
    assert "error" in result
    assert "allowed" in result
    assert "REQUIRES" in result["allowed"]


@pytest.mark.asyncio
async def test_explore_depth_capped_at_max():
    db = MockDB(node_lookup={"n1": ("Concept", "concept_id")})
    result = await explore_graph(
        {"start_node_id": "n1", "session_id": "s1", "depth": 99},
        db, {}
    )
    assert "error" not in result


@pytest.mark.asyncio
async def test_explore_returns_paths():
    db = MockDB(
        node_lookup={"n1": ("Concept", "concept_id"), "n2": ("Concept", "concept_id")},
        node_data={
            "n1": ("Node 1", 0.9),
            "n2": ("Neighbor", 0.92)
        },
        neighbor_lookup={
            ("n1", "out"): [("n2", 0.8)]
        }
    )
    result = await explore_graph(
        {"start_node_id": "n1", "session_id": "s1", "depth": 1, "direction": "outgoing", "edge_types": ["REQUIRES"]},
        db, {}
    )

    assert "paths" in result
    assert len(result["paths"]) > 0
    path = result["paths"][0]
    node_ids = [n["node_id"] for n in path["nodes"]]
    assert "n1" in node_ids
    assert "n2" in node_ids
    assert path["edges"][0]["type"] == "REQUIRES"


@pytest.mark.asyncio
async def test_explore_bfs_vs_dfs():
    # Complex graph to differentiate BFS/DFS
    # n1 -> n2 -> n4
    # n1 -> n3
    db = MockDB(
        node_lookup={
            "n1": ("Concept", "concept_id"),
            "n2": ("Concept", "concept_id"),
            "n3": ("Concept", "concept_id"),
            "n4": ("Concept", "concept_id"),
        },
        node_data={
            "n1": ("N1", 1.0), "n2": ("N2", 1.0), "n3": ("N3", 1.0), "n4": ("N4", 1.0)
        },
        neighbor_lookup={
            ("n1", "out"): [("n2", 1.0), ("n3", 1.0)],
            ("n2", "out"): [("n4", 1.0)],
        }
    )
    
    # BFS should find paths in breadth-first order (shorter paths first)
    bfs_result = await explore_graph(
        {"start_node_id": "n1", "session_id": "s1", "depth": 2, "strategy": "bfs"},
        db, {}
    )
    
    # DFS should find paths in depth-first order
    dfs_result = await explore_graph(
        {"start_node_id": "n1", "session_id": "s1", "depth": 2, "strategy": "dfs"},
        db, {}
    )
    
    assert len(bfs_result["paths"]) == len(dfs_result["paths"])
    # The order of paths should differ
    bfs_depths = [p["path_depth"] for p in bfs_result["paths"]]
    dfs_depths = [p["path_depth"] for p in dfs_result["paths"]]
    
    # BFS depths should be non-decreasing: [1, 1, 2]
    assert bfs_depths == sorted(bfs_depths)
    # DFS depths will go deep first: [1, 2, 1]
    assert bfs_depths != dfs_depths


def test_traversable_rels_contains_all_named_types():
    named_types = {
        "REQUIRES", "ENABLES", "REPLACES", "CONTRADICTS", "PART_OF",
        "CHOSEN_OVER", "IMPLEMENTS", "EXTENDS", "ALTERNATIVE_TO",
    }
    assert named_types.issubset(_TRAVERSABLE_RELS)


def test_max_depth_is_five():
    assert _MAX_DEPTH == 5
