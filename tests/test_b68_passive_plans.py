import pytest
import asyncio
import sys
import os
import types
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Module-level placeholders — set by setup_module before any test runs.
notify_turn = None
_infer_retrospective_plans = None

# Track which modules were stubbed by this file so teardown_module can clean up.
_STUBBED_KEYS: set[str] = set()


def _stub(name, **attrs):
    """Create a stub module with optional attributes."""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    _STUBBED_KEYS.add(name)
    return mod


def setup_module(module):
    """Install stubs and import mcp_engine.tools right before tests run."""
    global notify_turn, _infer_retrospective_plans

    # Stub external dependencies that kuzu needs
    for dep in ["sentence_transformers", "kuzu", "spacy", "spacy.lang", "spacy.lang.en"]:
        if dep not in sys.modules:
            _stub(dep)

    # Stub mcp_engine.graph.embeddings
    if "mcp_engine.graph.embeddings" not in sys.modules:
        _stub("mcp_engine.graph.embeddings",
              embed=lambda text, model_name=None: [0.01] * 384,
              prewarm=lambda model_name=None: None,
              embed_batch=lambda texts, model_name=None: [[0.01] * 384] * len(texts))

    # Stub mcp_engine.quest
    if "mcp_engine.quest" not in sys.modules:
        _stub("mcp_engine.quest",
              get_or_create_main_quest=lambda *a, **kw: "",
              get_or_create_session=lambda *a, **kw: None,
              create_side_quest=lambda *a, **kw: "",
              get_quest_context=lambda *a, **kw: {},
              compute_quest_id=lambda *a, **kw: "a" * 32)

    # Stub mcp_engine.warm_frontier
    if "mcp_engine.warm_frontier" not in sys.modules:
        _stub("mcp_engine.warm_frontier",
              compute_warm_frontier=lambda *a, **kw: None)

    # Stub mcp_engine.working_memory
    if "mcp_engine.working_memory" not in sys.modules:
        _stub("mcp_engine.working_memory",
              update_token_estimate=lambda *a, **kw: None,
              estimate_tokens=lambda text: len(text.split()))

    # Stub mcp_engine.hippocampus
    async def _stub_route_session(*a, **kw):
        return type('obj', (object,), {'quest_id': ''})()

    async def _stub_update_routing(*a, **kw):
        return None

    if "mcp_engine.hippocampus" not in sys.modules:
        _stub("mcp_engine.hippocampus",
              route_session=_stub_route_session,
              update_routing_strength=_stub_update_routing,
              get_active_quests_with_embeddings=lambda *a: [])

    import importlib
    tools_mod = importlib.import_module("mcp_engine.tools")
    sweep_mod = importlib.import_module("mcp_engine.sweep")

    module.notify_turn = tools_mod.notify_turn
    module._infer_retrospective_plans = sweep_mod._infer_retrospective_plans

    globals().update({
        "notify_turn": tools_mod.notify_turn,
        "_infer_retrospective_plans": sweep_mod._infer_retrospective_plans,
    })


def teardown_module(module):
    """Remove stubs and the tools module."""
    for key in _STUBBED_KEYS:
        sys.modules.pop(key, None)
    sys.modules.pop("mcp_engine.tools", None)
    sys.modules.pop("mcp_engine.sweep", None)
    for key in ["mcp_engine.graph.embeddings", "mcp_engine.quest",
                "mcp_engine.warm_frontier", "mcp_engine.working_memory",
                "mcp_engine.hippocampus"]:
        sys.modules.pop(key, None)


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
    mock = MagicMock()
    mock.execute = MagicMock()
    mock.execute_write = AsyncMock()
    mock.vector_search = MagicMock(return_value=[])
    return mock

@pytest.mark.asyncio
async def test_layer_b_passive_plan_detection(db):
    """
    Test that notify_turn detects a plan from natural language and creates graph nodes.
    """
    session_id = "test_session_b68"
    content = """Here is my plan to fix the bug:
1. Identify the root cause in the orchestrator.
2. Add a failing test case to test_loop.py.
3. Patch the logic and verify the fix.
"""
    
    # Mock dependencies for notify_turn
    db.execute.return_value = _Result([]) # No existing quests/sessions/plans
    
    config = {
        "embeddings": {"model": "mock-model"},
        "ingestion": {"max_ingest_chars": 4000}
    }
    
    params = {
        "role": "user",
        "content": content,
        "session_id": session_id
    }
    
    await notify_turn(params, db, config)
    
    # Verify Plan creation
    write_calls = db.execute_write.call_args_list
    plan_created = any("CREATE (p:Plan" in str(call) for call in write_calls)
    assert plan_created
    
    # Verify PlanStep creation (should be 3 steps)
    step_count = sum(1 for call in write_calls if "CREATE (ps:PlanStep" in str(call))
    assert step_count == 3
    
    # Verify NEXT_STEP chain
    next_step_created = any("MERGE (x)-[:NEXT_STEP]->(y)" in str(call) for call in write_calls)
    assert next_step_created

@pytest.mark.asyncio
async def test_layer_c_retrospective_plan_inference(db):
    """
    Test that background sweep can infer a plan from sequential ActionItems.
    """
    session_id = "session_retro"
    # Mock ActionItems in a session
    items = [
        ("s1", "aid1", "First step description", "2026-04-01T10:00:00"),
        ("s1", "aid2", "Second step description", "2026-04-01T10:01:00"),
        ("s1", "aid3", "Third step description", "2026-04-01T10:02:00"),
    ]
    
    # Mock DB query for ActionItems
    db.execute.side_effect = [
        _Result(items), # Items query
        _Result([])     # Dedup vector search query
    ]
    db.vector_search.return_value = []
    
    config = {
        "embeddings": {"model": "mock-model"},
        "plan_dedup_threshold": 0.90
    }
    
    inferred, errors = await _infer_retrospective_plans(db, config)
    
    assert inferred == 1
    assert errors == 0
    
    # Verify Plan node created with source="retrospective"
    write_calls = db.execute_write.call_args_list
    retro_plan = any("source: 'retrospective'" in str(call) for call in write_calls)
    assert retro_plan
    
    # Verify 3 PlanSteps created
    step_count = sum(1 for call in write_calls if "CREATE (ps:PlanStep" in str(call))
    assert step_count == 3

@pytest.mark.asyncio
async def test_passive_plan_deduplication(db):
    """
    Test that passive detection is skipped if a similar plan already exists (avoiding duplicates).
    """
    session_id = "test_session_dedup"
    content = """My plan:
1. Step one
2. Step two
3. Step three
"""
    
    # Mock vector search to return a "hit" (already exists)
    db.execute.return_value = _Result([])
    db.vector_search.return_value = [{"node": {"plan_id": "existing_p"}, "score": 0.95}]
    
    config = {
        "embeddings": {"model": "mock-model"},
        "ingestion": {"max_ingest_chars": 4000}
    }
    
    params = {
        "role": "user",
        "content": content,
        "session_id": session_id
    }
    
    await notify_turn(params, db, config)
    
    # Plan creation should NOT be called
    write_calls = db.execute_write.call_args_list
    plan_created = any("CREATE (p:Plan" in str(call) for call in write_calls)
    assert not plan_created
