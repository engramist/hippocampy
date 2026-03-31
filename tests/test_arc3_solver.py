"""Tests for agents/arc3/solver.py — ARC Solve Engine."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from agents.arc3.solver import (
    ArchetypeClassifier, GameArchetype, ObjectRoleMapper, RoleType,
    ObjectRole,
    VictoryHypothesizer, VictoryType, VictoryCondition,
    DissonanceDetector, PlanChunker, SolveEngine, SolveContext,
)


# ── ArchetypeClassifier ─────────────────────────────────────────────

def test_archetype_unknown_before_min_observations():
    clf = ArchetypeClassifier()
    for _ in range(4):
        archetype, conf = clf.update({})
    assert archetype == GameArchetype.UNKNOWN


def test_archetype_race_from_hud_and_reward():
    clf = ArchetypeClassifier()
    ctx = {
        "action_facts": [
            {"fact_type": "deterministic_effect", "value_status": "valuable"},
            {"fact_type": "deterministic_effect", "value_status": "valuable"},
        ],
        "hud_rows": [61, 62],
        "path_hypotheses": [],
    }
    for _ in range(5):
        archetype, conf = clf.update(ctx)
    assert archetype == GameArchetype.RACE
    assert conf > 0.0


def test_archetype_analogy_votes_boost_confidence():
    clf = ArchetypeClassifier()
    analogy_results = [
        {"text_raw": "ARC chase game player flees enemy", "similarity": 0.75},
        {"text_raw": "chase archetype convergence detected", "similarity": 0.70},
    ]
    archetype, conf = clf.apply_analogy_votes(
        GameArchetype.CHASE, 0.45, analogy_results
    )
    assert archetype == GameArchetype.CHASE
    assert conf > 0.45


def test_archetype_analogy_disagreement_caps_confidence():
    clf = ArchetypeClassifier()
    analogy_results = [
        {"text_raw": "race archetype linear path", "similarity": 0.80},
    ]
    archetype, conf = clf.apply_analogy_votes(
        GameArchetype.CHASE, 0.60, analogy_results
    )
    assert conf <= 0.5  # disagreement caps confidence


# ── ObjectRoleMapper ─────────────────────────────────────────────────

def test_object_role_wall_on_static_frame():
    mapper = ObjectRoleMapper()
    ctx = {
        "static_rows": [60, 61],
        "last_transition_effect": {"meaningful_change_score": 0.0, "regions_changed": []},
    }
    obs = {"colors": [{"value": 3, "count": 10}]}
    roles = mapper.update(ctx, obs, step=5)
    assert 3 in roles
    assert roles[3].role == RoleType.WALL


def test_object_role_player_on_changed_center_with_reward():
    mapper = ObjectRoleMapper()
    ctx = {
        "static_rows": [],
        "last_transition_effect": {
            "meaningful_change_score": 0.7,
            "regions_changed": ["center"],
            "changed_center": {"row": 10.0, "col": 8.0},
        },
    }
    obs = {"colors": [{"value": 5, "count": 1}]}
    roles = mapper.update(ctx, obs, step=3)
    assert 5 in roles
    assert roles[5].role == RoleType.PLAYER
    assert roles[5].estimated_position == {"row": 10.0, "col": 8.0}


# ── VictoryHypothesizer ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_victory_hypothesizer_calls_recall_plans():
    brain = AsyncMock()
    brain.recall_plans.return_value = {"plans": []}
    brain.recall_relevant_lessons.return_value = {"lessons": []}

    llm = AsyncMock()
    llm.complete.return_value = '{"condition_type":"reach_goal","description":"reach exit","target_color_id":6,"confidence":0.7}'

    vh = VictoryHypothesizer()
    vc = await vh.hypothesize(
        archetype=GameArchetype.CHASE,
        object_roles={},
        brain_client=brain,
        llm_client=llm,
        session_id="s1",
        task_id="t1",
        reward_history=[0.0, 0.0, 1.0],
    )
    brain.recall_plans.assert_called_once()
    brain.recall_relevant_lessons.assert_called_once()
    assert vc.condition_type == VictoryType.REACH_GOAL
    assert vc.confidence == 0.7
    assert vc.source == "llm"


@pytest.mark.asyncio
async def test_victory_hypothesizer_uses_high_valence_plan_directly():
    brain = AsyncMock()
    brain.recall_plans.return_value = {
        "plans": [{"goal": "reach exit bottom-right", "valence": 0.9}]
    }
    brain.recall_relevant_lessons.return_value = {"lessons": []}

    llm = AsyncMock()
    vh = VictoryHypothesizer()
    vc = await vh.hypothesize(
        archetype=GameArchetype.RACE,
        object_roles={},
        brain_client=brain,
        llm_client=llm,
        session_id="s1",
        task_id="t1",
        reward_history=[],
    )
    llm.complete.assert_not_called()   # high-valence plan skips LLM
    assert vc.source == "recall_plans"


@pytest.mark.asyncio
async def test_victory_hypothesizer_handles_llm_parse_error():
    brain = AsyncMock()
    brain.recall_plans.return_value = {"plans": []}
    brain.recall_relevant_lessons.return_value = {"lessons": []}
    llm = AsyncMock()
    llm.complete.return_value = "INVALID JSON {{{"

    vh = VictoryHypothesizer()
    vc = await vh.hypothesize(
        GameArchetype.UNKNOWN, {}, brain, llm, "s1", "t1", []
    )
    assert vc.source == "error"
    assert vc.confidence < 0.2


# ── DissonanceDetector ───────────────────────────────────────────────

def test_dissonance_fires_after_stall_threshold():
    dd = DissonanceDetector()
    from agents.arc3.solver import PlanChunk
    chunk = PlanChunk(description="test chunk", progress_score=0.0)
    ctx = {"last_transition_effect": {"meaningful_change_score": 0.05}}
    dissonance = False
    for i in range(DissonanceDetector.STALL_THRESHOLD + 1):
        dissonance, reason = dd.update(ctx, chunk, step=i)
    assert dissonance is True
    assert "no meaningful change" in reason


def test_dissonance_resets_on_good_progress():
    dd = DissonanceDetector()
    from agents.arc3.solver import PlanChunk
    chunk = PlanChunk(description="test")
    low_ctx = {"last_transition_effect": {"meaningful_change_score": 0.05}}
    good_ctx = {"last_transition_effect": {"meaningful_change_score": 0.8}}
    for _ in range(4):
        dd.update(low_ctx, chunk, step=0)
    dd.update(good_ctx, chunk, step=5)   # resets streak
    dissonance, _ = dd.update(low_ctx, chunk, step=6)
    assert not dissonance  # streak reset, only 1 zero-progress step


# ── PlanChunker ──────────────────────────────────────────────────────

def test_plan_chunker_bfs_on_state_graph():
    from agents.arc3.hypothesis import StateGraph, StateNode, Transition
    from agents.arc3.solver import PlanChunker, VictoryCondition, VictoryType

    graph = StateGraph()
    graph.add_state(StateNode("h1", 1, {}, 1.0, []))
    graph.add_state(StateNode("h2", 2, {}, 1.0, []))
    graph.add_state(StateNode("h3", 3, {}, 1.0, []))
    t1 = Transition("h1", "h2", "ACTION1", 1, "", 5, [])
    t1.reward_signal = 0.8
    t2 = Transition("h2", "h3", "ACTION2", 2, "", 5, [])
    t2.reward_signal = 0.0
    graph.add_transition(t1)
    graph.add_transition(t2)

    vc = VictoryCondition(condition_type=VictoryType.REACH_GOAL, description="test")
    chunker = PlanChunker()
    # BFS requires a goal_role to be identified
    object_roles = {6: ObjectRole(color_id=6, role=RoleType.GOAL)}
    chunk = chunker.generate_chunk(
        victory_condition=vc,
        object_roles=object_roles,
        state_graph=graph,
        current_hash="h1",
        available_actions=["ACTION1", "ACTION2", "ACTION3"],
        step=5,
    )
    # BFS should find path through high-reward state h2
    assert chunk.source == "bfs"
    assert "ACTION1" in chunk.estimated_actions


def test_plan_chunker_falls_back_to_exploration_when_no_graph():
    from agents.arc3.hypothesis import StateGraph, StateNode
    from agents.arc3.solver import PlanChunker, VictoryCondition, VictoryType

    graph = StateGraph()  # empty
    graph.add_state(StateNode("h1", 1, {}, 1.0, []))
    vc = VictoryCondition(condition_type=VictoryType.REACH_GOAL, description="test")
    chunker = PlanChunker()
    chunk = chunker.generate_chunk(vc, {}, graph, "h1", ["ACTION1", "ACTION2"], step=1)
    assert chunk.source == "explore"
    assert len(chunk.estimated_actions) >= 1


# ── SolveEngine integration ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_solve_engine_reset_preserves_archetype():
    from agents.arc3.solver import SolveEngine, PlanChunk

    brain = AsyncMock()
    brain.recall_plans.return_value = {"plans": []}
    brain.recall_relevant_lessons.return_value = {"lessons": []}
    brain.analogical_search.return_value = {"results": []}
    brain.register_plan.return_value = {"plan_id": "p1"}

    llm = AsyncMock()
    engine = SolveEngine(brain, llm, "s1")
    engine._archetype = GameArchetype.CHASE
    engine._archetype_confidence = 0.8
    engine._archetype_locked = True
    engine._active_chunk = PlanChunk(description="old chunk")
    engine._chunk_plan_id = "p-old"

    engine.reset_for_retry()

    assert engine._archetype == GameArchetype.CHASE   # preserved
    assert engine._archetype_locked is True           # preserved
    assert engine._active_chunk is None               # cleared
    assert engine._chunk_plan_id is None              # cleared


@pytest.mark.asyncio
async def test_solve_engine_dissonance_calls_report_outcome():
    from agents.arc3.solver import SolveEngine, PlanChunk, VictoryCondition, VictoryType

    brain = AsyncMock()
    brain.report_outcome.return_value = {"status": "ok"}
    brain.register_plan.return_value = {"plan_id": "p-new"}
    brain.recall_plans.return_value = {"plans": []}
    brain.recall_relevant_lessons.return_value = {"lessons": []}
    brain.analogical_search.return_value = {"results": []}

    llm = AsyncMock()
    llm.complete.return_value = '{"condition_type":"reach_goal","description":"reach exit","target_color_id":null,"confidence":0.5}'

    engine = SolveEngine(brain, llm, "s1")
    engine._archetype = GameArchetype.CHASE
    engine._archetype_confidence = 0.7
    engine._archetype_locked = True
    engine._victory_condition = VictoryCondition(
        condition_type=VictoryType.REACH_GOAL, confidence=0.6, description="reach exit"
    )
    engine._active_chunk = PlanChunk(description="stalled chunk", progress_score=0.0)
    engine._chunk_plan_id = "p-stall"
    # Force stall
    engine.dissonance_detector._zero_progress_streak = 10

    from agents.arc3.hypothesis import StateGraph
    graph = StateGraph()
    ctx = {
        "last_transition_effect": {"meaningful_change_score": 0.0, "reward_signal": 0.0},
        "action_facts": [], "hud_rows": [], "path_hypotheses": [],
        "current_state_hash": "h1",
    }
    obs = {"colors": [], "available_actions": ["ACTION1"], "task_id": "t1", "dataset_id": "d1"}

    await engine.solve(obs, ctx, step=20, state_graph=graph, current_state_hash="h1")

    brain.report_outcome.assert_called_once()
    call_kwargs = brain.report_outcome.call_args.kwargs
    assert call_kwargs["valence"] < 0
    assert call_kwargs["plan_id"] == "p-stall"
