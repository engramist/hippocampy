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
    "record_transition",
    "get_entity_history",
    "record_rule",
    "get_rules_for_action",
    "get_transferred_rules",
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


# ---------------------------------------------------------------------------
# B309 real-Kuzu regression coverage — A175-A179's pending server-side half.
#
# These tools traverse GridEntity/ActionEffect/MOVED_BY (existing B168/B278
# schema) plus the new Transition/Rule node tables and TRANSITION_OF rel
# table. The MockDB above can't validate real Cypher against real column/rel
# definitions (same class of bug B277/B280/B284 found this session), so this
# uses the full production schema via init_schema(), module-scoped since
# it's expensive; tests use disjoint task_ids to stay independent.
# ---------------------------------------------------------------------------

from campy.brain.hippocampus.schema import init_schema

_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_SEED_EXAMPLES_PATH = "campy/data/GistSeedExamples.md"


@pytest.fixture(scope="module")
def b309_db():
    tmp = tempfile.mkdtemp(prefix="kuzu_b309_arc_")
    db = KuzuClient(f"{tmp}/db")
    init_schema(db, _SEED_EXAMPLES_PATH, _EMBEDDING_MODEL)
    yield db
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.asyncio
async def test_a175_moved_by_written_when_entity_centroid_changes(b309_db):
    """Reproduction from docs/handoff/B278-entity-identity-and-moved-by.md:
    same task_id/color_id/region_index across two steps, centroid genuinely
    moves -> arc_get_entity_movement must return a non-empty entry with the
    correct delta, and arc_get_causal_path's MOVED_BY hop becomes reachable."""
    perceive = TOOL_HANDLERS["arc_perceive_state"]
    get_movement = TOOL_HANDLERS["arc_get_entity_movement"]

    await perceive(
        {"task_id": "b309-moved", "step": 0, "grid_hash": "h0",
         "entities": [{"color_id": 5, "region_index": 0,
                       "centroid_row": 2.0, "centroid_col": 2.0, "pixel_count": 1}]},
        b309_db, {},
    )
    await perceive(
        {"task_id": "b309-moved", "step": 1, "grid_hash": "h1",
         "entities": [{"color_id": 5, "region_index": 0,
                       "centroid_row": 2.0, "centroid_col": 5.0, "pixel_count": 1}]},
        b309_db, {},
    )

    result = await get_movement({"task_id": "b309-moved", "step": 1}, b309_db, {})

    assert result["entities"], "expected a MOVED_BY entry, got none"
    entry = result["entities"][0]
    assert entry["id"] == "b309-moved_e5_0"
    assert entry["delta_col"] == pytest.approx(3.0)
    assert entry["delta_row"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_a175_no_moved_by_when_centroid_unchanged(b309_db):
    """A stationary entity across two steps must not produce a MOVED_BY edge."""
    perceive = TOOL_HANDLERS["arc_perceive_state"]
    get_movement = TOOL_HANDLERS["arc_get_entity_movement"]

    await perceive(
        {"task_id": "b309-still", "step": 0, "grid_hash": "h0",
         "entities": [{"color_id": 7, "region_index": 0,
                       "centroid_row": 1.0, "centroid_col": 1.0, "pixel_count": 1}]},
        b309_db, {},
    )
    await perceive(
        {"task_id": "b309-still", "step": 1, "grid_hash": "h1",
         "entities": [{"color_id": 7, "region_index": 0,
                       "centroid_row": 1.0, "centroid_col": 1.0, "pixel_count": 1}]},
        b309_db, {},
    )

    result = await get_movement({"task_id": "b309-still", "step": 1}, b309_db, {})
    assert result["entities"] == []


@pytest.mark.asyncio
async def test_a176_record_transition_and_get_entity_history(b309_db):
    """record_transition persists per-step history; get_entity_history
    reads it back matching the request/response shapes in the A176 hand-off doc."""
    perceive = TOOL_HANDLERS["arc_perceive_state"]
    record_transition = TOOL_HANDLERS["record_transition"]
    get_history = TOOL_HANDLERS["get_entity_history"]

    # entity_ref resolves against a real GridEntity's region_index.
    await perceive(
        {"task_id": "b309-hist", "step": 0, "grid_hash": "h0",
         "entities": [{"color_id": 5, "region_index": 1,
                       "centroid_row": 0.0, "centroid_col": 0.0, "pixel_count": 1}]},
        b309_db, {},
    )

    result = await record_transition(
        {"task_id": "b309-hist", "step": 4, "action_id": "ACTION6",
         "changed_count": 3, "color_transitions": [{"from": 2, "to": 5, "count": 3}],
         "entity_ref": 1},
        b309_db, {},
    )
    assert result["ok"] is True
    assert result["transition_id"]

    history = await get_history({"task_id": "b309-hist", "entity_ref": 1}, b309_db, {})
    assert history["changed_count_total"] == 3
    assert len(history["transitions"]) == 1
    entry = history["transitions"][0]
    assert entry["action_id"] == "ACTION6"
    assert entry["step"] == 4
    assert entry["color_transitions"] == [{"from": 2, "to": 5, "count": 3}]


@pytest.mark.asyncio
async def test_a176_entity_ref_null_is_legitimate_not_an_error(b309_db):
    """entity_ref may be null (changed cells didn't fall inside a known
    entity's bbox) - must persist cleanly, not error."""
    record_transition = TOOL_HANDLERS["record_transition"]

    result = await record_transition(
        {"task_id": "b309-noref", "step": 2, "action_id": "ACTION3",
         "changed_count": 1, "color_transitions": [{"from": 1, "to": 2, "count": 1}],
         "entity_ref": None},
        b309_db, {},
    )
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_a176_get_entity_history_empty_for_unknown_entity(b309_db):
    """No recorded history -> empty result, not an error."""
    get_history = TOOL_HANDLERS["get_entity_history"]

    history = await get_history({"task_id": "b309-nohist", "entity_ref": 99}, b309_db, {})
    assert history == {"transitions": [], "changed_count_total": 0}


@pytest.mark.asyncio
async def test_a177_record_rule_creates_confirms_falsifies(b309_db):
    """A new (action_family, from_color) creates a Rule; a repeat with the
    same to_color confirms it (confidence increases, stays unfalsified); a
    repeat with a different to_color falsifies it."""
    record_rule = TOOL_HANDLERS["record_rule"]
    get_rules = TOOL_HANDLERS["get_rules_for_action"]

    task_id = "b309-rules"
    sig = {"action_family": "ACTION6", "from_color": 2, "to_color": 5}

    created = await record_rule(
        {"task_id": task_id, "step": 0, "action_id": "ACTION6",
         "candidate_signatures": [sig], "fingerprint": "ACTION6:small"},
        b309_db, {},
    )
    assert created["results"][0]["status"] == "created"

    rules_after_create = await get_rules({"task_id": task_id, "action_id": "ACTION6"}, b309_db, {})
    assert len(rules_after_create["rules"]) == 1
    initial_confidence = rules_after_create["rules"][0]["confidence"]
    assert rules_after_create["rules"][0]["falsified"] is False

    confirmed = await record_rule(
        {"task_id": task_id, "step": 1, "action_id": "ACTION6",
         "candidate_signatures": [sig], "fingerprint": "ACTION6:small"},
        b309_db, {},
    )
    assert confirmed["results"][0]["status"] == "confirmed"

    rules_after_confirm = await get_rules({"task_id": task_id, "action_id": "ACTION6"}, b309_db, {})
    assert len(rules_after_confirm["rules"]) == 1
    assert rules_after_confirm["rules"][0]["confidence"] > initial_confidence
    assert rules_after_confirm["rules"][0]["falsified"] is False

    falsifying_sig = {"action_family": "ACTION6", "from_color": 2, "to_color": 9}
    falsified = await record_rule(
        {"task_id": task_id, "step": 2, "action_id": "ACTION6",
         "candidate_signatures": [falsifying_sig], "fingerprint": "ACTION6:small"},
        b309_db, {},
    )
    assert falsified["results"][0]["status"] == "falsified"

    rules_after_falsify = await get_rules({"task_id": task_id, "action_id": "ACTION6"}, b309_db, {})
    assert rules_after_falsify["rules"] == [], "falsified rule must not be returned as a live rule"


@pytest.mark.asyncio
async def test_a179_get_transferred_rules_is_cross_game_only(b309_db):
    """A rule recorded under task_id=A with fingerprint=X is returned when
    queried from a different task_id=B with the same fingerprint, and is NOT
    returned when queried from task_id=A itself (self) or a different
    fingerprint."""
    record_rule = TOOL_HANDLERS["record_rule"]
    get_transferred = TOOL_HANDLERS["get_transferred_rules"]

    await record_rule(
        {"task_id": "b309-game-a", "step": 0, "action_id": "ACTION6",
         "candidate_signatures": [{"action_family": "ACTION6", "from_color": 2, "to_color": 5}],
         "fingerprint": "ACTION6:small"},
        b309_db, {},
    )

    same_fp_other_game = await get_transferred(
        {"task_id": "b309-game-b", "fingerprint": "ACTION6:small"}, b309_db, {}
    )
    assert len(same_fp_other_game["rules"]) == 1
    assert same_fp_other_game["rules"][0]["source_game_id"] == "b309-game-a"

    self_query = await get_transferred(
        {"task_id": "b309-game-a", "fingerprint": "ACTION6:small"}, b309_db, {}
    )
    assert self_query["rules"] == [], "must not return a game's own rules as 'transferred'"

    different_fp = await get_transferred(
        {"task_id": "b309-game-b", "fingerprint": "ACTION1:large"}, b309_db, {}
    )
    assert different_fp["rules"] == []