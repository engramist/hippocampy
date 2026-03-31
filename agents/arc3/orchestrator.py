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
from agents.arc3.solver import SolveEngine

logger = logging.getLogger(__name__)


class ARCOrchestrator:
    """Perceive → plan → act → evaluate loop powered by SideQuests."""

    MAX_PROMPT_LESSONS = 1
    MAX_PROMPT_MEMORIES = 1
    MAX_PROMPT_ANALOGIES = 1
    MAX_PROMPT_HISTORY = 2
    MAX_PROMPT_PLAN_STEPS = 2
    MAX_PROMPT_HYPOTHESES = 1
    MAX_PROMPT_ACTIONS = 4

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
        self._write_trace: List[dict] = []
        self._write_trace_context: str = "bootstrap"
        self.hypothesis_mgr = HypothesisManager(brain_client, session_id)
        self._hypothesis_context: dict | None = None
        self.solve_engine = SolveEngine(brain_client, llm_client, session_id)
        self._solve_context: dict | None = None
        # B89: Prompt budget metrics
        self._invalid_action_count = 0
        self._no_progress_step_count = 0
        self._prompt_tokens_per_step: List[int] = []
        self._retrieval_payloads: List[dict] = []
        self._first_prompt_detail_level = "unknown"
        self._asked_for_decision_from_effects = False
        # B90: Retrieval triggering
        self._retrieval_triggered = False
        self._last_retrieval_step = -1
        self._consecutive_no_progress_steps = 0
        self._memory_context: dict | None = None

    # ── Phase 1: Perceive ───────────────────────────────────────────────

    async def perceive(self, observation: ARC3Observation, step: int = 0) -> dict:
        """Ingest puzzle structure into SideQuests then optionally consult memory based on triggers."""
        # Feed puzzle structure into SideQuests (raw → short-term → entities via consolidation)
        structure_summary = self._summarize_puzzle_structure(observation)
        notify_response = await self.brain.notify_turn(
            role="user", content=structure_summary, session_id=self.session_id
        )
        self._record_write_event(
            kind="notify_turn",
            summary=structure_summary,
            detail={"role": "user", "scope": "structure_ingest"},
            response_dict=notify_response,
        )

        # B90: Check retrieval triggers to decide whether to fetch memory
        should_retrieve = self._should_trigger_retrieval(observation, step)
        self._retrieval_triggered = should_retrieve

        if should_retrieve:
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
            # B89: Track retrieval payload sizes
            retrieval_payload = {
                "memories_size": len(json.dumps(truth.get("results", []))),
                "lessons_size": len(json.dumps(lessons.get("lessons", []))),
                "analogies_size": len(json.dumps(analogies.get("results", []))),
                "total_size": 0,
            }
            retrieval_payload["total_size"] = (
                retrieval_payload["memories_size"]
                + retrieval_payload["lessons_size"]
                + retrieval_payload["analogies_size"]
            )
            self._retrieval_payloads.append(retrieval_payload)
            self._last_retrieval_step = step

            memory_context = {
                "memories": truth.get("results", []),
                "lessons": lessons.get("lessons", []),
                "analogies": analogies.get("results", []),
                "query": query,
                "_retrieval_payload_size": retrieval_payload["total_size"],
                "_triggered": True,
            }
        else:
            memory_context = {
                "memories": [],
                "lessons": [],
                "analogies": [],
                "query": "",
                "_retrieval_payload_size": 0,
                "_triggered": False,
            }

        self._memory_context = memory_context
        return memory_context

    # ── Phase 2: Plan ───────────────────────────────────────────────────

    async def hypothesize(
        self,
        observation: ARC3Observation,
        action_taken: str | None,
        step: int,
        transition_meta: dict | None = None,
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
            transition_meta=transition_meta,
        )

        # Override energy estimate with hypothesis-driven value if available
        hud_energy = context.get("energy_from_hud")
        if hud_energy is not None:
            observation["energy_estimate"] = hud_energy

        if context.get("last_transition_effect"):
            transition_effect = context["last_transition_effect"]
            action_facts = context.get("action_facts", [])
            path_hypotheses = context.get("path_hypotheses", [])
            top_fact = action_facts[0] if action_facts else None
            top_path = path_hypotheses[0] if path_hypotheses else None
            summary = (
                f"{transition_effect.get('action')} -> {transition_effect.get('meaningful_change_label')} "
                f"(score {transition_effect.get('meaningful_change_score', 0.0):.2f}); "
                f"facts={len(action_facts)} paths={len(path_hypotheses)}"
            )
            detail: dict[str, Any] = {
                "action": transition_effect.get("action"),
                "label": transition_effect.get("meaningful_change_label"),
                "score": transition_effect.get("meaningful_change_score"),
                "facts": len(action_facts),
                "paths": len(path_hypotheses),
                "saved_action_facts": self._compact_fact_trace(action_facts),
                "saved_path_hypotheses": self._compact_path_trace(path_hypotheses),
            }
            if top_fact:
                detail["top_fact"] = {
                    "action": top_fact.get("action"),
                    "fact_type": top_fact.get("fact_type"),
                    "value_status": top_fact.get("value_status"),
                }
            if top_path:
                detail["top_path"] = {
                    "actions": top_path.get("actions"),
                    "value_status": top_path.get("value_status"),
                }
            bottleneck = context.get("environment_bottleneck")
            if bottleneck:
                detail["environment_bottleneck"] = bottleneck
            self._record_write_event(
                kind="hypothesis_update",
                summary=summary,
                detail=detail,
                source_step=step,
            )

        self._hypothesis_context = context
        return context

    async def solve(
        self,
        observation: ARC3Observation,
        hypothesis_context: dict,
        step: int,
    ) -> dict:
        """Classify archetype, assign object roles, hypothesize victory condition, chunk plan."""
        current_hash = hypothesis_context.get("current_state_hash", "")
        solve_ctx = await self.solve_engine.solve(
            observation=observation,
            hypothesis_context=hypothesis_context,
            step=step,
            state_graph=self.hypothesis_mgr.graph,
            current_state_hash=current_hash,
        )
        self._solve_context = {
            "archetype": solve_ctx.archetype.value,
            "archetype_confidence": solve_ctx.archetype_confidence,
            "object_roles": {
                str(k): {"role": v.role.value, "confidence": v.confidence}
                for k, v in solve_ctx.object_roles.items()
            },
            "victory_condition": (
                {
                    "type": solve_ctx.victory_condition.condition_type.value,
                    "description": solve_ctx.victory_condition.description,
                    "confidence": solve_ctx.victory_condition.confidence,
                }
                if solve_ctx.victory_condition else None
            ),
            "active_chunk": (
                {
                    "description": solve_ctx.active_chunk.description,
                    "estimated_actions": solve_ctx.active_chunk.estimated_actions,
                    "progress": solve_ctx.active_chunk.progress_score,
                    "source": solve_ctx.active_chunk.source,
                }
                if solve_ctx.active_chunk else None
            ),
            "dissonance": solve_ctx.dissonance_detected,
            "dissonance_reason": solve_ctx.dissonance_reason,
            "strategy_summary": solve_ctx.strategy_summary,
        }
        return self._solve_context

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
        self._record_write_event(
            kind="register_plan",
            summary=f"registered plan {self._plan_id or 'unknown'} with {len(self._plan_steps)} step(s)",
            detail={
                "plan_id": self._plan_id,
                "steps": len(self._plan_steps),
            },
            response_dict=plan_payload,
        )
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
        notify_response = await self.brain.notify_turn(role="user", content=narrative, session_id=self.session_id)
        self._record_write_event(
            kind="notify_turn",
            summary=narrative,
            detail={"role": "user", "scope": "step_observation", "step": step_num},
            response_dict=notify_response,
            source_step=step_num,
        )

        available_actions = observation.get("available_actions") or [f"ACTION{i}" for i in range(1, 8)]
        prompt = self.build_action_prompt(
            observation=observation,
            memory_context=memory_context,
            step_history=self._step_history,
            available_actions=available_actions,
        )
        # B89: Estimate prompt tokens and track first-prompt detail level
        prompt_tokens = self.serializer._estimate_tokens(prompt)
        self._prompt_tokens_per_step.append(prompt_tokens)
        if not self._step_history:
            # This is the first prompt - determine detail level
            has_memory = "MEMORY:" in prompt
            has_facts = "ACTION FACTS:" in prompt
            has_effects = "OBSERVED EFFECTS:" in prompt
            self._first_prompt_detail_level = "rich" if (has_memory or has_facts or has_effects) else "compact"
        # Check if prompt asks for decision from observed effects
        if "OBSERVED EFFECTS:" in prompt and "INSTRUCTION:" in prompt:
            self._asked_for_decision_from_effects = "effect" in prompt.lower()

        action = await self._query_llm(prompt, available_actions)
        action = self._enforce_action_policy(action, available_actions)
        # B89: Track invalid actions
        action_id = action.get("action_id")
        if action_id not in available_actions:
            self._invalid_action_count += 1

        self._step_history.append({
            "step": len(self._step_history) + 1,
            "state_before": observation.get("state"),
            "board_before": self._snapshot_for_trace(observation),
            "available_actions": list(available_actions),
            "prompt": prompt,
            "action_id": action.get("action_id"),
            "rationale": action.get("rationale"),
            "reward": None,
            "done": False,
            "prompt_tokens": prompt_tokens,
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
            outcome_response = await self.brain.report_outcome(**payload)
            self._record_write_event(
                kind="report_outcome",
                summary=(
                    f"plan {self._plan_id} outcome={payload['outcome']} valence={valence:.2f}"
                ),
                detail={
                    "plan_id": self._plan_id,
                    "outcome": payload["outcome"],
                    "valence": round(valence, 2),
                },
                response_dict=outcome_response,
            )
        narrative = (
            f"Final observation for {final_observation['task_id']}: "
            f"correct={correct}, steps={steps_taken}, valence={valence:.2f}"
        )
        final_notify_response = await self.brain.notify_turn(role="assistant", content=narrative, session_id=self.session_id)
        self._record_write_event(
            kind="notify_turn",
            summary=narrative,
            detail={"role": "assistant", "scope": "final_narrative"},
            response_dict=final_notify_response,
        )
        return {"valence": valence}

    # ── Retrieval Trigger Logic ──────────────────────────────────────

    def _should_trigger_retrieval(self, observation: ARC3Observation, step: int) -> bool:
        """Determine if memory retrieval should be triggered based on puzzle state.

        Triggers:
        1. Initial puzzle bootstrapping (step == 0)
        2. Repeated no-progress steps (3+ consecutive)
        3. Fallback or invalid-action correction (invalid_action_count increased)
        4. Loop suspicion (loop_detected in hypothesis context)
        5. Evidence gap (no good action candidates in hypothesis context)
        """
        # Trigger 1: Initial puzzle bootstrapping
        if step == 0:
            return True

        # Trigger 2: Repeated no-progress steps (3+ consecutive)
        if self._no_progress_step_count >= 3 and step > self._last_retrieval_step:
            self._consecutive_no_progress_steps += 1
            if self._consecutive_no_progress_steps >= 3:
                self._consecutive_no_progress_steps = 0
                return True

        # Trigger 3: Invalid action correction (attempted invalid action)
        if self._invalid_action_count > 0 and step > self._last_retrieval_step:
            self._invalid_action_count = 0
            return True

        hyp_ctx = self._hypothesis_context or {}

        # Trigger 4: Loop suspicion
        if hyp_ctx.get("loop_detected"):
            return True

        # Trigger 5: Evidence gap - no clear action candidates
        observed_effects = hyp_ctx.get("observed_action_effects", [])
        action_coverage = hyp_ctx.get("action_coverage") or {}
        untested_count = action_coverage.get("untested_count", 0)
        tested_count = action_coverage.get("tested_count", 0)

        if tested_count > 2 and not observed_effects:
            # Tested multiple actions but no usable effects recorded
            return True

        # Trigger 6: All tested actions have decayed to low_value (top_two_low_value)
        if action_coverage.get("top_two_low_value"):
            return True

        return False

    # ── Prompt Construction ──────────────────────────────────────────

    def build_action_prompt(
        self,
        observation: ARC3Observation,
        memory_context: dict,
        step_history: List[dict],
        available_actions: List[str],
    ) -> str:
        """Structured prompt that wires SideQuests memory into the local LLM.

        B90: Prompt is smaller on no-trigger path; decision is effect-oriented.
        """
        sections: List[str] = []
        sections.append(
            "SYSTEM: You are an ARC puzzle solver. "
            "Treat action ids as opaque operators until this puzzle provides evidence about their effects. "
            f"Available actions: {', '.join(available_actions)}."
        )

        state = observation.get("state", "UNKNOWN")
        energy = observation.get("energy_estimate", 1.0)
        sections.append(f"STATE: {state}  ENERGY: {energy:.0%}")

        # B90: Include memory only if retrieval was triggered
        if memory_context.get("_triggered"):
            memory_lines = self._format_memory_section(memory_context, observation, is_first_decision=not step_history)
            if memory_lines:
                sections.append("MEMORY:\n" + "\n".join(memory_lines))

        fact_lines = self._format_action_fact_section(self._hypothesis_context)
        if fact_lines:
            sections.append("ACTION FACTS:\n" + "\n".join(fact_lines))

        hyp_lines = self._format_path_hypothesis_section(self._hypothesis_context)
        if hyp_lines:
            sections.append("PATH HYPOTHESES:\n" + "\n".join(hyp_lines))

        solve_section = self._build_solve_section()
        if solve_section:
            sections.append(solve_section)

        effect_lines = self._format_effect_section(self._hypothesis_context)
        if effect_lines:
            sections.append("OBSERVED EFFECTS:\n" + "\n".join(effect_lines))

        reflex_lines = self._format_reflex_section()
        if reflex_lines:
            sections.append("REFLEX:\n" + "\n".join(reflex_lines))

        plan_lines = self._format_plan_section()
        sections.append("PLAN:\n" + "\n".join(plan_lines))

        history_text = self._format_history_section(step_history)
        sections.append("HISTORY:\n" + history_text)

        sections.append("OBSERVATION:\n" + self._format_observation_section(observation))

        # B90: Effect-oriented instruction that foregrounds what changed and next decision
        last_effect = self._hypothesis_context.get("last_transition_effect") if self._hypothesis_context else None
        if last_effect:
            effect_summary = (
                f"Last action {last_effect.get('action')} caused "
                f"{last_effect.get('meaningful_change_label', 'unknown')} "
                f"(score {last_effect.get('meaningful_change_score', 0.0):.2f}). "
            )
        else:
            effect_summary = "No prior action effects recorded yet. "

        instruction = (
            f"INSTRUCTION: {effect_summary}"
            "What should you try next? "
            "Choose the next valid action based on observed effects. "
            "Start in an exploration phase: until each available action has at least one observed effect, prefer untested actions. "
            "Prefer actions with strong_progress or tentative_progress evidence. "
            "Treat no_progress evidence as a reason to switch actions unless reward improved. "
            "Use an UNTESTED action when repeated actions are low-value or looped. "
            "If the top tested actions both decay into low_value or no_progress, broaden exploration instead of bouncing between them. "
            "After 2 consecutive zero-reward tentative steps on the same action, require stronger evidence than before or switch. "
            "Do not let a memory-only first move override the current observation unless the memory clearly matches this puzzle. "
            "Do not invent human labels for actions beyond the observed effects. "
            "Respond with JSON {\"action_id\":..., \"rationale\":...}, and make the rationale cite one observed effect label or say UNTESTED."
        )
        sections.append(instruction)
        return "\n\n".join(sections)

    def set_write_trace_context(self, context: str) -> None:
        self._write_trace_context = context or "bootstrap"

    def consume_write_trace(self) -> List[dict]:
        trace = list(self._write_trace)
        self._write_trace.clear()
        return trace

    def _record_write_event(
        self,
        *,
        kind: str,
        summary: str,
        detail: dict | None = None,
        response_dict: dict | None = None,
        source_step: int | None = None,
    ) -> None:
        # Extract status from response dict, defaulting to "ok"
        status = "ok"
        if response_dict and isinstance(response_dict, dict):
            status = response_dict.get("status", "ok")

        event = {
            "phase": self._write_trace_context,
            "type": kind,
            "kind": kind,
            "status": status,
            "summary": self._compact_text(summary),
        }
        if source_step is not None:
            event["source_step"] = source_step
        if detail:
            event["detail"] = detail
        self._write_trace.append(event)

    @staticmethod
    def _compact_text(text: str, limit: int = 180) -> str:
        text = " ".join(str(text).split())
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    def _compact_fact_trace(self, facts: List[dict], limit: int = 3) -> List[dict]:
        compact: List[dict] = []
        for fact in facts[:limit]:
            compact.append(
                {
                    "id": fact.get("id"),
                    "action": fact.get("action"),
                    "fact_type": fact.get("fact_type"),
                    "value_status": fact.get("value_status"),
                    "consistency": fact.get("consistency"),
                    "evidence_count": fact.get("evidence_count"),
                    "trend": fact.get("trend"),
                    "support_steps": list(fact.get("support_steps") or [])[:4],
                    "description": self._compact_text(fact.get("description") or "", 140),
                }
            )
        return compact

    def _compact_path_trace(self, paths: List[dict], limit: int = 3) -> List[dict]:
        compact: List[dict] = []
        for path in paths[:limit]:
            compact.append(
                {
                    "actions": list(path.get("actions") or []),
                    "value_status": path.get("value_status"),
                    "confidence": path.get("confidence"),
                    "support_steps": list(path.get("support_steps") or [])[:4],
                    "description": self._compact_text(path.get("description") or "", 140),
                }
            )
        return compact

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
            if not isinstance(parsed, dict):
                raise ValueError(f"Expected dict action payload, got {type(parsed).__name__}")

            action_id = parsed.get("action_id")
            rationale = parsed.get("rationale") or "llm response missing rationale"
            if action_id not in available_actions:
                fallback = available_actions[0]
                logger.warning(
                    "LLM selected unavailable action %r; falling back to %r. Available=%s",
                    action_id,
                    fallback,
                    available_actions,
                )
                return {
                    "action_id": fallback,
                    "rationale": f"Invalid LLM action {action_id!r}; fallback to {fallback}. Original rationale: {rationale}",
                }

            return {
                "action_id": action_id,
                "rationale": rationale,
            }
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("LLM action parse failed: %s", exc)
            return {"action_id": available_actions[0], "rationale": "fallback"}

    def _enforce_action_policy(self, action: ARC3Action, available_actions: List[str]) -> ARC3Action:
        """Apply hard exploration guards when the prompt alone is not enough."""
        hyp_ctx = self._hypothesis_context or {}
        coverage = hyp_ctx.get("action_coverage") or {}
        unexplored = [
            candidate for candidate in coverage.get("untested_actions", [])
            if candidate in available_actions
        ]
        action_id = action.get("action_id")
        rationale = action.get("rationale") or ""

        if unexplored and action_id not in unexplored:
            forced = unexplored[0]
            return {
                "action_id": forced,
                "rationale": f"policy override: exploration phase requires testing {forced} before exploiting {action_id}. Original rationale: {rationale}",
            }

        ranked_effects = [
            effect for effect in hyp_ctx.get("observed_action_effects", [])
            if effect.get("action") in available_actions
        ]

        if coverage.get("initial_exploration_complete") and ranked_effects:
            preferred = self._select_ranked_action(ranked_effects)
            if preferred and action_id != preferred:
                return {
                    "action_id": preferred,
                    "rationale": f"policy override: post-exploration ranking prefers {preferred} over {action_id}. Original rationale: {rationale}",
                }

        return action

    def _select_ranked_action(self, ranked_effects: List[dict]) -> str | None:
        allowed = [
            effect for effect in ranked_effects
            if not effect.get("over_retest_budget")
        ]
        pool = allowed or ranked_effects
        if not pool:
            return None
        pool = sorted(
            pool,
            key=lambda effect: (
                -float(effect.get("rank_score", 0.0)),
                effect.get("times_seen", 0),
                effect.get("action", ""),
            ),
        )
        return pool[0].get("action")

    def _memory_query(self, observation: ARC3Observation) -> str:
        colors = ", ".join(str(s["value"]) for s in observation.get("colors", []))
        shapes = len(observation.get("shapes", []))
        state = observation.get("state", "UNKNOWN")
        available = observation.get("available_actions", [])
        energy = observation.get("energy_estimate", 1.0)
        spatial_signature = self._coarse_grid_summary(observation.get("grid", []), block_count=4)
        spatial_signature = spatial_signature.replace("\n", " / ") if spatial_signature else "(empty)"
        return (
            f"ARC task {observation['task_id']} has colors {colors} and {shapes} shapes. "
            f"Spatial signature: {spatial_signature}. "
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
        sc = self._solve_context

        if sc and sc.get("victory_condition"):
            vc = sc["victory_condition"]
            steps.append(f"Win condition: {vc['description']} (confidence={vc['confidence']:.2f})")
        else:
            steps.append("Explore game mechanics: test each action and observe effects")

        if sc and sc.get("active_chunk"):
            ch = sc["active_chunk"]
            steps.append(f"Execute chunk: {ch['description']}")
        else:
            steps.append("Gather more observations to identify game type")

        steps.append("Evaluate: did the action advance the win condition? Adjust if not.")

        for plan in recall.get("plans", [])[:2]:
            steps.append(f"Learn from {plan.get('goal')} (valence {plan.get('valence')})")
        return steps[:self.MAX_PROMPT_PLAN_STEPS]

    def _build_solve_section(self) -> str:
        sc = self._solve_context
        if not sc:
            return ""
        lines = ["=== SOLVE CONTEXT ==="]
        lines.append(f"ARCHETYPE: {sc['archetype']} (confidence={sc['archetype_confidence']:.2f})")

        roles = sc.get("object_roles") or {}
        if roles:
            lines.append("OBJECT ROLES:")
            for color_id, role_info in list(roles.items())[:5]:
                lines.append(f"  color_{color_id}: {role_info['role']} (conf={role_info['confidence']:.2f})")

        vc = sc.get("victory_condition")
        if vc:
            lines.append(f"VICTORY: {vc['type'].upper()} — {vc['description']} (conf={vc['confidence']:.2f})")

        chunk = sc.get("active_chunk")
        if chunk:
            lines.append(f"ACTIVE CHUNK: {chunk['description']} [{chunk['source']}]")
            if chunk.get("estimated_actions"):
                lines.append(f"  Suggested actions: {chunk['estimated_actions'][:6]}")
            lines.append(f"  Progress: {chunk['progress']:.2f}")

        if sc.get("dissonance"):
            lines.append(f"⚠ DISSONANCE: {sc['dissonance_reason']}")

        return "\n".join(lines)

    def _format_action_fact_section(self, hyp_ctx: dict | None) -> List[str]:
        if not hyp_ctx:
            return []
        lines = []
        for fact in hyp_ctx.get("action_facts", [])[: self.MAX_PROMPT_ACTIONS]:
            lines.append(
                f"{fact.get('action')}: {fact.get('fact_type', 'unknown').upper()} "
                f"(consistency {fact.get('consistency', 0.0):.2f}, value {fact.get('value_status', 'unknown')}, "
                f"evidence {fact.get('evidence_count', 0)}): {fact.get('description')}"
            )
        return lines

    def _format_path_hypothesis_section(self, hyp_ctx: dict | None) -> List[str]:
        if not hyp_ctx:
            return []
        lines = []
        if hyp_ctx.get("loop_detected"):
            lines.append(f"⚠ LOOP DETECTED — revisited state {hyp_ctx.get('loop_hash', '')[:8]}. Change strategy.")
        for h in hyp_ctx.get("path_hypotheses", [])[: self.MAX_PROMPT_HYPOTHESES]:
            lines.append(
                f"PATH {h.get('value_status', 'unknown').upper()} ({h.get('confidence', 0.0):.0%}): {h.get('description')}"
            )
        coverage = hyp_ctx.get("action_coverage") or {}
        if coverage:
            untested = coverage.get("untested_actions") or []
            if untested:
                lines.append(
                    "Currently available but unobserved actions: "
                    + ", ".join(untested[: self.MAX_PROMPT_ACTIONS])
                )
            lines.append(
                "Exploration coverage: "
                f"tested {coverage.get('tested_count', 0)}, "
                f"untested {coverage.get('untested_count', 0)}"
            )
            if coverage.get("top_two_low_value"):
                lines.append("Top tested actions have decayed to low_value; broaden exploration.")
        bottleneck = hyp_ctx.get("environment_bottleneck")
        if bottleneck:
            lines.append(f"⚠ {bottleneck.get('message')}")
        lines.append(f"Policy: {hyp_ctx.get('explore_vs_exploit', 'explore').upper()}")
        return lines

    def _format_effect_section(self, hyp_ctx: dict | None) -> List[str]:
        if not hyp_ctx:
            return []
        lines: List[str] = []
        last_effect = hyp_ctx.get("last_transition_effect")
        if last_effect:
            before_snapshot = last_effect.get("before_snapshot")
            after_snapshot = last_effect.get("after_snapshot")
            if before_snapshot and after_snapshot:
                lines.append(
                    f"Board transition: {str(last_effect.get('before_frame_hash', 'unknown'))[:8]} -> "
                    f"{str(last_effect.get('after_frame_hash', 'unknown'))[:8]}"
                )
                lines.append(
                    "Before board 4x4:\n"
                    + str(before_snapshot.get("coarse_map", "(empty)"))
                )
                lines.append(
                    "After board 4x4:\n"
                    + str(after_snapshot.get("coarse_map", "(empty)"))
                )
            changed_region = last_effect.get("changed_region") or {}
            if changed_region.get("row_range") and changed_region.get("col_range"):
                lines.append(
                    f"Changed region rows {changed_region['row_range'][0]}-{changed_region['row_range'][1]}, "
                    f"cols {changed_region['col_range'][0]}-{changed_region['col_range'][1]}"
                )
                lines.append(
                    "Changed region before:\n"
                    + str(changed_region.get("before_crop", "(empty)"))
                )
                lines.append(
                    "Changed region after:\n"
                    + str(changed_region.get("after_crop", "(empty)"))
                )
            lines.append(
                f"Last action {last_effect.get('action')}: "
                f"{last_effect.get('meaningful_change_label', 'unknown')} "
                f"(score {last_effect.get('meaningful_change_score', 0.0):.2f}, "
                f"reasons: {', '.join(last_effect.get('meaningful_change_reasons', [])) or 'none'}, "
                f"zero_reward_streak: {last_effect.get('zero_reward_streak', 0)}) :: "
                f"{last_effect.get('summary')}"
            )
        for effect in hyp_ctx.get("observed_action_effects", [])[: self.MAX_PROMPT_ACTIONS]:
            if effect.get("times_seen", 0) <= 0:
                lines.append(f"{effect.get('action')}: UNTESTED")
                continue
            lines.append(
                f"{effect.get('action')}: avg_score {effect.get('avg_meaningful_change', 0.0):.2f}, "
                f"rank {effect.get('rank_score', 0.0):.2f}, "
                f"last {effect.get('last_meaningful_label', 'unknown')}, "
                f"novel {effect.get('novel_state_count', 0)}/{effect.get('times_seen')}, "
                f"reward {effect.get('reward_hits', 0)}/{effect.get('times_seen')}, "
                f"zero_reward_streak {effect.get('zero_reward_streak', 0)}, "
                f"budget {effect.get('retest_budget', 0)}, "
                f"no_progress {effect.get('no_progress_count', 0)}/{effect.get('times_seen')}, "
                f"last {effect.get('recent_diff')}"
            )
        return lines

    def _format_memory_section(
        self,
        memory_context: dict,
        observation: ARC3Observation,
        is_first_decision: bool,
    ) -> List[str]:
        lines: List[str] = []
        for lesson in self._select_prompt_memories(memory_context.get("lessons", []), self.MAX_PROMPT_LESSONS):
            lines.append(f"Lesson: {self._truncate_text(lesson.get('text', ''), 180)}")
        for memory in self._select_prompt_memories(memory_context.get("memories", []), self.MAX_PROMPT_MEMORIES):
            match_score, match_tags = self._score_memory_match(memory, observation)
            if is_first_decision and match_score < 2:
                continue
            prefix = "Matched memory" if match_score >= 2 else "Weak memory"
            lines.append(
                f"{prefix}: {self._truncate_text(self._memory_text(memory), 180)}"
                + (f" [match: {', '.join(match_tags)}]" if match_tags else "")
            )
        for analogy in self._select_prompt_memories(memory_context.get("analogies", []), self.MAX_PROMPT_ANALOGIES):
            lines.append(f"Analogy: {self._truncate_text(self._memory_text(analogy), 180)}")
        return lines

    def _format_reflex_section(self) -> List[str]:
        lines: List[str] = []
        if not self._reflex_context:
            return lines
        for warning in self._reflex_context.get("warnings", [])[:1]:
            lines.append(f"WARNING: {warning}")
        for suggestion in self._reflex_context.get("suggestions", [])[:1]:
            lines.append(f"GOLDEN PATH: {suggestion}")
        return lines

    def _format_plan_section(self) -> List[str]:
        if not self._plan_steps:
            return ["Plan: no steps yet."]
        return [
            f"Step {idx + 1}: {step}"
            for idx, step in enumerate(self._plan_steps[: self.MAX_PROMPT_PLAN_STEPS])
        ]

    def _format_history_section(self, history: List[dict]) -> str:
        if not history:
            return "No steps taken yet."
        entries = []
        for record in history[-self.MAX_PROMPT_HISTORY :]:
            reward = record.get("reward")
            reward_text = f"reward {reward:.2f}" if isinstance(reward, float) else "reward pending"
            entries.append(
                f"Step {record['step']} → {record.get('action_id')} "
                f"({self._truncate_text(record.get('rationale') or '', 120)}) · {reward_text}"
            )
        return "\n".join(entries)

    def _format_observation_section(self, observation: ARC3Observation) -> str:
        grid = observation.get("grid", [])
        rows = len(grid)
        cols = len(grid[0]) if grid else 0
        colors = observation.get("colors", [])
        color_summary = ", ".join(
            f"{c['value']}:{c['count']}" for c in colors[:6]
        ) if colors else "none"
        coarse_map = self._coarse_grid_summary(grid)
        return (
            f"Grid: {rows}x{cols}\n"
            f"Top colors (value:count): {color_summary}\n"
            f"Frame hash: {observation.get('frame_hash', 'unknown')[:12]}\n"
            f"Coarse map (8x8 majority colors):\n{coarse_map}"
        )

    def _coarse_grid_summary(self, grid: List[List[int]], block_count: int = 8) -> str:
        if not grid or not grid[0]:
            return "(empty)"

        rows = len(grid)
        cols = len(grid[0])
        row_block = max(1, rows // block_count)
        col_block = max(1, cols // block_count)
        coarse_rows: list[str] = []
        for row_start in range(0, rows, row_block):
            if len(coarse_rows) >= block_count:
                break
            row_cells: list[str] = []
            for col_start in range(0, cols, col_block):
                if len(row_cells) >= block_count:
                    break
                counts: dict[int, int] = {}
                for r in range(row_start, min(row_start + row_block, rows)):
                    for c in range(col_start, min(col_start + col_block, cols)):
                        value = grid[r][c]
                        counts[value] = counts.get(value, 0) + 1
                dominant = min(counts) if not counts else max(counts, key=counts.get)
                row_cells.append(str(dominant))
            coarse_rows.append(" ".join(row_cells))
        return "\n".join(coarse_rows)

    def _select_prompt_memories(self, items: List[Any], limit: int) -> List[Any]:
        selected: List[Any] = []
        seen: set[str] = set()
        
        # B-93: Prioritize [ACTION FACT] entries
        facts = [item for item in items if "[ACTION FACT]" in self._memory_text(item)]
        others = [item for item in items if "[ACTION FACT]" not in self._memory_text(item)]
        
        for item in facts + others:
            text = self._memory_text(item).strip()
            if not text:
                continue
            if "ARC-AGI-3 API Contract" in text:
                continue
            if text in seen:
                continue
            selected.append(item)
            seen.add(text)
            if len(selected) >= limit:
                break
        return selected

    def _memory_text(self, item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("text") or item.get("text_raw") or item)
        return str(item)

    def _score_memory_match(self, item: Any, observation: ARC3Observation) -> tuple[int, List[str]]:
        text = self._memory_text(item).lower()
        if not text:
            return 0, []

        tags: List[str] = []
        available_actions = [str(action).lower() for action in observation.get("available_actions", [])]
        matched_actions = [action.upper() for action in available_actions if action in text]
        if matched_actions:
            tags.append(f"actions={','.join(matched_actions[:2])}")

        task_id = str(observation.get("task_id", "")).lower()
        dataset_id = str(observation.get("dataset_id", "")).lower()
        state = str(observation.get("state", "")).lower()
        if task_id and task_id in text:
            tags.append("task")
        if dataset_id and dataset_id in text:
            tags.append("dataset")
        if state and state in text:
            tags.append("state")

        color_hits = []
        for color in observation.get("colors", [])[:4]:
            value = str(color.get("value"))
            if f"color {value}" in text or f"{value}->" in text:
                color_hits.append(value)
        if color_hits:
            tags.append(f"colors={','.join(color_hits[:2])}")

        score = len(tags)
        return score, tags

    def _truncate_text(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rstrip() + "..."

    def _snapshot_for_trace(self, observation: ARC3Observation, block_count: int = 4) -> dict:
        grid = observation.get("grid", [])
        colors = observation.get("colors", [])
        return {
            "frame_hash": str(observation.get("frame_hash", "unknown"))[:12],
            "rows": len(grid),
            "cols": len(grid[0]) if grid else 0,
            "top_colors": colors[:6],
            "coarse_map": self._coarse_grid_summary(grid, block_count=block_count),
        }

    # ------------------------------------------------------------------

    def record_step_result(self, reward: float, done: bool) -> None:
        if not self._step_history:
            return
        record = self._step_history[-1]
        record["reward"] = reward
        record["done"] = done
        # B89: Track no-progress steps (reward = 0)
        if reward == 0.0:
            self._no_progress_step_count += 1

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
        self.solve_engine.reset_for_retry()

    def get_benchmark_metrics(self) -> dict:
        """B89: Return collected prompt budget and retrieval budget metrics."""
        avg_prompt_tokens = (
            sum(self._prompt_tokens_per_step) / len(self._prompt_tokens_per_step)
            if self._prompt_tokens_per_step
            else 0
        )
        total_retrieval_size = sum(
            payload.get("total_size", 0) for payload in self._retrieval_payloads
        )
        return {
            "prompt_budget": {
                "total_steps": len(self._prompt_tokens_per_step),
                "avg_tokens_per_step": round(avg_prompt_tokens, 1),
                "max_tokens_per_step": max(self._prompt_tokens_per_step) if self._prompt_tokens_per_step else 0,
                "min_tokens_per_step": min(self._prompt_tokens_per_step) if self._prompt_tokens_per_step else 0,
                "first_prompt_detail_level": self._first_prompt_detail_level,
                "asked_for_decision_from_effects": self._asked_for_decision_from_effects,
                "invalid_action_count": self._invalid_action_count,
                "no_progress_step_count": self._no_progress_step_count,
            },
            "retrieval_budget": {
                "retrieval_count": len(self._retrieval_payloads),
                "total_retrieval_size_bytes": total_retrieval_size,
                "avg_retrieval_size_bytes": (
                    total_retrieval_size / len(self._retrieval_payloads)
                    if self._retrieval_payloads
                    else 0
                ),
            },
        }

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
        frame_hash = str(observation.get("frame_hash", "unknown"))[:12]
        spatial_sketch = self._coarse_grid_summary(grid, block_count=4).replace("\n", " / ")
        color_desc = ", ".join(
            f"color {c['value']} ({c['count']} cells)" for c in colors[:6]
        ) if colors else "none detected"
        shape_desc = ", ".join(
            f"{s.get('type', 'unknown')} size {s.get('size', '?')}" for s in shapes[:6]
        ) if shapes else "none detected"
        return (
            f"[PUZZLE STRUCTURE] Task {observation['task_id']} from {observation['dataset_id']}. "
            f"Grid: {rows}x{cols}. State: {state}. Energy: {energy:.0%}. "
            f"Frame hash: {frame_hash}. "
            f"Colors: {color_desc}. "
            f"Shapes ({len(shapes)}): {shape_desc}. "
            f"Available actions: {', '.join(available) if available else 'pending'}. "
            f"Spatial sketch 4x4: {spatial_sketch or '(empty)'}."
        )
