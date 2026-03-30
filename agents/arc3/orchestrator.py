"""ARC-AGI-3 orchestrator wrapping the local LLM with SideQuests intelligence."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List

from benchmarks.arc3.adapter import BrainClientProtocol
from benchmarks.arc3.schema import ARC3Action, ARC3Observation
from benchmarks.arc3.state_serializer import StateSerializerForARC
from agents.arc3.hypothesis import HypothesisManager

logger = logging.getLogger(__name__)


class ARCOrchestrator:
    """Perceive → plan → act → evaluate loop powered by SideQuests."""

    def __init__(
        self,
        brain_client: BrainClientProtocol,
        llm_client: Any,
        session_id: str,
        serializer: StateSerializerForARC,
        config: dict,
    ):
        self.brain = brain_client
        self.llm = llm_client
        self.session_id = session_id
        self.serializer = serializer
        self.config = config
        self._plan_id: str | None = None
        self._reflex_context: dict | None = None
        self._plan_steps: List[str] = []
        self._step_history: List[dict] = []
        self.hypothesis_mgr = HypothesisManager(brain_client, session_id)
        self._hypothesis_context: dict | None = None

    # ── Phase 1: Perceive ───────────────────────────────────────────────

    async def perceive(self, observation: ARC3Observation) -> dict:
        """Ingest puzzle structure into SideQuests then consult memory."""
        # Feed puzzle structure into SideQuests (raw → short-term → entities via consolidation)
        structure_summary = self._summarize_puzzle_structure(observation)
        await self.brain.notify_turn(
            role="user", content=structure_summary, session_id=self.session_id
        )

        query = self._memory_query(observation)
        truth = await self.brain.current_truth(
            query=query, session_id=self.session_id, scope="branch", limit=5
        )
        lessons = await self.brain.recall_relevant_lessons(query=query, limit=4)
        analogies = await self.brain.analogical_search(
            query=query,
            current_quest_id=observation.get("dataset_id", ""),
            limit=3,
            min_similarity=0.35,
        )
        return {
            "memories": truth.get("results", []),
            "lessons": lessons.get("lessons", []),
            "analogies": analogies.get("results", []),
            "query": query,
        }

    # ── Phase 2: Plan ───────────────────────────────────────────────────

    async def hypothesize(
        self,
        observation: ARC3Observation,
        action_taken: str | None,
        step: int,
    ) -> dict:
        """Update state graph, generate/update hypotheses, detect invariants.

        Called after every action, before the next plan/act decision.
        Returns hypothesis context for prompt construction.
        """
        available = observation.get("available_actions") or [f"ACTION{i}" for i in range(1, 8)]
        context = self.hypothesis_mgr.observe(
            grid=observation["grid"],
            action_taken=action_taken,
            step=step,
            available_actions=available,
            observation=observation,
        )

        # Override energy estimate with hypothesis-driven value if available
        hud_energy = context.get("energy_from_hud")
        if hud_energy is not None:
            observation["energy_estimate"] = hud_energy

        self._hypothesis_context = context
        return context

    async def plan(self, observation: ARC3Observation, memory_context: dict) -> dict:
        """Declare a plan and capture Amygdala Reflex context."""
        goal = f"Solve ARC task {observation['dataset_id']}:{observation['task_id']}"
        recall = await self.brain.recall_plans(
            goal_query=goal, session_id=self.session_id, min_valence=0.0, limit=3
        )
        self._plan_steps = self._draft_plan_steps(
            observation, memory_context, recall, self._hypothesis_context
        )
        plan_payload = await self.brain.register_plan(
            goal=goal, steps=self._plan_steps, session_id=self.session_id
        )
        self._plan_id = plan_payload.get("plan_id")
        self._reflex_context = plan_payload
        memory_context["similar_plans"] = recall.get("plans", [])
        return plan_payload

    # ── Phase 3: Act ───────────────────────────────────────────────────

    async def act(
        self,
        observation: ARC3Observation,
        memory_context: dict,
        step_num: int,
    ) -> ARC3Action:
        """Choose an action using integrated memory, reflex, and plan context."""
        if step_num > 3:
            await self.brain.current_truth(
                query="Am I looping?", session_id=self.session_id, scope="branch", limit=3
            )
        narrative = f"Step {step_num} observation: state={observation.get('state', 'UNKNOWN')} colors={observation['colors']} shapes={observation['shapes']}"
        await self.brain.notify_turn(role="user", content=narrative, session_id=self.session_id)

        available_actions = observation.get("available_actions") or [f"ACTION{i}" for i in range(1, 8)]
        prompt = self.build_action_prompt(
            observation=observation,
            memory_context=memory_context,
            step_history=self._step_history,
            available_actions=available_actions,
        )
        action = await self._query_llm(prompt, available_actions)
        self._step_history.append({
            "step": len(self._step_history) + 1,
            "action_id": action.get("action_id"),
            "rationale": action.get("rationale"),
            "reward": None,
            "done": False,
        })
        return action

    # ── Phase 4: Evaluate ──────────────────────────────────────────────

    async def evaluate(
        self,
        correct: bool,
        steps_taken: int,
        max_steps: int,
        final_observation: ARC3Observation,
    ) -> dict:
        """Report outcome and trigger valence propagation."""
        valence = self.reward_to_valence(correct, steps_taken, max_steps)
        payload = {
            "plan_id": self._plan_id,
            "outcome": "correct" if correct else "failed",
            "valence": valence,
            "session_id": self.session_id,
        }
        if self._plan_id:
            await self.brain.report_outcome(**payload)
        narrative = (
            f"Final observation for {final_observation['task_id']}: "
            f"correct={correct}, steps={steps_taken}, valence={valence:.2f}"
        )
        await self.brain.notify_turn(role="assistant", content=narrative, session_id=self.session_id)
        return {"valence": valence}

    # ── Prompt Construction ──────────────────────────────────────────

    def build_action_prompt(
        self,
        observation: ARC3Observation,
        memory_context: dict,
        step_history: List[dict],
        available_actions: List[str],
    ) -> str:
        """Structured prompt that wires SideQuests memory into the local LLM."""
        sections: List[str] = []
        sections.append(
            f"SYSTEM: You are an ARC puzzle solver. Available actions: {', '.join(available_actions)}."
        )

        state = observation.get("state", "UNKNOWN")
        energy = observation.get("energy_estimate", 1.0)
        sections.append(f"STATE: {state}  ENERGY: {energy:.0%}")

        memory_lines = self._format_memory_section(memory_context)
        if memory_lines:
            sections.append("MEMORY:\n" + "\n".join(memory_lines))

        hyp_lines = self._format_hypothesis_section(self._hypothesis_context)
        if hyp_lines:
            sections.append("HYPOTHESIS:\n" + "\n".join(hyp_lines))

        reflex_lines = self._format_reflex_section()
        if reflex_lines:
            sections.append("REFLEX:\n" + "\n".join(reflex_lines))

        plan_lines = self._format_plan_section()
        sections.append("PLAN:\n" + "\n".join(plan_lines))

        history_text = self._format_history_section(step_history)
        sections.append("HISTORY:\n" + history_text)

        sections.append("OBSERVATION:\n" + json.dumps(observation["grid"]))

        sections.append(
            "INSTRUCTION: Choose an action. Respond with JSON {\"action_id\":..., \"rationale\":...}."
        )
        return "\n\n".join(sections)

    @staticmethod
    def reward_to_valence(correct: bool, steps: int, max_steps: int) -> float:
        """Map ARC result → valence [-1.0, +1.0]."""
        if not correct:
            if steps >= max_steps:
                return -0.5
            return -0.7
        ratio = 1.0 - (steps - 1) / max(max_steps - 1, 1)
        return 0.3 + 0.7 * ratio

    # ------------------------------------------------------------------

    async def _query_llm(self, prompt: str, available_actions: List[str]) -> ARC3Action:
        if not self.llm:
            return {"action_id": available_actions[0], "rationale": "system fallback"}
        messages = [
            {"role": "system", "content": "You are an ARC reasoning assistant."},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = await asyncio.to_thread(self.llm.chat, messages)
            parsed = json.loads(raw)
            return parsed
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("LLM action parse failed: %s", exc)
            return {"action_id": available_actions[0], "rationale": "fallback"}

    def _memory_query(self, observation: ARC3Observation) -> str:
        colors = ", ".join(str(s["value"]) for s in observation.get("colors", []))
        shapes = len(observation.get("shapes", []))
        state = observation.get("state", "UNKNOWN")
        available = observation.get("available_actions", [])
        energy = observation.get("energy_estimate", 1.0)
        return (
            f"ARC task {observation['task_id']} has colors {colors} and {shapes} shapes. "
            f"State is {state}. Energy: {energy:.0%}. "
            f"Available actions: {', '.join(available) if available else 'all'}."
        )

    def _draft_plan_steps(
        self,
        observation: ARC3Observation,
        memory_context: dict,
        recall: dict,
        hypothesis_context: dict | None = None,
    ) -> List[str]:
        steps = []
        # Use hypothesis-informed steps instead of static template
        if hypothesis_context:
            confirmed = hypothesis_context.get("confirmed_hypotheses", [])
            unexplored = hypothesis_context.get("unexplored_actions", [])
            policy = hypothesis_context.get("explore_vs_exploit", "explore")

            if policy == "explore" and unexplored:
                steps.append(f"Explore untested actions: {', '.join(unexplored[:3])}")
            for h in confirmed[:2]:
                steps.append(f"Exploit confirmed rule: {h['description']}")
            if hypothesis_context.get("loop_detected"):
                steps.append("BREAK LOOP: avoid the action sequence that returned to a visited state")
        else:
            steps.append("Survey the grid to understand dominant colors and shapes.")
            steps.append("Compare the pattern to lessons and analogies retrieved.")
            steps.append("Apply targeted ACTION commands to drive toward the goal.")

        for plan in recall.get("plans", [])[:2]:
            steps.append(f"Learn from {plan.get('goal')} (valence {plan.get('valence')})")
        return steps

    def _format_hypothesis_section(self, hyp_ctx: dict | None) -> List[str]:
        if not hyp_ctx:
            return []
        lines = []
        if hyp_ctx.get("loop_detected"):
            lines.append(f"⚠ LOOP DETECTED — revisited state {hyp_ctx.get('loop_hash', '')[:8]}. Change strategy.")
        for h in hyp_ctx.get("confirmed_hypotheses", [])[:3]:
            lines.append(f"CONFIRMED ({h['confidence']:.0%}): {h['description']}")
        for h in hyp_ctx.get("active_hypotheses", [])[:3]:
            lines.append(f"TESTING ({h['confidence']:.0%}): {h['description']}")
        unexplored = hyp_ctx.get("unexplored_actions", [])
        if unexplored:
            lines.append(f"Untested actions from this state: {', '.join(unexplored)}")
        lines.append(f"Policy: {hyp_ctx.get('explore_vs_exploit', 'explore').upper()}")
        return lines

    def _format_memory_section(self, memory_context: dict) -> List[str]:
        lines: List[str] = []
        for lesson in memory_context.get("lessons", []):
            lines.append(f"Lesson: {lesson.get('text', '')}")
        for memory in memory_context.get("memories", []):
            lines.append(f"Memory: {memory}")
        for analogy in memory_context.get("analogies", []):
            lines.append(f"Analogy: {analogy.get('text_raw', analogy)}")
        return lines

    def _format_reflex_section(self) -> List[str]:
        lines: List[str] = []
        if not self._reflex_context:
            return lines
        for warning in self._reflex_context.get("warnings", []):
            lines.append(f"WARNING: {warning}")
        for suggestion in self._reflex_context.get("suggestions", []):
            lines.append(f"GOLDEN PATH: {suggestion}")
        return lines

    def _format_plan_section(self) -> List[str]:
        if not self._plan_steps:
            return ["Plan: no steps yet."]
        return [f"Step {idx + 1}: {step}" for idx, step in enumerate(self._plan_steps)]

    def _format_history_section(self, history: List[dict]) -> str:
        if not history:
            return "No steps taken yet."
        entries = []
        for record in history:
            reward = record.get("reward")
            reward_text = f"reward {reward:.2f}" if isinstance(reward, float) else "reward pending"
            entries.append(
                f"Step {record['step']} → {record.get('action_id')} ({record.get('rationale')}) · {reward_text}"
            )
        return "\n".join(entries)

    # ------------------------------------------------------------------

    def record_step_result(self, reward: float, done: bool) -> None:
        if not self._step_history:
            return
        record = self._step_history[-1]
        record["reward"] = reward
        record["done"] = done

    def reset_for_retry(self, attempt: int) -> None:
        """Reset internal state for a retry attempt while preserving history.

        The step_history is kept so the Amygdala Reflex can see what was
        already tried.  The plan is cleared so a new register_plan call
        triggers fresh similarity checks against the now-failed plan.
        """
        self._plan_id = None
        self._reflex_context = None
        self._plan_steps = []
        # Append a sentinel so the LLM prompt shows the GAME_OVER boundary
        self._step_history.append({
            "step": len(self._step_history) + 1,
            "action_id": "GAME_OVER",
            "rationale": f"Attempt {attempt} failed — resetting with new strategy",
            "reward": -1.0,
            "done": True,
        })
        self.hypothesis_mgr.reset_graph()

    def _summarize_puzzle_structure(self, observation: ARC3Observation) -> str:
        """Build a rich structural summary for SideQuests ingestion."""
        grid = observation.get("grid", [])
        rows = len(grid)
        cols = len(grid[0]) if grid else 0
        colors = observation.get("colors", [])
        shapes = observation.get("shapes", [])
        state = observation.get("state", "NOT_STARTED")
        available = observation.get("available_actions", [])
        energy = observation.get("energy_estimate", 1.0)
        color_desc = ", ".join(
            f"color {c['value']} ({c['count']} cells)" for c in colors[:6]
        ) if colors else "none detected"
        shape_desc = ", ".join(
            f"{s.get('type', 'unknown')} size {s.get('size', '?')}" for s in shapes[:6]
        ) if shapes else "none detected"
        return (
            f"[PUZZLE STRUCTURE] Task {observation['task_id']} from {observation['dataset_id']}. "
            f"Grid: {rows}x{cols}. State: {state}. Energy: {energy:.0%}. "
            f"Colors: {color_desc}. "
            f"Shapes ({len(shapes)}): {shape_desc}. "
            f"Available actions: {', '.join(available) if available else 'pending'}."
        )
