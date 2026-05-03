import pytest
import asyncio
import sys
import os
import types
from unittest.mock import MagicMock, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Simple result wrapper used by other tests
class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []
        self._idx = 0
    def has_next(self): return self._idx < len(self._rows)
    def get_next(self):
        row = self._rows[self._idx]
        self._idx += 1
        return row

# Module-level placeholders — set by setup_module before any test runs.
notify_turn = None


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


def setup_module(module):
    global notify_turn

    # Stub external dependencies that kuzu needs
    for dep in ["sentence_transformers", "kuzu", "spacy", "spacy.lang", "spacy.lang.en"]:
        if dep not in sys.modules:
            _stub(dep)

    # Stub embeddings
    if "mcp_engine.graph.embeddings" not in sys.modules:
        _stub(
            "mcp_engine.graph.embeddings",
            embed=lambda text, model_name=None: [0.01] * 384,
            prewarm=lambda model_name=None: None,
            embed_batch=lambda texts, model_name=None: [[0.01] * 384] * len(texts)
        )

    # Stub quest & warm frontier & hippocampus
    if "mcp_engine.quest" not in sys.modules:
        _stub("mcp_engine.quest",
              get_or_create_main_quest=lambda *a, **kw: "",
              get_or_create_session=lambda *a, **kw: None,
              create_side_quest=lambda *a, **kw: "",
              get_quest_context=lambda *a, **kw: {},
              compute_quest_id=lambda *a, **kw: "a" * 32)

    if "mcp_engine.warm_frontier" not in sys.modules:
        _stub("mcp_engine.warm_frontier",
              compute_warm_frontier=lambda *a, **kw: None,
              get_warm_nodes=lambda *a, **kw: {})

    # Stub working_memory (we'll assert track_loaded called)
    if "mcp_engine.working_memory" not in sys.modules:
        _stub("mcp_engine.working_memory",
              update_token_estimate=lambda *a, **kw: None,
              estimate_tokens=lambda text: len(text.split()),
              get_loaded_node_ids=lambda *a, **kw: [],
              deduplicate_results=lambda results, *a, **kw: results,
              track_loaded=AsyncMock(return_value=None),
              check_context_health=lambda *a, **kw: {'status': 'ok'},
              get_session_token_state=lambda *a, **kw: {'message_count': 10},
              get_handoff_context=lambda *a, **kw: {})

    # Import tools module after stubbing
    import importlib
    tools_mod = importlib.import_module("mcp_engine.tools")
    notify_turn = tools_mod.notify_turn


@pytest.fixture
def db():
    mock = MagicMock()
    mock.execute = MagicMock()
    mock.execute_write = AsyncMock()
    mock.vector_search = MagicMock()
    return mock


@pytest.mark.asyncio
async def test_proactive_push_on_match(db):
    # Arrange: vector_search returns one lesson and one procedure
    def vs(table_name, index_name, vector, limit):
        if table_name == "Lesson":
            return [{"node": {"lesson_id": "l1", "text_raw": "Plan outcome (failure): crashed", "confidence": 0.9}, "score": 0.83}]
        if table_name == "Procedure":
            return [{"node": {"procedure_id": "proc1", "description": "Retry steps"}, "score": 0.8}]
        return []

    db.vector_search.side_effect = vs

    # db.execute: first call for last_proactive_push_msg_count returns empty
    def mock_execute(query, params=None):
        if "RETURN s.last_proactive_push_msg_count" in query:
            return _Result([])
        if "MATCH (g:KnowledgeGap)" in query:
            return _Result([["g1", "Missing infra tests", 0.9]])
        return _Result([])

    db.execute.side_effect = mock_execute

    params = {"role": "user", "content": "Deployment failed to prod", "session_id": "s1"}
    config = {"embeddings": {"model": "mock"}}

    # Act
    resp = await notify_turn(params, db, config)

    # Assert
    assert resp.get("status") == "ingested"
    pc = resp.get("proactive_context")
    assert pc is not None
    assert pc.get("pushed") is True
    items = pc.get("items")
    lesson = next(i for i in items if i.get("node_type") == "Lesson")
    assert lesson["lesson_id"] == "l1"
    assert lesson["text"] == "Plan outcome (failure): crashed"
    assert lesson["type"] == "lesson"
    assert lesson["domain"] == "generic"
    assert any(i.get("node_type") == "Procedure" and i.get("text") == "Retry steps" for i in items)
    assert any(i.get("node_type") == "KnowledgeGap" and i.get("text") == "Missing infra tests" for i in items)

    # verify we persisted last_proactive_push_msg_count
    write_calls = [str(c) for c in db.execute_write.call_args_list]
    assert any("last_proactive_push_msg_count" in c for c in write_calls)


@pytest.mark.asyncio
async def test_rate_limited_push(db):
    # Arrange: simulate last push recently
    db.vector_search.return_value = []

    def mock_execute(query, params=None):
        if "RETURN s.last_proactive_push_msg_count" in query:
            return _Result([[9]])
        return _Result([])

    db.execute.side_effect = mock_execute

    params = {"role": "user", "content": "Another failure", "session_id": "s1"}
    config = {"embeddings": {"model": "mock"}, "proactive_push": {"min_turns_between_pushes": 5}}

    resp = await notify_turn(params, db, config)
    pc = resp.get("proactive_context")
    assert pc is not None
    assert pc.get("pushed") is False
    assert pc.get("reason") == "rate_limited"
