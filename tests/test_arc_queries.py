from __future__ import annotations

import shutil
import tempfile

import pytest

try:
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
    from campy.brain.thalamus.tool_schemas import TOOLS
    from campy.brain.thalamus.tools import TOOL_HANDLERS
    KUZU_AVAILABLE = True
except ModuleNotFoundError as exc:
    if "kuzu" not in str(exc):
        raise
    TOOLS = []
    TOOL_HANDLERS = {}
    KUZU_AVAILABLE = False


pytestmark = pytest.mark.skipif(not KUZU_AVAILABLE, reason="kuzu not installed")


EXPECTED_ARC_TOOLS = {
    "arc_perceive_state",
    "arc_get_game_context",
    "arc_get_action_evidence",
    "arc_get_untested_actions",
    "arc_get_causal_path",
    "arc_record_action_effect",
    "arc_get_entity_movement",
    "arc_get_goal_evidence",
    "arc_classify_game_archetype",
    "arc_confirm_hypothesis",
    "arc_contradict_hypothesis",
    "arc_update_goal_confidence",
    "arc_get_mechanic_priors",
    "arc_check_action_gate",
    "arc_record_reward_prediction_error",
}


class MockResult:
    def __init__(self, rows):
        self._rows = list(rows)
        self._index = 0

    def has_next(self):
        return self._index < len(self._rows)

    def get_next(self):
        row = self._rows[self._index]
        self._index += 1
        return row


class MockDB:
    def __init__(self, query_rows=None):
        self.query_rows = query_rows or {}
        self.writes = []
        self.reads = []

    def execute(self, query, params=None):
        self.reads.append((query, params or {}))
        for pattern, rows in self.query_rows.items():
            if pattern in query:
                return MockResult(rows)
        return MockResult([])

    async def execute_write(self, query, params=None):
        self.writes.append((query, params or {}))

    def vector_search(self, table, index, vector, limit):
        return []


def test_arc_tools_are_registered_in_registry_and_schema():
    names = {tool["name"] for tool in TOOLS}
    missing_schema = EXPECTED_ARC_TOOLS - names
    missing_registry = EXPECTED_ARC_TOOLS - set(TOOL_HANDLERS)
    assert not missing_schema, f"Missing ARC tool schemas: {sorted(missing_schema)}"
    assert not missing_registry, f"Missing ARC tool handlers: {sorted(missing_registry)}"


@pytest.mark.asyncio
async def test_arc_perceive_state_handles_empty_state():
    db = MockDB()
    handler = TOOL_HANDLERS["arc_perceive_state"]

    result = await handler({"task_id": "t-1", "step": 0, "entities": []}, db, {})

    assert result["ok"] is True
    assert result["snapshot_id"] == "t-1_step0"
    assert result["entity_count"] == 0
    assert result["delta_from_previous"] is None
    assert len(db.writes) == 1
    assert "GridSnapshot" in db.writes[0][0]


@pytest.mark.asyncio
async def test_arc_get_untested_actions_filters_tested_actions():
    db = MockDB({"RETURN DISTINCT af.action_id": [("ACTION1",), ("ACTION3",)]})
    handler = TOOL_HANDLERS["arc_get_untested_actions"]

    result = await handler(
        {"task_id": "t-1", "available_actions": ["ACTION1", "ACTION2", "ACTION3", "ACTION4"]},
        db,
        {},
    )

    assert result == {"untested": ["ACTION2", "ACTION4"], "tested": ["ACTION1", "ACTION3"]}


@pytest.mark.asyncio
async def test_arc_get_action_evidence_returns_stable_shape():
    db = MockDB({"RETURN af.fact_type": [("rule", 0.75, "tested", 4, 2, 3)]})
    handler = TOOL_HANDLERS["arc_get_action_evidence"]

    result = await handler({"task_id": "t-1", "action_id": "ACTION9"}, db, {})

    assert result["tested"] is True
    assert result["action_id"] == "ACTION9"
    assert result["confidence"] == 0.75
    assert result["falsified_count"] == 3
    assert result["causal_power"] == 0.75


@pytest.mark.asyncio
async def test_arc_get_causal_path_is_bounded():
    db = MockDB({"as path_count": [(1, 0.88)]})
    handler = TOOL_HANDLERS["arc_get_causal_path"]

    result = await handler({"task_id": "t-1", "action_id": "ACTION9"}, db, {})

    assert result["path_exists"] is True
    assert result["path_length"] == 4
    query = db.reads[0][0]
    # No variable-length traversal (`*`) — the path uses fixed-length explicit
    # relationship hops so cost stays bounded (B278/B280).
    assert "*" not in query
    assert "DERIVED_FROM_FACT" in query
    assert "MOVED_BY" in query


@pytest.mark.asyncio
async def test_arc_check_action_gate_blocks_after_three_falsifications(monkeypatch):
    async def _allow(*args, **kwargs):
        return {"decision": "go", "reason": "ok"}

    monkeypatch.setattr("campy.brain.basal_ganglia.action_selector.check_action_gate", _allow)
    db = MockDB({
        "COALESCE(af.falsified_count, 0)": [(0.9, "ok", 3, 5)],
        "RETURN DISTINCT af.action_id": [("ACTION2",)],
    })
    handler = TOOL_HANDLERS["arc_check_action_gate"]

    result = await handler(
        {"task_id": "t-1", "action_id": "ACTION9", "available_actions": ["ACTION2", "ACTION5"]},
        db,
        {},
    )

    assert result["go"] is False
    assert result["falsification_count"] == 3
    assert result["untested_available"] is True


@pytest.mark.asyncio
async def test_arc_update_goal_confidence_is_gated_by_progress():
    db = MockDB({"RETURN vc.confidence": [(0.4,)]})
    handler = TOOL_HANDLERS["arc_update_goal_confidence"]

    result = await handler(
        {"task_id": "t-1", "goal_id": "G-1", "new_confidence": 0.9, "has_meaningful_progress": False},
        db,
        {},
    )

    assert result["gated_confidence"] == 0.4
    assert db.writes[-1][1]["conf"] == 0.4


@pytest.mark.asyncio
async def test_arc_contradict_hypothesis_demotes_on_low_confidence():
    db = MockDB({"RETURN h.confidence, h.status": [(0.05, "active")]})
    handler = TOOL_HANDLERS["arc_contradict_hypothesis"]

    result = await handler(
        {"task_id": "t-1", "hypothesis_id": "H-1", "evidence": {"weight": 1.0}},
        db,
        {},
    )

    assert result["falsified"] is True
    assert result["new_confidence"] == 0.05
    assert any("SET h.status = 'demoted'" in query for query, _ in db.writes)


@pytest.mark.asyncio
async def test_arc_record_reward_prediction_error_writes_action_fact():
    db = MockDB()
    handler = TOOL_HANDLERS["arc_record_reward_prediction_error"]

    result = await handler(
        {"task_id": "t-1", "action_id": "ACTION9", "predicted_reward": 0.2, "actual_reward": 0.8},
        db,
        {},
    )

    assert result["direction"] == "positive"
    assert result["prediction_error"] == 0.6
    assert any("prediction_error" in query for query, _ in db.writes)


# ---------------------------------------------------------------------------
# B278 real-Kuzu regression coverage.
#
# The MockDB-based test above only exercises the positive-RPE branch and
# never asserts anything actually persisted — it can't catch a real write
# silently failing to persist (exactly the class of bug ARC_AGI's A146
# consumer-side contract test caught in production: falsified_count stayed
# 0 despite arc_record_reward_prediction_error reporting success). These
# tests exercise the real Kuzu write/read path end to end.
# ---------------------------------------------------------------------------

@pytest.fixture()
def arc_db():
    tmp = tempfile.mkdtemp(prefix="kuzu_arc_queries_")
    db = KuzuClient(f"{tmp}/db")
    db.execute(
        "CREATE NODE TABLE ActionEffect (effect_id STRING, task_id STRING, "
        "action_id STRING, step INT32, n_cells_changed INT32, "
        "apparent_effect STRING, created_at TIMESTAMP, PRIMARY KEY (effect_id))"
    )
    db.execute(
        "CREATE NODE TABLE ActionFact (fact_id STRING, task_id STRING, "
        "action_id STRING, fact_type STRING, confidence DOUBLE, "
        "value_status STRING, evidence_count INT32, observation_count INT32, "
        "falsified_count INT32, last_updated TIMESTAMP, PRIMARY KEY (fact_id))"
    )
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_large_negative_rpe_persists_falsified_count(arc_db):
    """Regression test for the B278 persistence bug (ARC_AGI handoff doc,
    docs/handoff/B278-graph-evidence.md): a large negative RPE (error < -0.3)
    must actually increment ActionFact.falsified_count, not just report
    success. Verified with a real KuzuDB, not a mock."""
    record_effect = TOOL_HANDLERS["arc_record_action_effect"]
    record_rpe = TOOL_HANDLERS["arc_record_reward_prediction_error"]
    get_evidence = TOOL_HANDLERS["arc_get_action_evidence"]

    await record_effect(
        {"task_id": "t-real", "action_id": "ACTION1", "step": 0, "effect": {}},
        arc_db, {},
    )
    result = await record_rpe(
        {"task_id": "t-real", "action_id": "ACTION1", "step": 0,
         "predicted_reward": 1.0, "actual_reward": 0.0},
        arc_db, {},
    )
    assert result["direction"] == "negative"

    evidence = await get_evidence({"task_id": "t-real", "action_id": "ACTION1"}, arc_db, {})
    assert evidence["falsified_count"] == 1


@pytest.mark.asyncio
async def test_moderate_negative_rpe_direction_matches_write_behavior(arc_db):
    """error in (-0.3, -0.1) currently reports direction="negative" even
    though the write threshold is -0.3, so no write happens — the caller is
    told something occurred that didn't. direction must reflect whether a
    write actually happened, not use an independent threshold."""
    record_effect = TOOL_HANDLERS["arc_record_action_effect"]
    record_rpe = TOOL_HANDLERS["arc_record_reward_prediction_error"]
    get_evidence = TOOL_HANDLERS["arc_get_action_evidence"]

    await record_effect(
        {"task_id": "t-moderate", "action_id": "ACTION1", "step": 0, "effect": {}},
        arc_db, {},
    )
    # predicted=0.5, actual=0.3 -> error = -0.2 (between -0.3 and -0.1: no write)
    result = await record_rpe(
        {"task_id": "t-moderate", "action_id": "ACTION1", "step": 0,
         "predicted_reward": 0.5, "actual_reward": 0.3},
        arc_db, {},
    )

    evidence = await get_evidence({"task_id": "t-moderate", "action_id": "ACTION1"}, arc_db, {})
    assert evidence["falsified_count"] == 0, "no write should have happened at this error magnitude"
    assert result["direction"] == "neutral", (
        "direction must not claim 'negative' when no write occurred"
    )