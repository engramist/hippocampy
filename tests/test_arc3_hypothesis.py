import pytest
from unittest.mock import MagicMock
from agents.arc3.hypothesis import (
    StateGraph, StateNode, Transition, InvariantDetector, HypothesisManager, Hypothesis
)

# ── StateGraph tests ─────────────────────────────────────────

def test_add_state_new_returns_true():
    graph = StateGraph()
    node = StateNode("hash1", 1, {}, 1.0, [[1]])
    assert graph.add_state(node) is True
    assert "hash1" in graph.nodes

def test_add_state_revisit_returns_false():
    graph = StateGraph()
    node1 = StateNode("hash1", 1, {}, 1.0, [[1]])
    graph.add_state(node1)
    node2 = StateNode("hash1", 2, {}, 1.0, [[1]])
    assert graph.add_state(node2) is False
    assert len(graph.nodes) == 1

def test_detect_loop_on_revisit():
    graph = StateGraph()
    graph.add_state(StateNode("h1", 1, {}, 1.0, [[1]]))
    graph.add_state(StateNode("h2", 2, {}, 1.0, [[2]]))
    assert graph.detect_loop() is None
    graph.add_state(StateNode("h1", 3, {}, 1.0, [[1]]))
    assert graph.detect_loop() == "h1"

def test_no_loop_on_unique_states():
    graph = StateGraph()
    graph.add_state(StateNode("h1", 1, {}, 1.0, [[1]]))
    graph.add_state(StateNode("h2", 2, {}, 1.0, [[2]]))
    graph.add_state(StateNode("h3", 3, {}, 1.0, [[3]]))
    assert graph.detect_loop() is None

def test_get_unexplored_actions():
    graph = StateGraph()
    graph.add_state(StateNode("h1", 1, {}, 1.0, [[1]]))
    graph.add_transition(Transition("h1", "h2", "ACTION1", 1, "", 1, []))
    unexplored = graph.get_unexplored_actions("h1", ["ACTION1", "ACTION2", "ACTION3"])
    assert unexplored == ["ACTION2", "ACTION3"]

def test_get_action_effects_across_states():
    graph = StateGraph()
    graph.add_transition(Transition("h1", "h2", "ACTION1", 1, "diff1", 10, []))
    graph.add_transition(Transition("h3", "h4", "ACTION1", 2, "diff2", 12, []))
    effects = graph.get_action_effects("ACTION1")
    assert len(effects) == 2
    assert effects[0].diff_summary == "diff1"

def test_clear_resets_all():
    graph = StateGraph()
    graph.add_state(StateNode("h1", 1, {}, 1.0, [[1]]))
    graph.add_transition(Transition("h1", "h2", "A1", 1, "", 1, []))
    graph.clear()
    assert len(graph.nodes) == 0
    assert len(graph.edges) == 0
    assert graph._visit_order == []

# ── InvariantDetector tests ──────────────────────────────────

def test_find_static_rows_with_3_frames():
    detector = InvariantDetector(min_frames=3)
    detector.add_frame([[1, 1], [2, 2]])
    detector.add_frame([[1, 1], [3, 3]])
    detector.add_frame([[1, 1], [4, 4]])
    static = detector.find_static_rows()
    assert static == [0] # Row 0 is [1, 1] in all

def test_find_static_rows_insufficient_frames():
    detector = InvariantDetector(min_frames=3)
    detector.add_frame([[1, 1], [2, 2]])
    detector.add_frame([[1, 1], [2, 2]])
    assert detector.find_static_rows() == []

def test_find_dynamic_regions():
    detector = InvariantDetector()
    detector.add_frame([[0, 0, 0], [0, 0, 0]])
    detector.add_frame([[0, 1, 0], [0, 0, 0]])
    regions = detector.find_dynamic_regions()
    assert len(regions) == 1
    assert regions[0]["rows"] == [0]
    assert regions[0]["cols"] == [1]

def test_estimate_hud_rows_bottom_10pct():
    detector = InvariantDetector(min_frames=2)
    # 20 rows
    grid = [[0]*10 for _ in range(20)]
    detector.add_frame(grid)
    detector.add_frame(grid)
    # HUD candidate must be in bottom 10% (rows 18, 19)
    # But wait, find_static_rows needs min_frames (default 3)
    detector.add_frame(grid)
    static = detector.find_static_rows()
    assert 19 in static
    hud = detector.estimate_hud_rows()
    assert 19 in hud
    assert 0 not in hud

# ── HypothesisManager tests ─────────────────────────────────

def test_observe_creates_state_node():
    mgr = HypothesisManager(MagicMock(), "session1")
    mgr.observe([[[1]]], None, 1, ["A1"], {})
    assert "h1" in mgr.graph.nodes or len(mgr.graph.nodes) == 1

def test_observe_records_transition():
    mgr = HypothesisManager(MagicMock(), "session1")
    mgr.observe([[[1]]], None, 1, ["A1"], {})
    mgr.observe([[[2]]], "A1", 2, ["A1"], {})
    assert len(mgr.graph.edges) == 1
    assert mgr.graph.edges[list(mgr.graph.nodes.keys())[0]][0].action == "A1"

def test_hypothesis_generated_from_transition():
    mgr = HypothesisManager(MagicMock(), "session1")
    mgr.observe([[[1]]], None, 1, ["A1"], {})
    mgr.observe([[[2]]], "A1", 2, ["A1"], {})
    assert "action-A1" in mgr.hypotheses

def test_wall_hypothesis_on_zero_change():
    mgr = HypothesisManager(MagicMock(), "session1")
    mgr.observe([[[1]]], None, 1, ["A1"], {})
    mgr.observe([[[1]]], "A1", 2, ["A1"], {})
    # Should have action-A1 AND a wall hypothesis
    assert any(h.id.startswith("wall-") for h in mgr.hypotheses.values())

def test_confidence_update_supports():
    hyp = Hypothesis("h1", "desc", "cat")
    hyp.update(supports=True)
    assert hyp.confidence == 1.0
    assert hyp.support_count == 1

def test_confidence_update_contradicts():
    hyp = Hypothesis("h1", "desc", "cat")
    hyp.update(supports=False)
    assert hyp.confidence == 0.0
    assert hyp.contradiction_count == 1

def test_auto_confirm_at_threshold():
    hyp = Hypothesis("h1", "desc", "cat")
    # MIN_EVIDENCE=3, CONFIRM_THRESHOLD=0.8
    hyp.update(True)
    hyp.update(True)
    hyp.update(True)
    assert hyp.status == "confirmed"

def test_auto_prune_at_threshold():
    hyp = Hypothesis("h1", "desc", "cat")
    # MIN_EVIDENCE=3, PRUNE_THRESHOLD=0.2
    hyp.update(False)
    hyp.update(False)
    hyp.update(False)
    assert hyp.status == "refuted"

def test_explore_policy_when_low_confirmation():
    mgr = HypothesisManager(MagicMock(), "session1")
    mgr.hypotheses["h1"] = Hypothesis("h1", "d", "cat", status="active")
    assert mgr._decide_policy(1.0) == "explore"

def test_exploit_policy_when_low_energy():
    mgr = HypothesisManager(MagicMock(), "session1")
    # EXPLORE_ENERGY_FLOOR = 0.3
    assert mgr._decide_policy(0.2) == "exploit"

@pytest.mark.asyncio
async def test_distill_flushes_confirmed_to_brain():
    brain = MagicMock()
    
    async def mock_notify_turn(**kwargs):
        return {"status": "ok"}
    
    brain.notify_turn = mock_notify_turn

    mgr = HypothesisManager(brain, "session1")
    mgr.hypotheses["h1"] = Hypothesis("h1", "d", "cat", status="confirmed")
    count = await mgr.distill_to_brain()
    assert count == 1

def test_reset_graph_preserves_hypotheses():
    mgr = HypothesisManager(MagicMock(), "session1")
    mgr.hypotheses["h1"] = Hypothesis("h1", "d", "cat")
    mgr.graph.add_state(StateNode("h1", 1, {}, 1.0, [[1]]))
    mgr.reset_graph()
    assert len(mgr.graph.nodes) == 0
    assert "h1" in mgr.hypotheses

def test_energy_from_hud_estimation():
    mgr = HypothesisManager(MagicMock(), "session1")
    # partial bar: row of 10, 5 non-zero
    grid_2d = [[0]*10 for _ in range(10)]
    grid_2d[9] = [1, 1, 1, 1, 1, 0, 0, 0, 0, 0]
    hud_rows = [9]
    energy = mgr._estimate_energy_from_hud(hud_rows, grid_2d)
    assert energy == 0.5

def test_loop_detection_in_observe_output():
    mgr = HypothesisManager(MagicMock(), "session1")
    mgr.observe([[[1]]], None, 1, ["A1"], {})
    mgr.observe([[[2]]], "A1", 2, ["A1"], {})
    res = mgr.observe([[[1]]], "A1", 3, ["A1"], {})
    assert res["loop_detected"] is True

def test_compute_diff_accuracy():
    mgr = HypothesisManager(MagicMock(), "session1")
    prev = [[1, 1], [1, 1]]
    curr = [[1, 2], [1, 1]]
    diff = mgr._compute_diff(prev, curr)
    assert diff["pixels_changed"] == 1
    assert "rows 0-0, cols 1-1" in diff["summary"]
