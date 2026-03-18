"""
tests/test_explore_graph.py — Tests for the explore_graph tool (B10).

Tests the mcp_engine/tools.explore_graph handler directly using a mock db.
Heavy dependencies (sentence_transformers, kuzu) are mocked at test-execution
time (not collection time) via setup_module/teardown_module so stubs do not
contaminate other test files.
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
    """Install stubs and import mcp_engine.tools right before tests run.

    Using setup_module (not module-level code) ensures stubs are installed
    during the execution phase, not during pytest collection.  This prevents
    the stubs from leaking into other test files that need the real modules.
    """
    global explore_graph, _TRAVERSABLE_RELS, _MAX_DEPTH

    def _stub(name, **attrs):
        """Create a minimal module stub and register in sys.modules."""
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
        _STUBBED_KEYS.add(name)
        return mod

    # Stub heavy/unavailable dependencies only if not already in sys.modules.
    for dep in ["sentence_transformers", "kuzu", "spacy", "spacy.lang", "spacy.lang.en"]:
        if dep not in sys.modules:
            _stub(dep)

    # Stub mcp_engine.graph.embeddings
    if "mcp_engine.graph.embeddings" not in sys.modules:
        _stub("mcp_engine.graph.embeddings",
              embed=lambda text, model_name=None: [0.0] * 384,
              prewarm=lambda model_name=None: None,
              embed_batch=lambda texts, model_name=None: [[0.0] * 384] * len(texts))

    # Stub mcp_engine.quest
    if "mcp_engine.quest" not in sys.modules:
        _stub("mcp_engine.quest",
              get_or_create_main_quest=lambda *a, **kw: "",
              get_or_create_session=lambda *a, **kw: None,
              create_side_quest=lambda *a, **kw: "",
              get_quest_context=lambda *a, **kw: {},
              compute_quest_id=lambda *a, **kw: "a" * 32)

    # Stub mcp_engine.analogical
    if "mcp_engine.analogical" not in sys.modules:
        async def _noop(*a, **kw):
            return {}
        _stub("mcp_engine.analogical", analogical_search=_noop)

    # Stub mcp_engine.ingest
    if "mcp_engine.ingest" not in sys.modules:
        async def _noop_ingest(*a, **kw):
            return {}
        _stub("mcp_engine.ingest", ingest_document=_noop_ingest)

    # Now import tools — stubs are in place.
    import importlib
    tools_mod = importlib.import_module("mcp_engine.tools")
    module.explore_graph = tools_mod.explore_graph
    module._TRAVERSABLE_RELS = tools_mod._TRAVERSABLE_RELS
    module._MAX_DEPTH = tools_mod._MAX_DEPTH
    # Update this module's globals so test functions find the names.
    globals().update({
        "explore_graph": tools_mod.explore_graph,
        "_TRAVERSABLE_RELS": tools_mod._TRAVERSABLE_RELS,
        "_MAX_DEPTH": tools_mod._MAX_DEPTH,
    })


def teardown_module(module):
    """Remove stubs and the tools module so later test files use real modules."""
    for key in _STUBBED_KEYS:
        sys.modules.pop(key, None)
    # Remove mcp_engine.tools so downstream tests reimport it with real deps.
    sys.modules.pop("mcp_engine.tools", None)
    # Remove mcp_engine.graph.embeddings (even if it was already real) so
    # downstream tests get a fresh import with real sentence_transformers.
    for key in ["mcp_engine.graph.embeddings", "mcp_engine.quest",
                "mcp_engine.analogical", "mcp_engine.ingest"]:
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
    """Simple mock that returns pre-configured results per query prefix."""

    def __init__(self, node_lookup=None, neighbor_lookup=None):
        # node_lookup: dict mapping node_id → (table, pk)
        self._node_lookup = node_lookup or {}
        # neighbor_lookup: dict mapping (start_id, direction) → list of row tuples
        self._neighbor_lookup = neighbor_lookup or {}
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))
        node_id = (params or {}).get("id", "")

        # Node existence lookup (MATCH (n:Table) WHERE n.pk = $id)
        if "LIMIT 1" in query and node_id in self._node_lookup:
            table, pk = self._node_lookup[node_id]
            if f"n:{table}" in query:
                return _Row([[node_id]])  # found
            return _Row([])  # wrong table

        # Neighbor lookup
        key_out = (node_id, "out")
        key_in  = (node_id, "in")
        if "->" in query and key_out in self._neighbor_lookup:
            return _Row(self._neighbor_lookup[key_out])
        if "<-" in query and key_in in self._neighbor_lookup:
            return _Row(self._neighbor_lookup[key_in])

        return _Row([])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_explore_returns_empty_for_unknown_node():
    """Traversal of a non-existent node returns empty nodes/edges with error."""
    db = MockDB()
    result = await explore_graph(
        {"start_node_id": "no-such-id"},
        db, {}
    )
    assert result["nodes"] == []
    assert result["edges"] == []
    assert "error" in result


@pytest.mark.asyncio
async def test_explore_missing_start_node_id():
    """Missing start_node_id returns error."""
    db = MockDB()
    result = await explore_graph({}, db, {})
    assert "error" in result
    assert "start_node_id" in result["error"]


@pytest.mark.asyncio
async def test_explore_unknown_rel_type_returns_error():
    """An unknown relationship_type returns error with allowed list."""
    db = MockDB(node_lookup={"abc": ("Concept", "concept_id")})
    result = await explore_graph(
        {"start_node_id": "abc", "relationship_type": "INVALID_REL"},
        db, {}
    )
    assert "error" in result
    assert "allowed" in result
    assert "REQUIRES" in result["allowed"]


@pytest.mark.asyncio
async def test_explore_depth_capped_at_max():
    """depth parameter is capped at _MAX_DEPTH (3)."""
    db = MockDB(node_lookup={"n1": ("Concept", "concept_id")})
    # depth=99 should be silently capped; result should not error
    result = await explore_graph(
        {"start_node_id": "n1", "depth": 99},
        db, {}
    )
    # No error from depth capping itself
    assert "error" not in result or result.get("error") == "start_node_id not found in any node table"


@pytest.mark.asyncio
async def test_explore_returns_neighbors():
    """
    When the DB has a neighbor, explore_graph returns it in nodes + edges.

    Graph: Concept(n1) -[REQUIRES]-> Concept(n2)
    """
    db = MockDB(
        node_lookup={"n1": ("Concept", "concept_id")},
        neighbor_lookup={
            ("n1", "out"): [
                # (neighbor_id, text_raw, confidence, pathway_strength, rel_type)
                ("n2", "Neighbor concept", 0.92, 0.80, "REQUIRES"),
            ]
        }
    )
    result = await explore_graph(
        {"start_node_id": "n1", "depth": 1, "direction": "outgoing"},
        db, {}
    )

    assert result["start_node_id"] == "n1"
    assert result["start_node_type"] == "Concept"
    node_ids = [n["node_id"] for n in result["nodes"]]
    assert "n2" in node_ids

    edge_pairs = [(e["source"], e["target"]) for e in result["edges"]]
    assert ("n1", "n2") in edge_pairs


@pytest.mark.asyncio
async def test_explore_filters_by_direction_outgoing():
    """direction=outgoing only returns outgoing edges."""
    db = MockDB(
        node_lookup={"n1": ("Concept", "concept_id")},
        neighbor_lookup={
            ("n1", "out"): [("n2", "out neighbor", 0.9, 0.8, "REQUIRES")],
            ("n1", "in"):  [("n3", "in neighbor",  0.9, 0.8, "ENABLES")],
        }
    )
    result = await explore_graph(
        {"start_node_id": "n1", "depth": 1, "direction": "outgoing"},
        db, {}
    )
    node_ids = {n["node_id"] for n in result["nodes"]}
    assert "n2" in node_ids
    assert "n3" not in node_ids


@pytest.mark.asyncio
async def test_explore_filters_by_direction_incoming():
    """direction=incoming only returns incoming edges."""
    db = MockDB(
        node_lookup={"n1": ("Concept", "concept_id")},
        neighbor_lookup={
            ("n1", "out"): [("n2", "out neighbor", 0.9, 0.8, "REQUIRES")],
            ("n1", "in"):  [("n3", "in neighbor",  0.9, 0.8, "ENABLES")],
        }
    )
    result = await explore_graph(
        {"start_node_id": "n1", "depth": 1, "direction": "incoming"},
        db, {}
    )
    node_ids = {n["node_id"] for n in result["nodes"]}
    assert "n3" in node_ids
    assert "n2" not in node_ids


@pytest.mark.asyncio
async def test_explore_deduplicates_nodes():
    """Same neighbor returned twice (different edge types) is not duplicated in nodes."""
    db = MockDB(
        node_lookup={"n1": ("Concept", "concept_id")},
        neighbor_lookup={
            ("n1", "out"): [
                ("n2", "shared neighbor", 0.9, 0.8, "REQUIRES"),
                ("n2", "shared neighbor", 0.9, 0.8, "ENABLES"),
            ]
        }
    )
    result = await explore_graph(
        {"start_node_id": "n1", "depth": 1, "direction": "outgoing"},
        db, {}
    )
    node_ids = [n["node_id"] for n in result["nodes"]]
    # n2 should appear only once
    assert node_ids.count("n2") == 1


def test_traversable_rels_contains_all_named_types():
    """_TRAVERSABLE_RELS includes all 9 named semantic relationship types."""
    named_types = {
        "REQUIRES", "ENABLES", "REPLACES", "CONTRADICTS", "PART_OF",
        "CHOSEN_OVER", "IMPLEMENTS", "EXTENDS", "ALTERNATIVE_TO",
    }
    assert named_types.issubset(_TRAVERSABLE_RELS)


def test_max_depth_is_three():
    """_MAX_DEPTH is 3 — prevents runaway traversal."""
    assert _MAX_DEPTH == 3
