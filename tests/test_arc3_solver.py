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


def test_object_role_wall_requires_persistence_on_grid():
    mapper = ObjectRoleMapper()
    grid = [[0] * 4 for _ in range(4)]
    grid[0][0] = 3
    grid[0][1] = 3
    grid[1][0] = 3
    grid[1][1] = 3
    obs = {"grid": grid, "colors": [{"value": 0, "count": 12}, {"value": 3, "count": 4}]}
    ctx = {
        "static_rows": [0, 1],
        "hud_rows": [],
        "action_facts": [],
        "last_transition_effect": {"meaningful_change_score": 0.0, "changed_region": {}},
    }

    roles1 = mapper.update(ctx, obs, step=1)
    assert roles1[3].role != RoleType.WALL

    roles2 = mapper.update(ctx, obs, step=2)
    assert roles2[3].role != RoleType.WALL

    roles3 = mapper.update(ctx, obs, step=3)
    assert roles3[3].role == RoleType.WALL


def test_object_role_static_row_participant_with_changed_region_is_not_wall():
    mapper = ObjectRoleMapper()
    grid = [[0] * 4 for _ in range(4)]
    grid[0][1] = 3
    obs = {"grid": grid, "colors": [{"value": 0, "count": 15}, {"value": 3, "count": 1}]}

    ctx0 = {
        "static_rows": [0],
        "hud_rows": [],
        "action_facts": [],
        "last_transition_effect": {},
    }
    mapper.update(ctx0, obs, step=1)

    ctx1 = {
        "static_rows": [0],
        "hud_rows": [],
        "action_facts": [{"action": "ACTION5", "trend": {"direction": "left"}}],
        "last_transition_effect": {
            "action": "ACTION5",
            "meaningful_change_score": 0.2,
            "changed_center": {"row": 0.0, "col": 1.0},
            "changed_region": {"row_range": [0, 0], "col_range": [1, 1]},
        },
    }
    roles = mapper.update(ctx1, obs, step=2)
    assert roles[3].role != RoleType.WALL


def test_object_role_player_from_small_changed_region_chain():
    mapper = ObjectRoleMapper()

    grid0 = [[0] * 8 for _ in range(8)]
    grid0[5][6] = 3
    obs0 = {"grid": grid0, "colors": [{"value": 0, "count": 63}, {"value": 3, "count": 1}]}
    ctx0 = {"static_rows": [], "hud_rows": [], "action_facts": [], "last_transition_effect": {}}
    mapper.update(ctx0, obs0, step=1)

    grid1 = [[0] * 8 for _ in range(8)]
    grid1[5][5] = 3
    obs1 = {"grid": grid1, "colors": [{"value": 0, "count": 63}, {"value": 3, "count": 1}]}
    ctx1 = {
        "static_rows": [],
        "hud_rows": [],
        "action_facts": [{"action": "ACTION5", "trend": {"direction": "left"}}],
        "last_transition_effect": {
            "action": "ACTION5",
            "meaningful_change_score": 0.2,
            "changed_center": {"row": 5.0, "col": 5.5},
            "changed_region": {"row_range": [5, 5], "col_range": [5, 6]},
        },
    }
    mapper.update(ctx1, obs1, step=2)

    grid2 = [[0] * 8 for _ in range(8)]
    grid2[5][4] = 3
    obs2 = {"grid": grid2, "colors": [{"value": 0, "count": 63}, {"value": 3, "count": 1}]}
    ctx2 = {
        "static_rows": [],
        "hud_rows": [],
        "action_facts": [{"action": "ACTION5", "trend": {"direction": "left"}}],
        "last_transition_effect": {
            "action": "ACTION5",
            "meaningful_change_score": 0.2,
            "changed_center": {"row": 5.0, "col": 4.5},
            "changed_region": {"row_range": [5, 5], "col_range": [4, 5]},
        },
    }
    roles = mapper.update(ctx2, obs2, step=3)
    assert roles[3].role == RoleType.PLAYER
    assert roles[3].confidence >= 0.6


def test_object_role_goal_from_player_proximity_without_reward():
    mapper = ObjectRoleMapper()

    grid0 = [[0] * 8 for _ in range(8)]
    grid0[5][1] = 2
    grid0[5][6] = 7
    obs0 = {
        "grid": grid0,
        "colors": [{"value": 0, "count": 62}, {"value": 2, "count": 1}, {"value": 7, "count": 1}],
    }
    ctx0 = {"static_rows": [], "hud_rows": [], "action_facts": [], "last_transition_effect": {}}
    mapper.update(ctx0, obs0, step=1)

    grid1 = [[0] * 8 for _ in range(8)]
    grid1[5][2] = 2
    grid1[5][6] = 7
    obs1 = {
        "grid": grid1,
        "colors": [{"value": 0, "count": 62}, {"value": 2, "count": 1}, {"value": 7, "count": 1}],
    }
    ctx1 = {
        "static_rows": [],
        "hud_rows": [],
        "action_facts": [{"action": "ACTION4", "trend": {"direction": "right"}}],
        "last_transition_effect": {
            "action": "ACTION4",
            "meaningful_change_score": 0.2,
            "pixels_changed": 2,
            "changed_center": {"row": 5.0, "col": 1.5},
            "changed_region": {"row_range": [5, 5], "col_range": [1, 2]},
        },
    }
    mapper.update(ctx1, obs1, step=2)

    grid2 = [[0] * 8 for _ in range(8)]
    grid2[5][3] = 2
    grid2[5][6] = 7
    obs2 = {
        "grid": grid2,
        "colors": [{"value": 0, "count": 62}, {"value": 2, "count": 1}, {"value": 7, "count": 1}],
    }
    ctx2 = {
        "static_rows": [],
        "hud_rows": [],
        "action_facts": [{"action": "ACTION4", "trend": {"direction": "right"}}],
        "last_transition_effect": {
            "action": "ACTION4",
            "meaningful_change_score": 0.2,
            "pixels_changed": 2,
            "changed_center": {"row": 5.0, "col": 2.5},
            "changed_region": {"row_range": [5, 5], "col_range": [2, 3]},
        },
    }
    roles = mapper.update(ctx2, obs2, step=3)
    assert roles[2].role == RoleType.PLAYER
    assert roles[7].role == RoleType.GOAL
    assert roles[7].confidence >= 0.55


# ── VictoryHypothesizer ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_victory_hypothesizer_calls_recall_plans():
    brain = AsyncMock()
    brain.recall_plans.return_value = {"plans": []}
    brain.recall_relevant_lessons.return_value = {"lessons": []}

    llm = AsyncMock()
    llm.achat.return_value = '{"condition_type":"reach_goal","description":"reach exit","target_color_id":6,"confidence":0.7}'

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
    llm.achat.assert_not_called()   # high-valence plan skips LLM
    assert vc.source == "recall_plans"


@pytest.mark.asyncio
async def test_victory_hypothesizer_handles_llm_parse_error():
    brain = AsyncMock()
    brain.recall_plans.return_value = {"plans": []}
    brain.recall_relevant_lessons.return_value = {"lessons": []}
    llm = AsyncMock()
    llm.achat.return_value = "INVALID JSON {{{"

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


def test_plan_chunker_graduates_to_directional_once_evidence_is_strong():
    from agents.arc3.hypothesis import StateGraph, StateNode
    from agents.arc3.solver import PlanChunker, VictoryCondition, VictoryType

    graph = StateGraph()
    graph.add_state(StateNode("h1", 1, {}, 1.0, []))
    vc = VictoryCondition(condition_type=VictoryType.REACH_GOAL, description="reach exit")
    chunker = PlanChunker()
    object_roles = {
        1: ObjectRole(
            color_id=1,
            role=RoleType.PLAYER,
            confidence=0.8,
            estimated_position={"row": 4.0, "col": 2.0},
        ),
        9: ObjectRole(
            color_id=9,
            role=RoleType.GOAL,
            confidence=0.75,
            estimated_position={"row": 1.0, "col": 2.0},
        ),
    }
    hypothesis_context = {
        "action_coverage": {
            "initial_exploration_complete": True,
            "tested_count": 6,
            "untested_count": 0,
        },
        "action_facts": [
            {"fact_type": "deterministic_effect", "value_status": "valuable"},
            {"fact_type": "deterministic_effect", "value_status": "valuable"},
        ],
        "path_hypotheses": [
            {"value_status": "tentative"},
            {"value_status": "valuable"},
        ],
    }

    chunk = chunker.generate_chunk(
        victory_condition=vc,
        object_roles=object_roles,
        state_graph=graph,
        current_hash="h1",
        available_actions=["ACTION1", "ACTION2", "ACTION3", "ACTION4", "ACTION5", "ACTION6"],
        step=8,
        hypothesis_context=hypothesis_context,
    )

    assert chunk.source == "directional"
    assert chunk.estimated_actions[:3] == ["ACTION1", "ACTION1", "ACTION1"]
    assert chunk.graduation_score >= chunker.GRADUATION_THRESHOLD
    assert "graduate directional" in chunk.graduation_reason
    assert chunk.graduation_components["coverage_ratio"] == 1.0


def test_plan_chunker_keeps_exploration_when_evidence_is_weak():
    from agents.arc3.hypothesis import StateGraph, StateNode
    from agents.arc3.solver import PlanChunker, VictoryCondition, VictoryType

    graph = StateGraph()
    graph.add_state(StateNode("h1", 1, {}, 1.0, []))
    vc = VictoryCondition(condition_type=VictoryType.REACH_GOAL, description="reach exit")
    chunker = PlanChunker()
    object_roles = {
        1: ObjectRole(
            color_id=1,
            role=RoleType.PLAYER,
            confidence=0.78,
            estimated_position={"row": 4.0, "col": 2.0},
        ),
        9: ObjectRole(
            color_id=9,
            role=RoleType.GOAL,
            confidence=0.72,
            estimated_position={"row": 1.0, "col": 2.0},
        ),
    }
    hypothesis_context = {
        "action_coverage": {
            "initial_exploration_complete": False,
            "tested_count": 3,
            "untested_count": 3,
            "top_two_low_value": False,
        },
        "action_facts": [
            {"fact_type": "deterministic_effect", "value_status": "low_value"},
        ],
        "path_hypotheses": [
            {"value_status": "tentative"},
        ],
    }

    chunk = chunker.generate_chunk(
        victory_condition=vc,
        object_roles=object_roles,
        state_graph=graph,
        current_hash="h1",
        available_actions=["ACTION1", "ACTION2", "ACTION3", "ACTION4", "ACTION5", "ACTION6"],
        step=2,
        hypothesis_context=hypothesis_context,
    )

    assert chunk.source == "explore"
    assert chunk.estimated_actions == ["ACTION1"]
    assert "stay explore" in chunk.graduation_reason
    assert "coverage" in chunk.graduation_reason


def test_plan_chunker_stays_explore_when_contradiction_is_high():
    from agents.arc3.hypothesis import StateGraph, StateNode
    from agents.arc3.solver import PlanChunker, VictoryCondition, VictoryType

    graph = StateGraph()
    graph.add_state(StateNode("h1", 1, {}, 1.0, []))
    vc = VictoryCondition(condition_type=VictoryType.REACH_GOAL, description="reach exit")
    chunker = PlanChunker()
    object_roles = {
        1: ObjectRole(
            color_id=1,
            role=RoleType.PLAYER,
            confidence=0.92,
            estimated_position={"row": 4.0, "col": 2.0},
        ),
        9: ObjectRole(
            color_id=9,
            role=RoleType.GOAL,
            confidence=0.88,
            estimated_position={"row": 1.0, "col": 2.0},
        ),
    }
    hypothesis_context = {
        "action_coverage": {
            "initial_exploration_complete": True,
            "tested_count": 6,
            "untested_count": 0,
            "top_two_low_value": True,
        },
        "action_facts": [
            {"fact_type": "deterministic_effect", "value_status": "valuable"},
        ],
        "path_hypotheses": [
            {"value_status": "valuable"},
        ],
        "loop_detected": True,
    }

    chunk = chunker.generate_chunk(
        victory_condition=vc,
        object_roles=object_roles,
        state_graph=graph,
        current_hash="h1",
        available_actions=["ACTION1", "ACTION2", "ACTION3", "ACTION4", "ACTION5", "ACTION6"],
        step=7,
        hypothesis_context=hypothesis_context,
    )

    assert chunk.source == "explore"
    assert "loop detected" in chunk.graduation_reason
    assert chunk.graduation_score < chunker.GRADUATION_THRESHOLD


@pytest.mark.asyncio
async def test_solve_engine_strategy_summary_surfaces_graduation_reason():
    from agents.arc3.solver import SolveEngine, VictoryCondition, VictoryType, ObjectRole

    brain = AsyncMock()
    brain.recall_plans.return_value = {"plans": []}
    brain.recall_relevant_lessons.return_value = {"lessons": []}
    brain.analogical_search.return_value = {"results": []}
    brain.register_plan.return_value = {"plan_id": "p-summary"}
    brain.report_outcome.return_value = {"status": "ok"}

    llm = AsyncMock()
    llm.achat.return_value = '{"condition_type":"reach_goal","description":"reach exit","target_color_id":null,"confidence":0.5}'

    engine = SolveEngine(brain, llm, "s1")
    engine._victory_condition = VictoryCondition(
        condition_type=VictoryType.REACH_GOAL, confidence=0.9, description="reach exit"
    )
    engine._archetype_confidence = 0.8
    engine._object_roles = {
        1: ObjectRole(
            color_id=1,
            role=RoleType.PLAYER,
            confidence=0.9,
            estimated_position={"row": 4.0, "col": 2.0},
        ),
        9: ObjectRole(
            color_id=9,
            role=RoleType.GOAL,
            confidence=0.86,
            estimated_position={"row": 1.0, "col": 2.0},
        ),
    }
    engine.role_mapper.update = MagicMock(return_value={})

    from agents.arc3.hypothesis import StateGraph

    graph = StateGraph()
    ctx = {
        "last_transition_effect": {"meaningful_change_score": 0.8, "reward_signal": 0.0},
        "action_facts": [
            {"fact_type": "deterministic_effect", "value_status": "valuable"},
        ],
        "hud_rows": [],
        "path_hypotheses": [
            {"value_status": "valuable"},
        ],
        "action_coverage": {
            "initial_exploration_complete": True,
            "tested_count": 6,
            "untested_count": 0,
        },
        "current_state_hash": "h1",
    }
    obs = {
        "colors": [{"value": 1, "count": 1}, {"value": 9, "count": 1}],
        "available_actions": ["ACTION1", "ACTION2", "ACTION3", "ACTION4", "ACTION5", "ACTION6"],
        "task_id": "t1",
        "dataset_id": "d1",
        "grid": [[0, 0], [0, 1]],
    }

    result = await engine.solve(obs, ctx, step=8, state_graph=graph, current_state_hash="h1")

    assert "GRADUATION:" in result.strategy_summary
    assert "graduate directional" in result.strategy_summary
    assert result.active_chunk is not None
    assert result.active_chunk.graduation_reason


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
async def test_solve_engine_orchestrates_analogy_retrieval():
    from agents.arc3.solver import SolveEngine, PlanChunk, VictoryCondition, VictoryType

    brain = AsyncMock()
    brain.register_plan.return_value = {"plan_id": "p-new"}
    brain.recall_plans.return_value = {"plans": []}
    brain.recall_relevant_lessons.return_value = {"lessons": []}
    brain.analogical_search.return_value = {"results": [{"text_raw": "chase", "similarity": 0.8}]}
    brain.report_outcome.return_value = {"status": "ok"}

    llm = AsyncMock()
    llm.achat.return_value = '{"condition_type":"reach_goal","description":"reach exit","target_color_id":null,"confidence":0.5}'

    engine = SolveEngine(brain, llm, "s1")
    engine.archetype_classifier.update = MagicMock(return_value=(GameArchetype.CHASE, 0.4))
    engine._archetype = GameArchetype.CHASE
    engine._archetype_confidence = 0.4
    engine._archetype_locked = False
    engine._victory_condition = VictoryCondition(
        condition_type=VictoryType.REACH_GOAL, confidence=0.6, description="reach exit"
    )
    engine._active_chunk = PlanChunk(description="existing chunk", progress_score=0.0)
    engine._chunk_plan_id = "p-existing"

    from agents.arc3.hypothesis import StateGraph
    graph = StateGraph()
    ctx = {
        "last_transition_effect": {"meaningful_change_score": 0.0, "reward_signal": 0.0},
        "action_facts": [],
        "hud_rows": [],
        "path_hypotheses": [],
        "current_state_hash": "h1",
    }
    obs = {"colors": [], "available_actions": ["ACTION1"], "task_id": "t1", "dataset_id": "d1"}

    await engine.solve(obs, ctx, step=5, state_graph=graph, current_state_hash="h1")

    brain.analogical_search.assert_called_once()
    assert brain.analogical_search.call_args.kwargs["current_quest_id"] == "t1"


@pytest.mark.asyncio
async def test_solve_engine_defers_victory_hypothesis_below_threshold():
    from agents.arc3.solver import SolveEngine
    from agents.arc3.hypothesis import StateGraph

    brain = AsyncMock()
    brain.recall_plans.return_value = {"plans": []}
    brain.recall_relevant_lessons.return_value = {"lessons": []}
    brain.analogical_search.return_value = {"results": []}
    brain.register_plan.return_value = {"plan_id": "p-threshold"}
    brain.report_outcome.return_value = {"status": "ok"}

    llm = AsyncMock()
    llm.achat.return_value = '{"condition_type":"reach_goal","description":"reach exit","target_color_id":null,"confidence":0.5}'

    engine = SolveEngine(brain, llm, "s1")
    engine.archetype_classifier.update = MagicMock(return_value=(GameArchetype.CHASE, 0.6))
    engine._archetype = GameArchetype.CHASE
    engine._archetype_confidence = 0.6
    engine._archetype_locked = False

    obs = {"colors": [], "available_actions": ["ACTION1"], "task_id": "t1", "dataset_id": "d1"}
    ctx = {
        "last_transition_effect": {"meaningful_change_score": 0.0, "reward_signal": 0.0},
        "action_facts": [],
        "hud_rows": [],
        "path_hypotheses": [],
        "current_state_hash": "h1",
    }

    result = await engine.solve(obs, ctx, step=5, state_graph=StateGraph(), current_state_hash="h1")

    brain.recall_plans.assert_not_called()
    brain.recall_relevant_lessons.assert_not_called()
    llm.achat.assert_not_called()
    assert result.victory_condition is None


@pytest.mark.asyncio
async def test_solve_engine_passes_trend_evidence_to_role_mapping():
    from agents.arc3.solver import SolveEngine, PlanChunk, VictoryCondition, VictoryType, ObjectRole

    brain = AsyncMock()
    brain.recall_plans.return_value = {"plans": []}
    brain.recall_relevant_lessons.return_value = {"lessons": []}
    brain.analogical_search.return_value = {"results": []}
    brain.register_plan.return_value = {"plan_id": "p-role"}
    brain.report_outcome.return_value = {"status": "ok"}

    llm = AsyncMock()
    llm.achat.return_value = '{"condition_type":"reach_goal","description":"reach exit","target_color_id":null,"confidence":0.5}'

    engine = SolveEngine(brain, llm, "s1")
    engine._victory_condition = VictoryCondition(
        condition_type=VictoryType.REACH_GOAL, confidence=0.9, description="reach exit"
    )
    engine._active_chunk = PlanChunk(description="follow evidence", progress_score=0.0)
    engine._chunk_plan_id = "p-role"

    captured = {}

    def fake_role_mapper(hypothesis_context, observation, step):
        captured["action_facts"] = hypothesis_context.get("action_facts", [])
        return {
            7: ObjectRole(
                color_id=7,
                role=RoleType.PLAYER,
                confidence=0.8,
                evidence_steps=[step],
                estimated_position={"row": 4.0, "col": 2.0},
            )
        }

    engine.role_mapper.update = MagicMock(side_effect=fake_role_mapper)

    from agents.arc3.hypothesis import StateGraph
    graph = StateGraph()
    ctx = {
        "last_transition_effect": {"meaningful_change_score": 0.6, "reward_signal": 0.0},
        "action_facts": [
            {
                "action": "ACTION1",
                "trend": {
                    "kind": "directional_drift",
                    "axis": "col",
                    "direction": "left",
                    "avg_delta": 1.5,
                    "samples": 2,
                    "stable_region": False,
                },
            }
        ],
        "hud_rows": [],
        "path_hypotheses": [],
        "current_state_hash": "h1",
    }
    obs = {
        "colors": [{"value": 7, "count": 1}],
        "available_actions": ["ACTION1"],
        "task_id": "t1",
        "dataset_id": "d1",
        "grid": [[0, 0], [0, 7]],
    }

    result = await engine.solve(obs, ctx, step=6, state_graph=graph, current_state_hash="h1")

    assert captured["action_facts"][0]["trend"]["direction"] == "left"
    assert result.object_roles[7].role == RoleType.PLAYER
    assert result.object_roles[7].estimated_position == {"row": 4.0, "col": 2.0}


@pytest.mark.asyncio
async def test_solve_engine_preserves_player_against_later_goal_flip():
    from agents.arc3.solver import SolveEngine, PlanChunk, VictoryCondition, VictoryType
    from agents.arc3.hypothesis import StateGraph

    brain = AsyncMock()
    brain.recall_plans.return_value = {"plans": []}
    brain.recall_relevant_lessons.return_value = {"lessons": []}
    brain.analogical_search.return_value = {"results": []}
    brain.register_plan.return_value = {"plan_id": "p-player"}
    brain.report_outcome.return_value = {"status": "ok"}

    llm = AsyncMock()
    llm.achat.return_value = '{"condition_type":"reach_goal","description":"reach exit","target_color_id":null,"confidence":0.5}'

    engine = SolveEngine(brain, llm, "s1")
    engine._victory_condition = VictoryCondition(
        condition_type=VictoryType.REACH_GOAL, confidence=0.8, description="reach exit"
    )
    engine._solve_plan_id = "p-player"
    engine._active_chunk = PlanChunk(description="follow evidence", source="explore")
    engine._object_roles = {
        15: ObjectRole(
            color_id=15,
            role=RoleType.PLAYER,
            confidence=0.72,
            evidence_steps=[2],
            estimated_position={"row": 2.0, "col": 1.0},
        )
    }
    engine.role_mapper.update = MagicMock(
        return_value={
            15: ObjectRole(
                color_id=15,
                role=RoleType.GOAL,
                confidence=0.95,
                evidence_steps=[9],
                estimated_position={"row": 2.0, "col": 1.0},
            )
        }
    )

    obs = {
        "colors": [{"value": 15, "count": 1}],
        "available_actions": ["ACTION1", "ACTION2"],
        "task_id": "t1",
        "dataset_id": "d1",
        "grid": [[0, 15], [0, 0]],
    }
    ctx = {
        "last_transition_effect": {"meaningful_change_score": 0.2, "reward_signal": 0.0},
        "action_facts": [],
        "hud_rows": [],
        "path_hypotheses": [],
        "current_state_hash": "h1",
    }

    result = await engine.solve(obs, ctx, step=10, state_graph=StateGraph(), current_state_hash="h1")

    assert result.object_roles[15].role == RoleType.PLAYER
    assert "rejected goal flip" in result.strategy_summary
    assert "PRIMARY ROLES: player=15" in result.strategy_summary


@pytest.mark.asyncio
async def test_solve_engine_replaces_stale_goal_with_stronger_new_goal():
    from agents.arc3.solver import SolveEngine, PlanChunk, VictoryCondition, VictoryType
    from agents.arc3.hypothesis import StateGraph

    brain = AsyncMock()
    brain.recall_plans.return_value = {"plans": []}
    brain.recall_relevant_lessons.return_value = {"lessons": []}
    brain.analogical_search.return_value = {"results": []}
    brain.register_plan.return_value = {"plan_id": "p-goal"}
    brain.report_outcome.return_value = {"status": "ok"}

    llm = AsyncMock()
    llm.achat.return_value = '{"condition_type":"reach_goal","description":"reach exit","target_color_id":null,"confidence":0.5}'

    engine = SolveEngine(brain, llm, "s1")
    engine._victory_condition = VictoryCondition(
        condition_type=VictoryType.REACH_GOAL, confidence=0.8, description="reach exit"
    )
    engine._solve_plan_id = "p-goal"
    engine._active_chunk = PlanChunk(description="follow evidence", source="explore")
    engine._object_roles = {
        15: ObjectRole(
            color_id=15,
            role=RoleType.PLAYER,
            confidence=0.86,
            evidence_steps=[2],
            estimated_position={"row": 2.0, "col": 1.0},
        ),
        9: ObjectRole(
            color_id=9,
            role=RoleType.GOAL,
            confidence=0.58,
            evidence_steps=[2],
            estimated_position={"row": 1.0, "col": 1.0},
        ),
    }
    engine.role_mapper.update = MagicMock(
        return_value={
            12: ObjectRole(
                color_id=12,
                role=RoleType.GOAL,
                confidence=0.93,
                evidence_steps=[9],
                estimated_position={"row": 0.0, "col": 1.0},
            )
        }
    )

    obs = {
        "colors": [{"value": 15, "count": 1}, {"value": 9, "count": 1}, {"value": 12, "count": 1}],
        "available_actions": ["ACTION1", "ACTION2"],
        "task_id": "t1",
        "dataset_id": "d1",
        "grid": [[0, 15], [9, 12]],
    }
    ctx = {
        "last_transition_effect": {"meaningful_change_score": 0.2, "reward_signal": 0.0},
        "action_facts": [],
        "hud_rows": [],
        "path_hypotheses": [],
        "current_state_hash": "h1",
    }

    result = await engine.solve(obs, ctx, step=11, state_graph=StateGraph(), current_state_hash="h1")

    assert result.object_roles[12].role == RoleType.GOAL
    assert result.object_roles[9].role == RoleType.DECORATION
    assert "demoted stale goal" in result.strategy_summary
    assert "PRIMARY ROLES: player=15, goal=12" in result.strategy_summary


def test_merge_persistent_roles_enforces_single_primary_player_and_goal():
    engine = SolveEngine(AsyncMock(), AsyncMock(), "s1")
    engine._object_roles = {
        2: ObjectRole(color_id=2, role=RoleType.GOAL, confidence=0.61, evidence_steps=[1]),
        7: ObjectRole(color_id=7, role=RoleType.GOAL, confidence=0.88, evidence_steps=[2]),
        11: ObjectRole(color_id=11, role=RoleType.PLAYER, confidence=0.84, evidence_steps=[1]),
        12: ObjectRole(color_id=12, role=RoleType.PLAYER, confidence=0.79, evidence_steps=[2]),
    }

    notes = engine._merge_persistent_roles({}, step=3)

    assert sum(1 for role in engine._object_roles.values() if role.role == RoleType.PLAYER) == 1
    assert sum(1 for role in engine._object_roles.values() if role.role == RoleType.GOAL) == 1
    assert engine._object_roles[7].role == RoleType.GOAL
    assert engine._object_roles[2].role == RoleType.DECORATION
    assert engine._object_roles[11].role == RoleType.PLAYER
    assert engine._object_roles[12].role == RoleType.DECORATION
    assert any("demoted stale goal" in note for note in notes)


def test_strategy_summary_reports_role_resolution_notes_and_primary_ids():
    from agents.arc3.solver import PlanChunk

    engine = SolveEngine(AsyncMock(), AsyncMock(), "s1")
    engine._archetype = GameArchetype.CHASE
    engine._archetype_confidence = 0.7
    engine._victory_condition = VictoryCondition(
        condition_type=VictoryType.REACH_GOAL, confidence=0.9, description="reach exit"
    )
    engine._object_roles = {
        15: ObjectRole(color_id=15, role=RoleType.PLAYER, confidence=0.82),
        9: ObjectRole(color_id=9, role=RoleType.GOAL, confidence=0.91),
        3: ObjectRole(color_id=3, role=RoleType.DECORATION, confidence=0.4),
    }
    engine._active_chunk = PlanChunk(
        description="follow evidence",
        source="directional",
        progress_score=0.4,
        graduation_reason="graduate directional: score=0.81 >= 0.72",
        graduation_score=0.81,
    )
    engine._role_resolution_notes = ["step 10: kept player at color_15; rejected goal flip"]

    summary = engine._build_strategy_summary()

    assert "PRIMARY ROLES: player=15, goal=9" in summary
    assert "ROLE RESOLUTION: step 10: kept player at color_15; rejected goal flip" in summary
    assert "GRADUATION:" in summary


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
    llm.achat.return_value = '{"condition_type":"reach_goal","description":"reach exit","target_color_id":null,"confidence":0.5}'

    engine = SolveEngine(brain, llm, "s1")
    engine._archetype = GameArchetype.CHASE
    engine._archetype_confidence = 0.7
    engine._archetype_locked = True
    engine._victory_condition = VictoryCondition(
        condition_type=VictoryType.REACH_GOAL, confidence=0.6, description="reach exit"
    )
    engine._active_chunk = PlanChunk(description="stalled chunk", progress_score=0.0)
    engine._chunk_plan_id = "p-stall"
    engine.dissonance_detector._zero_progress_streak = 10

    from agents.arc3.hypothesis import StateGraph
    graph = StateGraph()
    ctx = {
        "last_transition_effect": {"meaningful_change_score": 0.0, "reward_signal": 0.0},
        "action_facts": [],
        "hud_rows": [],
        "path_hypotheses": [],
        "current_state_hash": "h1",
    }
    obs = {"colors": [], "available_actions": ["ACTION1"], "task_id": "t1", "dataset_id": "d1"}

    await engine.solve(obs, ctx, step=20, state_graph=graph, current_state_hash="h1")

    brain.report_outcome.assert_called_once()
    call_kwargs = brain.report_outcome.call_args.kwargs
    assert call_kwargs["valence"] < 0
    assert call_kwargs["plan_id"] == "p-stall"
