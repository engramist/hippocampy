import pytest
import asyncio
import sys
import os
import types
from unittest.mock import MagicMock, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Module-level placeholders — set by setup_module before any test runs.
report_outcome = None
current_truth = None
notify_turn = None

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
    """Install stubs and import campy.brain.thalamus.tools right before tests run."""
    global report_outcome, current_truth, notify_turn

    # Stub external dependencies that kuzu needs
    for dep in ["sentence_transformers", "kuzu", "spacy", "spacy.lang", "spacy.lang.en"]:
        if dep not in sys.modules:
            _stub(dep)

    # Stub campy.brain.hippocampus.graph.embeddings
    if "campy.brain.hippocampus.graph.embeddings" not in sys.modules:
        _stub("campy.brain.hippocampus.graph.embeddings",
              embed=lambda text, model_name=None: [0.01] * 384,
              prewarm=lambda model_name=None: None,
              embed_batch=lambda texts, model_name=None: [[0.01] * 384] * len(texts))

    # Stub campy.brain.hippocampus.quest
    if "campy.brain.hippocampus.quest" not in sys.modules:
        _stub("campy.brain.hippocampus.quest",
              get_or_create_main_quest=lambda *a, **kw: "",
              get_or_create_session=lambda *a, **kw: None,
              create_side_quest=lambda *a, **kw: "",
              get_quest_context=lambda *a, **kw: {},
              compute_quest_id=lambda *a, **kw: "a" * 32)

    # Stub campy.brain.temporal_lobe.warm_frontier
    if "campy.brain.temporal_lobe.warm_frontier" not in sys.modules:
        _stub("campy.brain.temporal_lobe.warm_frontier",
              compute_warm_frontier=lambda *a, **kw: None,
              get_warm_nodes=lambda *a, **kw: {})

    # Stub campy.brain.thalamus.working_memory
    if "campy.brain.thalamus.working_memory" not in sys.modules:
        _stub("campy.brain.thalamus.working_memory",
              update_token_estimate=lambda *a, **kw: None,
              estimate_tokens=lambda text: len(text.split()),
              get_loaded_node_ids=lambda *a, **kw: [],
              deduplicate_results=lambda results, *a, **kw: results,
              track_loaded=lambda *a, **kw: None,
              check_context_health=lambda *a, **kw: {'status': 'ok'},
              get_session_token_state=lambda *a, **kw: {},
              get_handoff_context=lambda *a, **kw: {})

    async def _stub_route_session(*a, **kw):
        return type('obj', (object,), {'quest_id': ''})()

    async def _stub_update_routing(*a, **kw):
        return None

    if "campy.brain.hippocampus.hippocampus" not in sys.modules:
        _stub("campy.brain.hippocampus.hippocampus",
              route_session=_stub_route_session,
              update_routing_strength=_stub_update_routing,
              get_active_quests_with_embeddings=lambda *a: [])

    import importlib
    tools_mod = importlib.import_module("campy.brain.thalamus.tools")

    module.report_outcome = tools_mod.report_outcome
    module.current_truth = tools_mod.current_truth
    module.notify_turn = tools_mod.notify_turn

    globals().update({
        "report_outcome": tools_mod.report_outcome,
        "current_truth": tools_mod.current_truth,
        "notify_turn": tools_mod.notify_turn,
    })


def teardown_module(module):
    """Remove stubs and the tools module."""
    for key in _STUBBED_KEYS:
        sys.modules.pop(key, None)
    sys.modules.pop("campy.brain.thalamus.tools", None)
    for key in ["campy.brain.hippocampus.graph.embeddings", "campy.brain.hippocampus.quest",
                "campy.brain.temporal_lobe.warm_frontier", "campy.brain.thalamus.working_memory",
                "campy.brain.hippocampus.hippocampus"]:
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
async def test_valence_propagation_to_concepts(db):
    """
    Test that report_outcome (step-level) creates OUTCOME_SIGNAL edges to ACTS_ON concepts.
    """
    # report_outcome logic for step-level updates:
    # MATCH (ps:PlanStep)-[:STEP_OF]->(p:Plan {plan_id: $pid}) 
    # WHERE ps.step_number = $step_number 
    # MATCH (ps)-[:ACTS_ON]->(c:Concept) 
    # MERGE (ps)-[o:OUTCOME_SIGNAL]->(c)
    
    params = {
        "plan_id": "p1",
        "step_number": 1,
        "outcome": "Failed to deploy",
        "valence": -0.8,
        "session_id": "s1"
    }
    
    await report_outcome(params, db, {})
    
    # Verify OUTCOME_SIGNAL write
    write_calls = db.execute_write.call_args_list
    signal_written = any("OUTCOME_SIGNAL" in str(call) for call in write_calls)
    assert signal_written

@pytest.mark.asyncio
async def test_retrieval_ranking_with_outcome_boost(db):
    """
    Test that current_truth incorporates valence history into ranking.
    """
    session_id = "s1"

    # Mock vector_search results for 2 concepts
    # c1: low similarity (0.7), but positive valence history
    # c2: high similarity (0.8), but negative valence history

    mock_c1 = {"concept_id": "c1", "text_raw": "good concept", "confidence": 1.0, "pathway_strength": 1.0}
    mock_c2 = {"concept_id": "c2", "text_raw": "bad concept", "confidence": 1.0, "pathway_strength": 1.0}

    # Mock vector_search to only return results for Concept table, empty for others
    def mock_vector_search(table_name, index_name, vector, limit):
        if table_name == "Concept":
            return [
                {"node": mock_c1, "score": 0.7},
                {"node": mock_c2, "score": 0.8}
            ]
        return []

    db.vector_search.side_effect = mock_vector_search

    # Mock outcome signals query in current_truth
    # MATCH (ps:PlanStep)-[o:OUTCOME_SIGNAL]->(c:Concept)
    # WHERE c.archived = false
    # RETURN c.concept_id, avg(o.valence), count(o)
    def mock_execute(query, params=None):
        if "OUTCOME_SIGNAL" in query:
            return _Result([
                ["c1", 0.9, 1],  # Positive
                ["c2", -0.9, 1]  # Negative
            ])
        return _Result([])

    db.execute.side_effect = mock_execute

    config = {"embeddings": {"model": "mock"}}
    params = {"query": "test query", "session_id": session_id, "limit": 2}

    response = await current_truth(params, db, config)
    results = response["results"]

    # Calculate expected ranks
    # Rank = ((sim * 0.5) + (strength * 0.3) + (recency * 0.2)) * (1 + outcome_boost)
    # outcome_boost = clamp(valence * 0.3, -0.3, 0.3)

    # c1: sim=0.7, strength=1.0, recency=1.0 -> base_rank = 0.35 + 0.3 + 0.2 = 0.85
    #     boost = 0.9 * 0.3 = 0.27
    #     final = 0.85 * 1.27 = 1.0795

    # c2: sim=0.8, strength=1.0, recency=1.0 -> base_rank = 0.4 + 0.3 + 0.2 = 0.9
    #     boost = -0.9 * 0.3 = -0.27
    #     final = 0.9 * 0.73 = 0.657

    assert len(results) == 2
    assert results[0]["node_id"] == "c1"
    assert results[1]["node_id"] == "c2"
    assert results[0]["outcome_valence"] == 0.9
    assert results[1]["outcome_valence"] == -0.9
    assert "failed" in results[1]["outcome_warning"].lower()

@pytest.mark.asyncio
async def test_passive_outcome_reporting(db):
    """
    Test that notify_turn detects outcome language and auto-reports to an active plan.
    """
    session_id = "s1"
    content = "Nailed it! All tests pass."
    
    # Mock active plan lookup
    def mock_execute(query, params=None):
        if "status = 'active'" in query:
            return _Result([["active_plan_id"]])
        return _Result([])
    db.execute.side_effect = mock_execute
    
    config = {
        "embeddings": {"model": "mock"},
        "ingestion": {"max_ingest_chars": 4000}
    }
    params = {"role": "user", "content": content, "session_id": session_id}
    
    await notify_turn(params, db, config)
    
    # Verify report_outcome logic was triggered (SET ps.actual_outcome or SET p.valence)
    write_calls = db.execute_write.call_args_list
    outcome_reported = any("valence = $valence" in str(call) or "ps.actual_outcome = $outcome" in str(call) for call in write_calls)
    assert outcome_reported
