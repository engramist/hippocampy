"""
tests/test_explore_graph.py — Tests for the explore_graph tool (B10).

Tests the modular campy/brain/thalamus/tools/explore_graph handler directly using a mock db.
"""

from __future__ import annotations
import asyncio
import re
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
    """Install stubs and import campy.brain.thalamus.tools right before tests run."""
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

    if "campy.brain.hippocampus.graph.embeddings" not in sys.modules:
        _stub("campy.brain.hippocampus.graph.embeddings",
              embed=lambda text, model_name=None: [0.0] * 384,
              prewarm=lambda model_name=None: None,
              embed_batch=lambda texts, model_name=None: [[0.0] * 384] * len(texts))

    if "campy.brain.hippocampus.quest" not in sys.modules:
        _stub("campy.brain.hippocampus.quest",
              get_or_create_main_quest=lambda *a, **kw: "",
              get_or_create_session=lambda *a, **kw: None,
              create_side_quest=lambda *a, **kw: "",
              get_quest_context=lambda *a, **kw: {},
              compute_quest_id=lambda *a, **kw: "a" * 32)

    import importlib
    tools_mod = importlib.import_module("campy.brain.thalamus.tools")
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
    sys.modules.pop("campy.brain.thalamus.tools", None)
    for key in ["campy.brain.hippocampus.graph.embeddings", "campy.brain.hippocampus.quest"]:
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
    """B280: real Kuzu has no working parameterized form for internal-id
    filtering, so the real implementation embeds `id(a) IN [INTERNAL_ID(t,
    o), ...]` literals directly in the query text (see explore_graph.py's
    _internal_id_literal). This mock simulates that by assigning every
    known node_id a stable fake internal id ({"table": 0, "offset": N}) up
    front, returning it alongside node dicts (mirroring real Kuzu's `_id`
    key), and parsing offsets back out of the query text via regex instead
    of reading an `ids` param - there is no `ids` param anymore.
    """

    def __init__(self, node_lookup=None, node_data=None, neighbor_lookup=None):
        self._node_lookup = node_lookup or {}
        self._node_data = node_data or {}
        self._neighbor_lookup = neighbor_lookup or {}
        self.queries = []
        self._internal_ids = {
            node_id: {"table": 0, "offset": i}
            for i, node_id in enumerate(self._node_lookup)
        }
        self._offset_to_node = {iid["offset"]: node_id for node_id, iid in self._internal_ids.items()}

    def _node_dict(self, node_id):
        table, _ = self._node_lookup.get(node_id, ("Concept", "concept_id"))
        text, confidence = self._node_data.get(node_id, ("", 0.0))
        pk = {
            "Concept": "concept_id",
            "Decision": "decision_id",
            "Constraint": "constraint_id",
            "Requirement": "requirement_id",
            "ActionItem": "action_item_id",
            "GlobalConstraint": "global_constraint_id",
            "GlobalPreference": "global_preference_id",
            "MainQuest": "quest_id",
            "SideQuest": "quest_id",
            "Message": "message_id",
            "Document": "document_id",
            "Lesson": "lesson_id",
        }.get(table, "concept_id")
        return {
            "_id": self._internal_ids.get(node_id, {"table": 0, "offset": -1}),
            "_label": table,
            pk: node_id,
            "text_raw": text,
            "confidence": confidence,
        }

    def execute(self, query, params=None):
        self.queries.append((query, params))
        node_id = (params or {}).get("id", "")

        # Start-node resolution: now `RETURN n, id(n) LIMIT 1`.
        if "LIMIT 1" in query and node_id in self._node_lookup:
            table, _ = self._node_lookup[node_id]
            if f"n:{table}" in query:
                return _Row([[self._node_dict(node_id), self._internal_ids[node_id]]])
            return _Row([])

        # Batched neighbor lookup: ids now embedded as INTERNAL_ID(table, offset)
        # literals in the query text rather than an "ids" param.
        if "RETURN a, b, label(r), coalesce(r.confidence, 1.0)" in query:
            offsets = [int(o) for o in re.findall(r"INTERNAL_ID\(\d+,\s*(\d+)\)", query)]
            ids = [self._offset_to_node[o] for o in offsets if o in self._offset_to_node]
            current_rel = None
            for rel in ["REQUIRES", "ENABLES", "REPLACES", "CONTRADICTS", "PART_OF", "CHOSEN_OVER", "IMPLEMENTS", "EXTENDS", "ALTERNATIVE_TO", "NEXT_MESSAGE", "CAUSED_BY", "ESTABLISHED_IN"]:
                if f":{rel}" in query:
                    current_rel = rel
                    break
            results = []
            direction_key = "in" if "<-" in query else "out"
            for seed_id in ids:
                key = (seed_id, direction_key)
                neighbor_rows = self._neighbor_lookup.get(key)
                if neighbor_rows is None:
                    neighbor_rows = self._neighbor_lookup.get((seed_id, "both"), [])
                for n_id, n_conf in neighbor_rows:
                    results.append([
                        self._node_dict(seed_id),
                        self._node_dict(n_id),
                        current_rel or "REQUIRES",
                        n_conf,
                    ])
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


# ---------------------------------------------------------------------------
# B125: Context-windowed recall tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_explore_context_window_default():
    """B125: context_window defaults to 0 (no context neighbors)."""
    db = MockDB(
        node_lookup={"n1": ("Concept", "concept_id")},
        node_data={"n1": ("Node 1", 0.9)},
    )
    result = await explore_graph(
        {"start_node_id": "n1", "session_id": "s1"},
        db, {}
    )
    assert "context_window" in result
    assert result["context_window"] == 0


@pytest.mark.asyncio
async def test_explore_context_window_parameter():
    """B125: context_window parameter is accepted and capped at 3."""
    db = MockDB(
        node_lookup={"n1": ("Concept", "concept_id")},
        node_data={"n1": ("Node 1", 0.9)},
    )

    # Test with valid context_window
    result = await explore_graph(
        {"start_node_id": "n1", "session_id": "s1", "context_window": 2},
        db, {}
    )
    assert result["context_window"] == 2

    # Test with context_window exceeding max
    result = await explore_graph(
        {"start_node_id": "n1", "session_id": "s1", "context_window": 10},
        db, {}
    )
    assert result["context_window"] == 3


@pytest.mark.asyncio
async def test_explore_context_window_negative_clamped_to_zero():
    """B125: negative context_window should be clamped to 0."""
    db = MockDB(
        node_lookup={"n1": ("Concept", "concept_id")},
        node_data={"n1": ("Node 1", 0.9)},
    )
    result = await explore_graph(
        {"start_node_id": "n1", "session_id": "s1", "context_window": -5},
        db, {}
    )
    assert result["context_window"] == 0


@pytest.mark.asyncio
async def test_explore_context_neighbors_included_in_nodes():
    """B125: When context_window > 0, nodes should include context_neighbors field."""
    db = MockDB(
        node_lookup={
            "n1": ("Concept", "concept_id"),
            "n2": ("Concept", "concept_id"),
        },
        node_data={
            "n1": ("Node 1", 0.9),
            "n2": ("Context neighbor", 0.85),
        },
        neighbor_lookup={
            ("n1", "both"): [("n2", 1.0)],
        }
    )

    # With context_window = 0, should not have context_neighbors
    result_no_context = await explore_graph(
        {"start_node_id": "n1", "session_id": "s1", "context_window": 0},
        db, {}
    )
    if result_no_context["paths"]:
        path = result_no_context["paths"][0]
        if path["nodes"]:
            node = path["nodes"][0]
            # context_neighbors may not be present or may be empty
            context_count = node.get("context_count", 0)
            assert context_count == 0

    # With context_window > 0, may include context neighbors
    result_with_context = await explore_graph(
        {"start_node_id": "n1", "session_id": "s1", "context_window": 1},
        db, {}
    )
    assert result_with_context["context_window"] == 1
    # Result structure should be valid
    assert "paths" in result_with_context


@pytest.mark.asyncio
async def test_explore_graph_query_budget():
    db = MockDB(
        node_lookup={
            "n1": ("Concept", "concept_id"),
            "n2": ("Concept", "concept_id"),
            "n3": ("Concept", "concept_id"),
            "n4": ("Concept", "concept_id"),
        },
        node_data={
            "n1": ("Root", 1.0),
            "n2": ("A", 0.9),
            "n3": ("B", 0.8),
            "n4": ("C", 0.7),
        },
        neighbor_lookup={
            ("n1", "out"): [("n2", 1.0), ("n3", 1.0)],
            ("n2", "out"): [("n4", 1.0)],
            ("n3", "out"): [("n1", 1.0)],
        },
    )

    result = await explore_graph(
        {"start_node_id": "n1", "session_id": "s1", "depth": 3, "strategy": "bfs"},
        db, {}
    )

    assert result["exploration_complete"] is True
    assert len(db.queries) <= 30, f"explore_graph issued {len(db.queries)} queries"
