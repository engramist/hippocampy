"""ARC-AGI-3 orchestrator wrapping the local LLM with SideQuests intelligence."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

from benchmarks.arc3.adapter import BrainClientProtocol
from benchmarks.arc3.schema import ARC3Action, ARC3Observation
from benchmarks.arc3.state_serializer import StateSerializerForARC
from agents.arc3.hypothesis import HypothesisManager
from agents.arc3.solver import SolveEngine
from agents.arc3.repl_sandbox import execute_repl
from agents.arc3.prompts import (
    SYSTEM_PROMPT,
    INSTRUCTION_TEMPLATE,
    SANDBOX_INSTRUCTION,
    REPL_SANDBOX_INSTRUCTION,
    SANDBOX_SYSTEM_MESSAGE,
    QUERY_LLM_SYSTEM_MESSAGE,
    VERIFIER_SYSTEM_PROMPT,
    VERIFIER_PROMPT_TEMPLATE,
)

logger = logging.getLogger(__name__)


@dataclass
class ContentBlock:
    """B117: A structured block of prompt content."""
    type: str
    content: str
    header: Optional[str] = None


@dataclass
class PromptPacket:
    """B117: A typed collection of content blocks for the LLM prompt."""
    blocks: List[ContentBlock] = field(default_factory=list)

    def get_block(self, block_type: str) -> Optional[ContentBlock]:
        return next((b for b in self.blocks if b.type == block_type), None)

    def render(self) -> str:
        """Render the packet into a final prompt string."""
        ordered_keys = [
            "SYSTEM", "STATE", "ENTITY_CONTEXT", "MEMORY", "SOLVE_CONTEXT", "PLAN",
            "ACTION_FACTS", "EXPLORATION_SUMMARY", "PATH_HYPOTHESES", "HYPOTHESIS",
            "OBSERVED_EFFECTS", "REFLEX", "HISTORY", "OBSERVATION",
            "INSTRUCTION"
        ]
        
        # Mapping of block type to its standard header
        headers = {
            "ENTITY_CONTEXT": "ENTITY CONTEXT",
            "MEMORY": "MEMORY",
            "SOLVE_CONTEXT": "SOLVE CONTEXT",
            "PLAN": "PLAN",
            "ACTION_FACTS": "ACTION FACTS",
            "EXPLORATION_SUMMARY": "EXPLORATION SUMMARY",
            "PATH_HYPOTHESES": "PATH HYPOTHESES",
            "HYPOTHESIS": "HYPOTHESIS",
            "OBSERVED_EFFECTS": "OBSERVED EFFECTS",
            "REFLEX": "REFLEX",
            "HISTORY": "HISTORY",
            "OBSERVATION": "OBSERVATION",
        }

        block_map = {b.type: b for b in self.blocks}
        final_parts = []
        for key in ordered_keys:
            if key in block_map:
                block = block_map[key]
                if not block.content.strip():
                    continue
                
                header = block.header or headers.get(key)
                if header:
                    final_parts.append(f"=== {header} ===\n{block.content}")
                else:
                    final_parts.append(block.content)

        return "\n\n".join(final_parts)


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
        # B131: Comprehensive execution trace for CloudWatch-style logging
        self._execution_trace: List[dict] = []
        self._trace_start_time = time.time()
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
        self._last_seen_invalid_action_count = 0
        self._memory_context: dict | None = None
        self._pruning_decisions: List[dict] = []
        self._entity_gate_result: Dict[str, Any] = {}
        self._compaction_artifact: Any | None = None
        self._guard_escalations: List[dict] = []

    def record_guard_escalation(self, step: int, reason: str, status: str):
        """B130: Record a guard escalation event."""
        self._guard_escalations.append({
            "step": step,
            "reason": reason,
            "guard_state": status
        })

    def _emit_trace_event(self, event_type: str, operation: str, details: dict | None = None, result: dict | None = None, elapsed_ms: float | None = None):
        """B131: Emit a timestamped execution trace event (CloudWatch-style)."""
        import time
        timestamp_iso = datetime.datetime.fromtimestamp(time.time(), datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        event = {
            "timestamp_iso": timestamp_iso,
            "event_type": event_type,
            "operation": operation,
            "details": details or {},
            "result": result,
            "elapsed_ms": elapsed_ms,
        }
        self._execution_trace.append(event)

    @property
    def _entity_map(self) -> Dict[int, Dict[str, Any]]:
        """B120: Property proxy for B119 object roles."""
        return {
            k: {
                "role": v.role.value,
                "confidence": v.confidence,
                "position": v.estimated_position
            }
            for k, v in self.solve_engine._object_roles.items()
        }

    def get_ledger(self) -> List[dict]:
        """Return the collected SideQuests call ledger."""
        from benchmarks.arc3.adapter import LedgerBrainClient
        if isinstance(self.brain, LedgerBrainClient):
            return list(self.brain.ledger)
        return []

    def analyze_ledger_and_prune(self) -> List[dict]:
        """B118: Analyze ledger for high-latency/low-value patterns and prune."""
        ledger = self.get_ledger()
        if not ledger:
            return []

        decisions = []
        # Group by call_type to find slow offenders
        stats = {}
        for entry in ledger:
            ctype = entry["call_type"]
            if ctype not in stats:
                stats[ctype] = {"count": 0, "total_latency": 0.0, "low_value_count": 0}
            stats[ctype]["count"] += 1
            stats[ctype]["total_latency"] += entry.get("latency_ms", 0)
            
            # Rough proxy for "low value" in ARC:
            # - retrieval that found 0 items
            # - notify that returned just "ok" but didn't trigger a meaningful hypothesis
            res = str(entry.get("result_summary", "")).lower()
            if "found 0" in res or "found []" in res:
                stats[ctype]["low_value_count"] += 1

        for ctype, data in stats.items():
            avg_latency = data["total_latency"] / data["count"]
            low_value_ratio = data["low_value_count"] / data["count"]
            
            # Pruning criteria: avg > 500ms and > 50% are low value
            if avg_latency > 500 and low_value_ratio > 0.5:
                decision = {
                    "call_type": ctype,
                    "reason": f"high latency ({avg_latency:.1f}ms) with low value ratio ({low_value_ratio:.1%})",
                    "action": "deprioritize",
                }
                decisions.append(decision)
                # Avoid duplicate decisions
                if not any(d["call_type"] == ctype for d in self._pruning_decisions):
                    self._pruning_decisions.append(decision)

        return decisions

    async def _bootstrap_entity_discovery(self, observation: ARC3Observation) -> None:
        """B119: Extract bootstrap entity discovery logic."""
        bootstrap_roles = self.solve_engine.role_mapper.seed_bootstrap_roles(observation)
        discovered_count = 0
        for color_id, role in bootstrap_roles.items():
            existing = self.solve_engine._object_roles.get(color_id)
            # Update if new, or if existing was unknown/low-conf
            if existing is None or existing.role == "unknown" or role.confidence > existing.confidence:
                self.solve_engine._object_roles[color_id] = role
                discovered_count += 1
        
        if discovered_count > 0:
            detail = {
                str(k): {"role": v.role.value, "confidence": v.confidence}
                for k, v in bootstrap_roles.items()
            }
            self._record_write_event(
                kind="bootstrap_discovery",
                summary=f"Discovered {discovered_count} preliminary entities from initial frame.",
                detail=detail,
                source_step=0,
            )

    def _check_entity_gate(self, observation: ARC3Observation) -> dict:
        """B121: Check entity discovery completeness.

        Returns:
            {"status": "pass"|"skip"|"fail"|"degraded",
             "reason": str,
             "retry_count": int}
        """
        colors = observation.get("colors", [])
        non_bg_colors = [c for c in colors
                         if (c["value"] if isinstance(c, dict) else c) != 0]

        if len(non_bg_colors) <= 0:
            return {"status": "skip", "reason": "single-color grid", "retry_count": 0}

        if not self._entity_map:
            return {"status": "fail", "reason": "entity map empty", "retry_count": 0}

        has_known = any(
            info["role"] != "unknown" for info in self._entity_map.values()
        )
        if has_known:
            return {"status": "pass", "reason": "entity roles identified", "retry_count": 0}

        return {"status": "fail", "reason": "all roles UNKNOWN", "retry_count": 0}

    # ── Phase 1: Perceive ───────────────────────────────────────────────

    async def perceive(self, observation: ARC3Observation, step: int = 0) -> dict:
        """Ingest puzzle structure into SideQuests then optionally consult memory based on triggers."""
        self._emit_trace_event(
            "phase_start",
            "perceive",
            {
                "step": step,
                "task_id": observation.get("task_id"),
                "state": observation.get("state"),
            },
        )

        # Feed puzzle structure into SideQuests (raw → short-term → entities via consolidation)
        structure_summary = self._summarize_puzzle_structure(observation)
        notify_start = time.time()
        notify_response = await self.brain.notify_turn(
            role="user", content=structure_summary, session_id=self.session_id
        )
        notify_elapsed = (time.time() - notify_start) * 1000
        self._emit_trace_event(
            "operation",
            "notify_turn[structure_ingest]",
            {"step": step},
            {"summary_length": len(structure_summary)},
            notify_elapsed,
        )
        self._record_write_event(
            kind="notify_turn",
            summary=structure_summary,
            detail={"role": "user", "scope": "structure_ingest"},
            response_dict=notify_response,
        )

        # B119/B121: Bootstrap initial entity map at step 0 with enforcement gate
        if step == 0:
            bootstrap_start = time.time()
            await self._bootstrap_entity_discovery(observation)
            bootstrap_elapsed = (time.time() - bootstrap_start) * 1000
            self._emit_trace_event(
                "operation",
                "bootstrap_entity_discovery",
                {"step": step},
                {"entity_count": len(self._entity_map)},
                bootstrap_elapsed,
            )

            # Entity gate enforcement (B121)
            max_entity_retries = 2
            gate_result = self._check_entity_gate(observation)
            retry_count = 0
            while gate_result["status"] == "fail" and retry_count < max_entity_retries:
                retry_count += 1
                logger.warning(
                    "Entity gate failed (attempt %d/%d): %s — retrying",
                    retry_count, max_entity_retries, gate_result["reason"],
                )
                await self._bootstrap_entity_discovery(observation)
                gate_result = self._check_entity_gate(observation)

            gate_result["retry_count"] = retry_count
            if gate_result["status"] == "fail":
                gate_result["status"] = "degraded"
                gate_result["reason"] = f"entity discovery failed after {retry_count} retries"
                logger.warning("Entity gate degraded: %s", gate_result["reason"])

            self._entity_gate_result = gate_result
            self._emit_trace_event(
                "operation",
                "entity_gate",
                {"step": step},
                gate_result,
            )
            self._record_write_event(
                kind="entity_gate",
                summary=f"Entity gate: {gate_result['status']} ({gate_result['reason']})",
                detail=gate_result,
                source_step=0,
            )

        # B90: Check retrieval triggers to decide whether to fetch memory
        should_retrieve = self._should_trigger_retrieval(observation, step)
        self._retrieval_triggered = should_retrieve
        self._emit_trace_event(
            "operation",
            "retrieval_trigger_check",
            {"step": step},
            {"triggered": should_retrieve},
        )

        if should_retrieve:
            query = self._memory_query(observation)
            truth_start = time.time()
            truth = await self.brain.current_truth(
                query=query, session_id=self.session_id, scope="branch", limit=5
            )
            truth_elapsed = (time.time() - truth_start) * 1000
            self._emit_trace_event(
                "operation",
                "current_truth",
                {"step": step, "query": query},
                {"results": len(truth.get("results", []))},
                truth_elapsed,
            )

            lessons_start = time.time()
            lessons = await self.brain.recall_relevant_lessons(query=query, limit=4)
            lessons_elapsed = (time.time() - lessons_start) * 1000
            self._emit_trace_event(
                "operation",
                "recall_relevant_lessons",
                {"step": step, "query": query},
                {"results": len(lessons.get("lessons", []))},
                lessons_elapsed,
            )

            analog_start = time.time()
            analogies = await self.brain.analogical_search(
                query=query,
                current_quest_id=observation.get("dataset_id", ""),
                limit=3,
                min_similarity=0.35,
            )
            analog_elapsed = (time.time() - analog_start) * 1000
            self._emit_trace_event(
                "operation",
                "analogical_search",
                {"step": step, "query": query},
                {"results": len(analogies.get("results", []))},
                analog_elapsed,
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
        self._emit_trace_event(
            "phase_end",
            "perceive",
            {"step": step},
            {
                "retrieval_triggered": bool(memory_context.get("_triggered")),
                "memories": len(memory_context.get("memories", [])),
                "lessons": len(memory_context.get("lessons", [])),
                "analogies": len(memory_context.get("analogies", [])),
            },
        )
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
        self._emit_trace_event(
            "phase_start",
            "hypothesize",
            {
                "step": step,
                "action_taken": action_taken,
                "state": observation.get("state"),
            },
        )
        available = observation.get("available_actions") or [f"ACTION{i}" for i in range(1, 8)]
        observe_start = time.time()
        context = self.hypothesis_mgr.observe(
            grid=observation["grid"],
            action_taken=action_taken,
            step=step,
            available_actions=available,
            observation=observation,
            transition_meta=transition_meta,
        )
        observe_elapsed = (time.time() - observe_start) * 1000
        self._emit_trace_event(
            "operation",
            "hypothesis_mgr.observe",
            {"step": step, "action_taken": action_taken},
            {
                "loop_detected": bool(context.get("loop_detected")),
                "facts": len(context.get("action_facts", []) or []),
                "paths": len(context.get("path_hypotheses", []) or []),
            },
            observe_elapsed,
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
            self._emit_trace_event(
                "operation",
                "hypothesis_update",
                {"step": step},
                {
                    "label": transition_effect.get("meaningful_change_label"),
                    "score": transition_effect.get("meaningful_change_score"),
                    "facts": len(action_facts),
                    "paths": len(path_hypotheses),
                },
            )

        self._hypothesis_context = context
        
        # B116: Refresh compaction artifact
        compact_start = time.time()
        self._compaction_artifact = self.hypothesis_mgr.compact_exploration(step)
        compact_elapsed = (time.time() - compact_start) * 1000
        self._emit_trace_event(
            "operation",
            "compact_exploration",
            {"step": step},
            {"artifact_type": type(self._compaction_artifact).__name__},
            compact_elapsed,
        )
        self._emit_trace_event(
            "phase_end",
            "hypothesize",
            {"step": step},
            {
                "loop_detected": bool(context.get("loop_detected")),
                "energy_from_hud": context.get("energy_from_hud"),
            },
        )
        
        return context

    async def solve(
        self,
        observation: ARC3Observation,
        hypothesis_context: dict,
        step: int,
    ) -> dict:
        """Classify archetype, assign object roles, hypothesize victory condition, chunk plan."""
        self._emit_trace_event(
            "phase_start",
            "solve",
            {
                "step": step,
                "task_id": observation.get("task_id"),
                "state": observation.get("state"),
            },
        )
        current_hash = hypothesis_context.get("current_state_hash", "")
        solve_start = time.time()
        solve_ctx = await self.solve_engine.solve(
            observation=observation,
            hypothesis_context=hypothesis_context,
            step=step,
            state_graph=self.hypothesis_mgr.graph,
            current_state_hash=current_hash,
        )
        solve_elapsed = (time.time() - solve_start) * 1000
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
                    "plan_id": solve_ctx.active_chunk.plan_id,
                }
                if solve_ctx.active_chunk else None
            ),
            "dissonance": solve_ctx.dissonance_detected,
            "dissonance_reason": solve_ctx.dissonance_reason,
            "strategy_summary": solve_ctx.strategy_summary,
            "chunk_ledger": [
                {
                    "description": entry.description,
                    "status": entry.status,
                    "steps_used": entry.steps_used,
                    "outcome_summary": entry.outcome_summary,
                }
                for entry in (solve_ctx.chunk_ledger or [])
            ],
        }
        archetype = self._solve_context["archetype"]
        conf = self._solve_context["archetype_confidence"]
        victory = (self._solve_context.get("victory_condition") or {}).get("type", "unknown")
        chunk = (self._solve_context.get("active_chunk") or {}).get("description", "none")
        dissonance = self._solve_context.get("dissonance", False)
        logger.info(
            "[SOLVE] step=%d archetype=%s(%.2f) victory=%s chunk=%s dissonance=%s",
            step, archetype, conf, victory, chunk[:40] if chunk else "none", dissonance,
        )
        self._emit_trace_event(
            "phase_end",
            "solve",
            {"step": step},
            {
                "archetype": archetype,
                "archetype_confidence": conf,
                "victory": victory,
                "dissonance": dissonance,
            },
            solve_elapsed,
        )
        return self._solve_context

    async def plan(self, observation: ARC3Observation, memory_context: dict) -> dict:
        """Declare a plan and capture Amygdala Reflex context."""
        import time
        plan_start = time.time()
        self._emit_trace_event("phase_start", "plan", {"goal": f"Solve ARC task {observation['dataset_id']}:{observation['task_id']}"})
        
        goal = f"Solve ARC task {observation['dataset_id']}:{observation['task_id']}"
        recall_start = time.time()
        recall = await self.brain.recall_plans(
            goal_query=goal, session_id=self.session_id, min_valence=0.0, limit=3
        )
        recall_elapsed = (time.time() - recall_start) * 1000
        self._emit_trace_event("operation", "recall_plans", {"goal_query": goal}, {"found": len(recall.get("plans", []))}, recall_elapsed)
        
        draft_start = time.time()
        self._plan_steps = self._draft_plan_steps(
            observation, memory_context, recall, self._hypothesis_context
        )
        draft_elapsed = (time.time() - draft_start) * 1000
        self._emit_trace_event("operation", "draft_plan_steps", {}, {"steps_count": len(self._plan_steps)}, draft_elapsed)
        
        # B131: Emit reasoning trace explaining plan strategy
        sc = self._solve_context
        reasoning_parts = []
        if sc and sc.get("archetype"):
            reasoning_parts.append(f"Archetype: {sc['archetype']} (conf={sc['archetype_confidence']:.2f})")
        if sc and sc.get("victory_condition"):
            vc = sc["victory_condition"]
            reasoning_parts.append(f"Win condition: {vc['type']} (conf={vc['confidence']:.2f})")
        if sc and sc.get("active_chunk"):
            ch = sc["active_chunk"]
            reasoning_parts.append(f"Active chunk: {ch['description']}")
        
        reasoning_summary = " | ".join(reasoning_parts) if reasoning_parts else "Fallback exploration strategy"
        reasoning_narrative = f"[PLAN REASONING] Goal: {goal}. Strategy: {reasoning_summary}. Steps: {len(self._plan_steps)}"
        reason_start = time.time()
        await self.brain.notify_turn(role="assistant", content=reasoning_narrative, session_id=self.session_id)
        reason_elapsed = (time.time() - reason_start) * 1000
        self._emit_trace_event("operation", "notify_turn[plan_reasoning]", {"content": reasoning_narrative}, {}, reason_elapsed)
        
        register_start = time.time()
        plan_payload = await self.brain.register_plan(
            goal=goal, steps=self._plan_steps, session_id=self.session_id
        )
        register_elapsed = (time.time() - register_start) * 1000
        self._emit_trace_event("operation", "register_plan", {"goal": goal, "steps": len(self._plan_steps)}, {"plan_id": plan_payload.get("plan_id")}, register_elapsed)
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
        self._emit_trace_event(
            "phase_start",
            "act",
            {
                "step": step_num,
                "state": observation.get("state"),
                "available_actions": len(observation.get("available_actions") or []),
            },
        )

        if step_num > 3:
            loop_check_start = time.time()
            await self.brain.current_truth(
                query="Am I looping?", session_id=self.session_id, scope="branch", limit=3
            )
            loop_check_elapsed = (time.time() - loop_check_start) * 1000
            self._emit_trace_event(
                "operation",
                "current_truth[loop_check]",
                {"step": step_num},
                {},
                loop_check_elapsed,
            )

        narrative = f"Step {step_num} observation: state={observation.get('state', 'UNKNOWN')} colors={observation['colors']} shapes={observation['shapes']}"
        step_notify_start = time.time()
        notify_response = await self.brain.notify_turn(role="user", content=narrative, session_id=self.session_id)
        step_notify_elapsed = (time.time() - step_notify_start) * 1000
        self._emit_trace_event(
            "operation",
            "notify_turn[step_observation]",
            {"step": step_num},
            {"summary_length": len(narrative)},
            step_notify_elapsed,
        )
        self._record_write_event(
            kind="notify_turn",
            summary=narrative,
            detail={"role": "user", "scope": "step_observation", "step": step_num},
            response_dict=notify_response,
            source_step=step_num,
        )

        available_actions = observation.get("available_actions") or [f"ACTION{i}" for i in range(1, 8)]
        
        # B117: Use PromptPacket model
        packet = self.build_action_packet(
            observation=observation,
            memory_context=memory_context,
            step_history=self._step_history,
            available_actions=available_actions,
        )
        prompt = packet.render()
        
        # B89: Estimate prompt tokens and track first-prompt detail level
        prompt_tokens = self.serializer._estimate_tokens(prompt)
        self._prompt_tokens_per_step.append(prompt_tokens)
        if not self._step_history:
            # This is the first prompt - determine detail level
            # Check for specific block presence
            has_memory = packet.get_block("MEMORY") is not None
            has_facts = packet.get_block("ACTION_FACTS") is not None
            has_effects = packet.get_block("OBSERVED_EFFECTS") is not None
            self._first_prompt_detail_level = "rich" if (has_memory or has_facts or has_effects) else "compact"
        
        # Check if prompt asks for decision from observed effects
        if packet.get_block("OBSERVED_EFFECTS") and packet.get_block("INSTRUCTION"):
            self._asked_for_decision_from_effects = "effect" in prompt.lower()

        # B114/B123: Mental Sandbox reasoning loop (includes REPL)
        sandbox_start = time.time()
        action = await self._mental_sandbox(prompt, available_actions, observation)
        sandbox_elapsed = (time.time() - sandbox_start) * 1000
        self._emit_trace_event(
            "operation",
            "mental_sandbox",
            {"step": step_num},
            {"action_id": action.get("action_id")},
            sandbox_elapsed,
        )

        action = self._enforce_action_policy(action, available_actions)
        action = self._ensure_action6_coordinates(action, observation)

        # B115: Final pre-execution decision guard
        guard_result = self.solve_engine.critique_action(
            action_id=action["action_id"],
            available_actions=available_actions,
            hypothesis_context=self._hypothesis_context or {},
            step_history=self._step_history,
        )
        self._emit_trace_event(
            "operation",
            "critique_action",
            {"step": step_num, "candidate_action": action.get("action_id")},
            {
                "status": guard_result.get("status"),
                "suggested_action": guard_result.get("suggested_action"),
            },
        )
        
        executed_by = "llm"
        if guard_result["status"] in ("blocked", "warned"):
            self.record_guard_escalation(step_num, guard_result["reason"], guard_result["status"])
            if guard_result.get("suggested_action"):
                old_id = action["action_id"]
                new_id = guard_result["suggested_action"]
                action["action_id"] = new_id
                action["rationale"] = (
                    f"{action.get('rationale', '')} (guard override: {old_id} -> {new_id} :: {guard_result['reason']})"
                )
                executed_by = "guard_override"
            elif guard_result["status"] == "blocked":
                # If blocked and no suggestion, we must still move. 
                # Policy enforcement should have already ensured it's at least valid if possible.
                action["rationale"] = f"{action.get('rationale', '')} (guard blocked: {guard_result['reason']})"
                executed_by = "guard_blocked_fallback"
        
        action = self._ensure_action6_coordinates(action, observation)
        action["guard_status"] = guard_result["status"]

        # B126: Adversarial verification of candidate action (optional, can be disabled via config)
        verifier_enabled = self.config.get("enable_verifier", False)
        verifier_attempts = 0
        verifier_result = None
        original_action_id = action["action_id"]

        while verifier_enabled and verifier_attempts < 2:
            verifier_result = await self._verify_candidate_action(
                action_id=action["action_id"],
                rationale=action.get("rationale", ""),
                observation=observation,
                step_history=self._step_history,
                hypothesis_context=self._hypothesis_context or {},
            )

            verifier_attempts += 1

            if verifier_result["approved"]:
                break

            # First rejection: retry with rejection context
            if verifier_attempts < 2:
                logger.info(
                    "Verifier rejected %s: %s — retrying",
                    action["action_id"],
                    verifier_result["rejection_reason"],
                )
                # Append rejection context to the original prompt and retry
                retry_prompt = prompt + f"\n\nVerifier feedback: {verifier_result['rejection_reason']}\nReconsider: what action is better?"
                retry_action = await self._mental_sandbox(retry_prompt, available_actions, observation)
                retry_action = self._enforce_action_policy(retry_action, available_actions)
                retry_action = self._ensure_action6_coordinates(retry_action, observation)
                action = retry_action
            else:
                # Second rejection: log and proceed with original action
                logger.warning(
                    "Verifier double-rejected %s (%s), proceeding with original %s",
                    action["action_id"],
                    verifier_result["rejection_reason"],
                    original_action_id,
                )
                # Don't revert action, proceed with final candidate

        # Record verifier result in thinking trace (only if verifier was enabled)
        if verifier_enabled:
            if action.get("thinking_trace") is None:
                action["thinking_trace"] = []

            action["thinking_trace"].append({
                "kind": "verification",
                "candidate_action": original_action_id,
                "verifier_approved": verifier_result.get("approved") if verifier_result else True,
                "rejection_reason": verifier_result.get("rejection_reason") if verifier_result else None,
                "attempts": verifier_attempts,
                "final_action": action["action_id"],
            })

            action["verifier_status"] = "approved" if (verifier_result and verifier_result["approved"]) else "rejected_then_proceeded"
            self._emit_trace_event(
                "operation",
                "verifier",
                {"step": step_num, "attempts": verifier_attempts},
                {
                    "enabled": True,
                    "approved": bool(verifier_result and verifier_result.get("approved")),
                    "final_action": action.get("action_id"),
                },
            )
        else:
            action["verifier_status"] = "disabled"
            self._emit_trace_event(
                "operation",
                "verifier",
                {"step": step_num},
                {"enabled": False},
            )

        # B89: Track invalid actions
        action_id = action.get("action_id")
        if action_id not in available_actions:
            self._invalid_action_count += 1

        self._step_history.append({
            "step": len(self._step_history) + 1,
            "state_before": observation.get("state"),
            "board_before": self._snapshot_for_trace(observation),
            "solve_context": dict(self._solve_context) if self._solve_context else None,
            "available_actions": list(available_actions),
            "prompt": prompt,
            "decision_flow": {
                "proposed_by": "llm",
                "executed_by": executed_by,
                "guard_status": guard_result["status"],
                "guard_reason": guard_result["reason"] if guard_result["status"] != "approved" else None
            },
            "action_id": action.get("action_id"),
            "x": action.get("x"),
            "y": action.get("y"),
            "rationale": action.get("rationale"),
            "thinking_trace": action.get("thinking_trace", []),
            "guard_status": action.get("guard_status", "unknown"),
            "verifier_status": action.get("verifier_status", "unknown"),
            "reward": None,
            "done": False,
            "prompt_tokens": prompt_tokens,
        })
        self._emit_trace_event(
            "phase_end",
            "act",
            {"step": step_num},
            {
                "action_id": action.get("action_id"),
                "guard_status": action.get("guard_status"),
                "verifier_status": action.get("verifier_status"),
                "prompt_tokens": prompt_tokens,
            },
        )
        return action

    async def _mental_sandbox(self, initial_prompt: str, available_actions: List[str], observation: ARC3Observation) -> ARC3Action:
        """B114/B123: Bounded internal reasoning loop before final move."""
        max_iterations = 2
        iteration = 0
        current_prompt = initial_prompt
        thinking_trace = []
        self._emit_trace_event(
            "operation",
            "mental_sandbox_start",
            {"max_iterations": max_iterations},
            {"available_actions": len(available_actions)},
        )
        
        # B122/B123: Use extracted sandbox instructions
        current_prompt += SANDBOX_INSTRUCTION
        current_prompt += REPL_SANDBOX_INSTRUCTION

        while iteration < max_iterations:
            iteration += 1
            self._emit_trace_event(
                "operation",
                "mental_sandbox_iteration",
                {"iteration": iteration},
            )
            messages = [
                {"role": "system", "content": SANDBOX_SYSTEM_MESSAGE},
                {"role": "user", "content": current_prompt},
            ]
            try:
                raw = await asyncio.to_thread(self.llm.chat, messages)
                parsed = json.loads(raw)
                
                # Check for sandbox thought tool (B114)
                if "sandbox_thought" in parsed:
                    test_action = parsed["sandbox_thought"]
                    result = self.solve_engine.peek_action_consequences(test_action, self._hypothesis_context or {})
                    self._emit_trace_event(
                        "operation",
                        "sandbox_thought",
                        {"iteration": iteration, "test_action": test_action},
                        {
                            "estimated_score": result.get("estimated_score") if isinstance(result, dict) else None,
                            "meaningful_change": result.get("meaningful_change") if isinstance(result, dict) else None,
                        },
                    )
                    
                    thought_entry = {
                        "iteration": iteration,
                        "thought": parsed.get("thought", ""),
                        "tool": "sandbox_thought",
                        "test_action": test_action,
                        "result": result
                    }
                    thinking_trace.append(thought_entry)
                    
                    current_prompt += f"\n\nSandbox Result for {test_action}: {json.dumps(result)}\nWhat is your next thought or final decision?"
                    continue

                # Check for REPL test tool (B123)
                if "repl_test" in parsed:
                    code = parsed["repl_test"]
                    # Add simple grid variable for convenience
                    grid_code = f"g = {json.dumps(observation.get('grid', []))}\n" + code
                    result = await asyncio.to_thread(execute_repl, grid_code)
                    self._emit_trace_event(
                        "operation",
                        "repl_test",
                        {"iteration": iteration},
                        {
                            "stderr": result.get("stderr", "")[:200],
                            "stdout_len": len(result.get("stdout", "")),
                        },
                    )
                    
                    thought_entry = {
                        "iteration": iteration,
                        "thought": parsed.get("thought", ""),
                        "tool": "repl_test",
                        "code": code,
                        "result": result
                    }
                    thinking_trace.append(thought_entry)
                    
                    current_prompt += f"\n\nREPL Result:\nstdout: {result['stdout']}\nstderr: {result['stderr']}\nWhat is your next thought or final decision?"
                    continue
                
                # Final decision found
                if "action_id" in parsed:
                    action_id = self._normalize_action_id(parsed.get("action_id"))
                    rationale = parsed.get("rationale", "")
                    self._emit_trace_event(
                        "operation",
                        "mental_sandbox_final_decision",
                        {"iteration": iteration},
                        {"action_id": action_id},
                    )
                    
                    if action_id not in available_actions:
                        fallback = available_actions[0]
                        logger.warning(
                            "LLM selected unavailable action %r in sandbox; falling back to %r.",
                            action_id, fallback
                        )
                        return {
                            "action_id": fallback,
                            "rationale": f"Invalid LLM action {action_id!r} in sandbox; fallback to {fallback}. Original rationale: {rationale}",
                            "thinking_trace": thinking_trace
                        }

                    if thinking_trace:
                        rationale = f"{rationale} (sandbox refined)"
                    action: ARC3Action = {
                        "action_id": action_id,
                        "rationale": rationale,
                        "thinking_trace": thinking_trace,
                    }
                    x = self._coerce_action6_coordinate(parsed.get("x"))
                    y = self._coerce_action6_coordinate(parsed.get("y"))
                    if x is not None:
                        action["x"] = x
                    if y is not None:
                        action["y"] = y
                    return action
                
                # Fallback if neither
                iteration = max_iterations
            except Exception as exc:
                logger.warning("Mental sandbox parse failed: %s", exc)
                self._emit_trace_event(
                    "operation",
                    "mental_sandbox_parse_error",
                    {"iteration": iteration},
                    {"error": str(exc)},
                )
                break

        # Fallback to standard query if sandbox fails or exhausts
        final_action = await self._query_llm(initial_prompt, available_actions)
        self._emit_trace_event(
            "operation",
            "mental_sandbox_fallback_query_llm",
            {},
            {"action_id": final_action.get("action_id")},
        )
        if thinking_trace:
            final_action["thinking_trace"] = thinking_trace
        return final_action


    # ── Phase 4: Evaluate ──────────────────────────────────────────────

    async def evaluate(
        self,
        correct: bool,
        steps_taken: int,
        max_steps: int,
        final_observation: ARC3Observation,
    ) -> dict:
        """Report outcome and trigger valence propagation."""
        self._emit_trace_event(
            "phase_start",
            "evaluate",
            {
                "task_id": final_observation.get("task_id"),
                "steps_taken": steps_taken,
                "max_steps": max_steps,
                "correct": correct,
            },
        )
        valence = self.reward_to_valence(correct, steps_taken, max_steps)
        payload = {
            "plan_id": self._plan_id,
            "outcome": "correct" if correct else "failed",
            "valence": valence,
            "session_id": self.session_id,
        }
        if self._plan_id:
            report_start = time.time()
            outcome_response = await self.brain.report_outcome(**payload)
            report_elapsed = (time.time() - report_start) * 1000
            self._emit_trace_event(
                "operation",
                "report_outcome",
                {"plan_id": self._plan_id},
                {
                    "outcome": payload["outcome"],
                    "valence": round(valence, 2),
                },
                report_elapsed,
            )
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
        final_notify_start = time.time()
        final_notify_response = await self.brain.notify_turn(role="assistant", content=narrative, session_id=self.session_id)
        final_notify_elapsed = (time.time() - final_notify_start) * 1000
        self._emit_trace_event(
            "operation",
            "notify_turn[final_narrative]",
            {"task_id": final_observation.get("task_id")},
            {"summary_length": len(narrative)},
            final_notify_elapsed,
        )
        self._record_write_event(
            kind="notify_turn",
            summary=narrative,
            detail={"role": "assistant", "scope": "final_narrative"},
            response_dict=final_notify_response,
        )
        self._emit_trace_event(
            "phase_end",
            "evaluate",
            {"task_id": final_observation.get("task_id")},
            {
                "correct": correct,
                "steps_taken": steps_taken,
                "valence": round(valence, 2),
            },
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

        # B118: Pruning check - if retrieval tools are already marked as low-value/high-latency,
        # skip optional mid-run retrieval to save time.
        pruned_types = {d["call_type"] for d in self._pruning_decisions if d["action"] == "deprioritize"}
        retrieval_types = {"current_truth", "recall_lessons", "analogical_search"}
        if retrieval_types.intersection(pruned_types) and step > 0:
            logger.info("[B118] Skipping retrieval trigger due to prior pruning decisions.")
            return False

        # Trigger 2: Repeated no-progress steps (3+ consecutive)
        if self._consecutive_no_progress_steps >= 3 and step > self._last_retrieval_step:
            return True

        # Trigger 3: Invalid action correction (attempted invalid action)
        if self._invalid_action_count > self._last_seen_invalid_action_count and step > self._last_retrieval_step:
            self._last_seen_invalid_action_count = self._invalid_action_count
            return True

        hyp_ctx = self._hypothesis_context or {}

        # Trigger 4: Loop suspicion
        if hyp_ctx.get("loop_detected"):
            return True

        # Trigger 5: Large state shift that can invalidate prior assumptions
        if self._should_trigger_large_state_shift(hyp_ctx):
            return True

        # Trigger 6: Evidence gap - no clear action candidates
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

    def _should_trigger_large_state_shift(self, hyp_ctx: dict | None) -> bool:
        """Cheap proxy for a sudden board change that invalidates prior assumptions."""
        if not hyp_ctx:
            return False
        last_effect = hyp_ctx.get("last_transition_effect") or {}
        score = float(last_effect.get("meaningful_change_score", 0.0))
        pixels_changed = int(last_effect.get("pixels_changed", 0) or 0)
        if pixels_changed >= 32:
            return True
        if score >= 0.65 and pixels_changed >= 12:
            return True
        return False

    # ── Prompt Construction ──────────────────────────────────────────

    def build_action_packet(
        self,
        observation: ARC3Observation,
        memory_context: dict,
        step_history: List[dict],
        available_actions: List[str],
    ) -> PromptPacket:
        """Construct a structured PromptPacket for the current decision. B117"""
        packet = PromptPacket()

        packet.blocks.append(ContentBlock(
            type="SYSTEM",
            content=SYSTEM_PROMPT.format(available_actions=', '.join(available_actions))
        ))

        state = observation.get("state", "UNKNOWN")
        energy = observation.get("energy_estimate", 1.0)
        packet.blocks.append(ContentBlock(
            type="STATE",
            content=f"STATE: {state}  ENERGY: {energy:.0%}"
        ))

        # B120: Entity context block
        if self._entity_map:
            entity_lines = []
            for cid, info in self._entity_map.items():
                if info["role"] == "unknown":
                    continue
                line = f"Color {cid}: {info['role']} (confidence={info['confidence']:.0%})"
                if info.get("position"):
                    line += f" at row {info['position']['row']:.0f}, col {info['position']['col']:.0f}"
                entity_lines.append(line)
            if entity_lines:
                packet.blocks.append(ContentBlock(
                    type="ENTITY_CONTEXT",
                    content="\n".join(entity_lines),
                    header="ENTITY CONTEXT",
                ))

        if memory_context.get("_triggered"):
            memory_lines = self._format_memory_section(memory_context, observation, is_first_decision=not step_history)
            if memory_lines:
                packet.blocks.append(ContentBlock(type="MEMORY", content="\n".join(memory_lines)))

        fact_lines = self._format_action_fact_section(self._hypothesis_context)
        if fact_lines:
            packet.blocks.append(ContentBlock(type="ACTION_FACTS", content="\n".join(fact_lines)))

        hyp_lines = self._format_path_hypothesis_section(self._hypothesis_context)
        if hyp_lines:
            packet.blocks.append(ContentBlock(type="PATH_HYPOTHESES", content="\n".join(hyp_lines)))

        hypothesis_lines = self._format_hypothesis_section(self._hypothesis_context)
        if hypothesis_lines:
            packet.blocks.append(ContentBlock(type="HYPOTHESIS", content="\n".join(hypothesis_lines)))

        solve_section = self._build_solve_section()
        if solve_section:
            # Solve section already has a header usually, but packet render adds one.
            # Let's clean it up to avoid double headers.
            content = solve_section.replace("=== SOLVE CONTEXT ===\n", "")
            packet.blocks.append(ContentBlock(type="SOLVE_CONTEXT", content=content))

        effect_lines = self._format_effect_section(self._hypothesis_context)
        if effect_lines:
            packet.blocks.append(ContentBlock(type="OBSERVED_EFFECTS", content="\n".join(effect_lines)))

        # EXPLORATION_SUMMARY from B116
        compaction_text = self._format_compaction_section()
        if compaction_text:
            packet.blocks.append(ContentBlock(type="EXPLORATION_SUMMARY", content=compaction_text))

        reflex_lines = self._format_reflex_section()
        if reflex_lines:
            packet.blocks.append(ContentBlock(type="REFLEX", content="\n".join(reflex_lines)))

        plan_lines = self._format_plan_section()
        packet.blocks.append(ContentBlock(type="PLAN", content="\n".join(plan_lines)))

        history_text = self._format_history_section(step_history)
        packet.blocks.append(ContentBlock(type="HISTORY", content=history_text))

        packet.blocks.append(ContentBlock(
            type="OBSERVATION",
            content=self._format_observation_section(observation)
        ))

        # B110: INSTRUCTION should not duplicate effect summary (already in OBSERVED EFFECTS)
        instruction_text = self._format_instruction_section(self._hypothesis_context)
        packet.blocks.append(ContentBlock(
            type="INSTRUCTION",
            content=instruction_text
        ))

        # Apply B110 suppression and other transformations
        self._apply_packet_transformations(packet, observation)

        return packet

    def build_action_prompt(
        self,
        observation: ARC3Observation,
        memory_context: dict,
        step_history: List[dict],
        available_actions: List[str],
    ) -> str:
        """Render the final prompt string from a packet. B117"""
        packet = self.build_action_packet(observation, memory_context, step_history, available_actions)
        return packet.render()

    def _apply_packet_transformations(self, packet: PromptPacket, observation: ARC3Observation) -> None:
        """B110/B117: Apply programmatic transformations like observation suppression and deduplication."""
        obs_block = packet.get_block("OBSERVATION")
        effects_block = packet.get_block("OBSERVED_EFFECTS")
        instruction_block = packet.get_block("INSTRUCTION")

        # B110 logic: suppress OBSERVATION section if OBSERVED EFFECTS provides sufficient board context
        if obs_block and effects_block:
            effects_content = effects_block.content
            # Check if OBSERVED EFFECTS has rich board transition information
            has_board_context = (
                "Before board" in effects_content or
                "After board" in effects_content or
                "Changed region" in effects_content
            )

            if has_board_context:
                # Suppress the OBSERVATION block entirely when OBSERVED EFFECTS provides board context
                obs_block.content = ""
            else:
                # If effects lack board context, keep OBSERVATION but suppress coarse map detail
                obs_lines = obs_block.content.split("\n")
                filtered_obs = [l for l in obs_lines if "Coarse map" not in l and not l.startswith("0 ") and not l.startswith("1 ")]
                if len(filtered_obs) < len(obs_lines):
                    filtered_obs.append("(coarse map suppressed; see OBSERVED EFFECTS for board context)")
                obs_block.content = "\n".join(filtered_obs)

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

    @staticmethod
    def _normalize_action_id(action_id: Any) -> str | None:
        if action_id is None:
            return None
        text = str(action_id).strip().upper()
        if not text:
            return None
        if text.isdigit():
            return f"ACTION{text}"
        return text

    @staticmethod
    def _coerce_action6_coordinate(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            coordinate = int(value)
        except (TypeError, ValueError):
            return None
        return max(0, min(63, coordinate))

    def _candidate_action6_coordinates(self, observation: ARC3Observation) -> List[tuple[int, int]]:
        grid = observation.get("grid") or []
        if not grid or not isinstance(grid, list) or not isinstance(grid[0], list) or not grid[0]:
            return [(0, 0)]

        rows = len(grid)
        cols = len(grid[0])
        counts: dict[int, int] = {}
        for row in grid:
            for cell in row:
                value = int(cell)
                counts[value] = counts.get(value, 0) + 1
        background = max(counts.items(), key=lambda item: item[1])[0] if counts else 0

        non_background = [
            (x, y)
            for y, row in enumerate(grid)
            for x, cell in enumerate(row)
            if int(cell) != background
        ]
        center = (max(0, min(63, cols // 2)), max(0, min(63, rows // 2)))
        corners = [
            (0, 0),
            (max(0, min(63, cols - 1)), 0),
            (0, max(0, min(63, rows - 1))),
            (max(0, min(63, cols - 1)), max(0, min(63, rows - 1))),
        ]

        ordered: List[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for coord in non_background + [center] + corners:
            normalized = (max(0, min(63, int(coord[0]))), max(0, min(63, int(coord[1]))))
            if normalized not in seen:
                seen.add(normalized)
                ordered.append(normalized)
        return ordered or [(0, 0)]

    def _infer_action6_coordinates(self, observation: ARC3Observation) -> tuple[int, int]:
        candidates = self._candidate_action6_coordinates(observation)
        action6_attempts = [
            step for step in self._step_history
            if self._normalize_action_id(step.get("action_id")) == "ACTION6"
        ]
        used_coords = {
            (x, y)
            for step in action6_attempts
            for x, y in [
                (
                    self._coerce_action6_coordinate(step.get("x")),
                    self._coerce_action6_coordinate(step.get("y")),
                )
            ]
            if x is not None and y is not None
        }

        start_index = len(action6_attempts) % len(candidates)
        for offset in range(len(candidates)):
            coord = candidates[(start_index + offset) % len(candidates)]
            if coord not in used_coords:
                return coord
        return candidates[start_index]

    def _ensure_action6_coordinates(self, action: ARC3Action, observation: ARC3Observation) -> ARC3Action:
        normalized_id = self._normalize_action_id(action.get("action_id"))
        if normalized_id != "ACTION6":
            if normalized_id and normalized_id != action.get("action_id"):
                updated = dict(action)
                updated["action_id"] = normalized_id
                return updated
            return action

        updated = dict(action)
        updated["action_id"] = normalized_id
        x = self._coerce_action6_coordinate(updated.get("x"))
        y = self._coerce_action6_coordinate(updated.get("y"))
        inferred = x is None or y is None
        if inferred:
            x, y = self._infer_action6_coordinates(observation)
        updated["x"] = x
        updated["y"] = y

        rationale = str(updated.get("rationale") or "ACTION6 coordinate probe")
        coord_note = f"x={x}, y={y}"
        if coord_note not in rationale:
            prefix = f"{rationale}; " if rationale else ""
            reason = "targeting inferred coord" if inferred else "targeting coord"
            updated["rationale"] = f"{prefix}{reason} ({coord_note})"
        return updated

    async def _query_llm(self, prompt: str, available_actions: List[str]) -> ARC3Action:
        if not self.llm:
            return {"action_id": available_actions[0], "rationale": "system fallback"}
        messages = [
            {"role": "system", "content": QUERY_LLM_SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ]
        try:
            raw = await asyncio.to_thread(self.llm.chat, messages)
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError(f"Expected dict action payload, got {type(parsed).__name__}")

            action_id = self._normalize_action_id(parsed.get("action_id"))
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

            action: ARC3Action = {
                "action_id": action_id,
                "rationale": rationale,
            }
            x = self._coerce_action6_coordinate(parsed.get("x"))
            y = self._coerce_action6_coordinate(parsed.get("y"))
            if x is not None:
                action["x"] = x
            if y is not None:
                action["y"] = y
            return action
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("LLM action parse failed: %s", exc)
            return {"action_id": available_actions[0], "rationale": "fallback"}

    @staticmethod
    def _should_skip_chunk_action(effect: dict | None) -> bool:
        """Return True when the evidence says a chunk action has gone stale."""
        if not effect:
            return False

        value_status = str(effect.get("value_status") or "").lower()
        last_label = str(effect.get("last_meaningful_label") or "").lower()
        zero_reward_streak = int(effect.get("zero_reward_streak") or 0)
        no_progress_count = int(effect.get("no_progress_count") or 0)
        avg_change = float(effect.get("avg_meaningful_change") or 0.0)
        rank_score = float(effect.get("rank_score") or 0.0)

        if effect.get("over_retest_budget"):
            return True
        if value_status in {"low_value", "ineffective"}:
            return True
        if last_label in {"low_value", "no_progress"} and zero_reward_streak >= 2:
            return True
        if zero_reward_streak >= 3 and (no_progress_count > 0 or avg_change < 0.45 or rank_score < 0.20):
            return True
        return False

    def _enforce_action_policy(self, action: ARC3Action, available_actions: List[str]) -> ARC3Action:
        """Apply hard exploration guards and chunk enforcement (B109/B112)."""
        hyp_ctx = self._hypothesis_context or {}
        coverage = hyp_ctx.get("action_coverage") or {}
        unexplored = [
            candidate for candidate in coverage.get("untested_actions", [])
            if candidate in available_actions
        ]
        observed_effects = {
            effect.get("action"): effect
            for effect in hyp_ctx.get("observed_action_effects", [])
            if effect.get("action")
        }
        
        action_id = action.get("action_id")
        rationale = action.get("rationale") or ""

        # B109/B112: Prioritize guidance-grade chunk actions (bfs, directional)
        active_chunk = (self._solve_context or {}).get("active_chunk")
        if active_chunk and active_chunk.get("estimated_actions"):
            source = active_chunk.get("source", "unknown")
            suggested = active_chunk["estimated_actions"]
            
            # B112: Only hard-enforce guidance-grade sources (bfs, directional).
            # 'explore' chunks are descriptive hints, not strict constraints.
            if source == "bfs":
                # BFS is strict-sequential: only enforce if the very first planned action
                # is still available and hasn't already decayed into a stale low-value loop.
                first_planned = suggested[0] if suggested else None
                if first_planned and first_planned in available_actions and not self._should_skip_chunk_action(observed_effects.get(first_planned)):
                    chunk_action = first_planned
                    if self.solve_engine._active_chunk and self.solve_engine._active_chunk.estimated_actions:
                        try:
                            self.solve_engine._active_chunk.estimated_actions.remove(chunk_action)
                        except ValueError:
                            pass
                    if action_id != chunk_action:
                        return {
                            "action_id": chunk_action,
                            "rationale": f"policy override: enforcing bfs chunk '{active_chunk.get('description', '')}'. Original rationale: {rationale}",
                        }
                    return action
                # else: BFS first step blocked or stale; fall through to standard choice

            elif source == "directional":
                # Directional is loose: enforce the first available action that still has
                # credible signal, skipping blocked or stale low-value suggestions.
                valid_suggested = [a for a in suggested if a in available_actions]
                viable_suggested = [
                    candidate for candidate in valid_suggested
                    if not self._should_skip_chunk_action(observed_effects.get(candidate))
                ]
                if viable_suggested:
                    chunk_action = viable_suggested[0]
                    # Pop everything from index 0 to the enforced action (inclusive)
                    if self.solve_engine._active_chunk and self.solve_engine._active_chunk.estimated_actions:
                        chunk_list = self.solve_engine._active_chunk.estimated_actions
                        try:
                            idx = chunk_list.index(chunk_action)
                            del chunk_list[:idx + 1]
                        except ValueError:
                            pass
                    if action_id != chunk_action:
                        return {
                            "action_id": chunk_action,
                            "rationale": f"policy override: enforcing directional chunk '{active_chunk.get('description', '')}'. Original rationale: {rationale}",
                        }
                    return action
                elif valid_suggested and self.solve_engine._active_chunk and self.solve_engine._active_chunk.estimated_actions:
                    # Drop stale leading actions so the chunk doesn't keep re-forcing a loop.
                    chunk_list = self.solve_engine._active_chunk.estimated_actions
                    while chunk_list and (
                        chunk_list[0] not in available_actions
                        or self._should_skip_chunk_action(observed_effects.get(chunk_list[0]))
                    ):
                        chunk_list.pop(0)
            else:
                # B112: If it's an 'explore' chunk, we don't hard-enforce it, 
                # but we should still consume it if the LLM coincidentally picked it.
                if action_id == suggested[0]:
                    if self.solve_engine._active_chunk and self.solve_engine._active_chunk.estimated_actions:
                        self.solve_engine._active_chunk.estimated_actions.pop(0)

        # If no guidance chunk action, fall back to standard exploration policy
        if unexplored and action_id not in unexplored:
            forced = unexplored[0]
            
            # B112: If we are forcing an exploration action, check if it matches 
            # an 'explore' chunk suggestion so we consume it.
            if active_chunk and active_chunk.get("source") == "explore" and active_chunk.get("estimated_actions"):
                if forced == active_chunk["estimated_actions"][0]:
                    if self.solve_engine._active_chunk and self.solve_engine._active_chunk.estimated_actions:
                        self.solve_engine._active_chunk.estimated_actions.pop(0)

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

    async def _verify_candidate_action(
        self,
        action_id: str,
        rationale: str,
        observation: ARC3Observation,
        step_history: List[dict],
        hypothesis_context: dict,
    ) -> dict:
        """B126: Adversarial verification of candidate action before execution.

        Returns:
            {"approved": bool, "rejection_reason": str or None, "llm_response": str}
        """
        colors = observation.get("colors", [])
        shapes = observation.get("shapes", [])
        state = observation.get("state", "UNKNOWN")

        # Recent history summary
        recent_history_entries = []
        for step in step_history[-3:]:
            recent_history_entries.append(
                f"{step.get('action_id', 'UNKNOWN')}: reward={step.get('reward', '?')}"
            )
        recent_history = " → ".join(recent_history_entries) if recent_history_entries else "No history"

        # Sandbox context (if available from mental sandbox)
        sandbox_result = "Not used"
        thinking_trace = observation.get("_thinking_trace", [])
        if thinking_trace:
            sandbox_entry = next((t for t in thinking_trace if t.get("tool") == "sandbox_thought"), None)
            if sandbox_entry:
                sandbox_result = f"Tested {sandbox_entry.get('test_action')}: {sandbox_entry.get('result')}"

        # Loop detection
        loop_detected = hypothesis_context.get("loop_detected", False)

        # Action facts summary
        action_facts = hypothesis_context.get("action_facts", [])
        facts_for_action = [f for f in action_facts if f.get("action") == action_id]
        facts_summary = ""
        if facts_for_action:
            facts_summary = "; ".join([f"{f.get('action')} = {f.get('description')}" for f in facts_for_action[:2]])
        else:
            facts_summary = "Unknown behavior"

        # Build verifier prompt
        verifier_prompt = VERIFIER_PROMPT_TEMPLATE.format(
            action_id=action_id,
            rationale=rationale,
            state=state,
            colors=colors,
            shapes=shapes,
            recent_history=recent_history,
            sandbox_result=sandbox_result,
            loop_detected=loop_detected,
            action_facts_summary=facts_summary,
        )

        try:
            messages = [
                {"role": "system", "content": VERIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": verifier_prompt},
            ]
            raw = await asyncio.to_thread(self.llm.chat, messages)
            parsed = json.loads(raw)

            approval = parsed.get("approved", True)
            rejection_reason = parsed.get("reason") if not approval else None

            return {
                "approved": approval,
                "rejection_reason": rejection_reason,
                "llm_response": raw,
            }
        except Exception as exc:
            logger.warning("Verifier call failed: %s, defaulting to approval", exc)
            return {
                "approved": True,
                "rejection_reason": None,
                "llm_response": "",
            }

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

        # B124: Render chunk ledger as compact table
        ledger = sc.get("chunk_ledger") or []
        if ledger:
            lines.append("CHUNK LEDGER:")
            for entry in ledger[-8:]:  # Show last 8 entries
                status_sym = {
                    "completed": "✓",
                    "active": "→",
                    "pending": " ",
                    "failed": "✗",
                }.get(entry.get("status", "?"), "?")
                desc = entry.get("description", "")[:40]
                outcome = entry.get("outcome_summary", "")
                if outcome:
                    lines.append(f"  [{status_sym}] {desc} ({outcome})")
                else:
                    lines.append(f"  [{status_sym}] {desc}")

        if sc.get("dissonance"):
            lines.append(f"⚠ DISSONANCE: {sc['dissonance_reason']}")

        return "\n".join(lines)

    def _should_suppress_observation(self, effect_lines: List[str]) -> bool:
        """B110: Suppress OBSERVATION section if OBSERVED EFFECTS already provides board context.

        Returns True if we should skip the OBSERVATION section because OBSERVED EFFECTS
        contains sufficient board-state information (before/after snapshots, changed regions).
        """
        if not effect_lines:
            return False

        # Check if effect_lines contains board transition information
        effect_text = "\n".join(effect_lines)
        has_board_transition = (
            "Board transition:" in effect_text or
            "Before board" in effect_text or
            "Changed region" in effect_text or
            "before_snapshot" in effect_text or
            "after_snapshot" in effect_text
        )

        return has_board_transition

    def _format_instruction_section(self, hyp_ctx: dict | None) -> str:
        """B110: Instruction that refers to earlier sections instead of re-dumping effects.

        Avoids repeating the effect summary already in OBSERVED EFFECTS, but keeps
        the complete decision policy rules.
        """
        # B110: Skip effect summary since OBSERVED EFFECTS provides detailed context
        instruction = (
            "INSTRUCTION: What should you try next? "
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
        return instruction

    def _compose_final_prompt(self, sections: dict, observation: dict, step_history) -> str:
        """Render a pre-built sections dict into a single final prompt string (B110).

        Sections are ordered canonically. Headers are added for all sections
        except SYSTEM. Applies coarse-map suppression when OBSERVED_EFFECTS
        content is rich (>= 400 chars).
        """
        ordered_keys = [
            "SYSTEM", "STATE", "ENTITY_CONTEXT", "MEMORY", "SOLVE_CONTEXT", "PLAN",
            "OBSERVED_EFFECTS", "OBSERVATION", "ACTION_FACTS", "PATH_HYPOTHESIS", "INSTRUCTION",
        ]

        # Coarse-map suppression: when OBSERVED_EFFECTS is substantial, strip the
        # low-value coarse grid representation from OBSERVATION.
        observation_content = sections.get("OBSERVATION", "")
        if "OBSERVED_EFFECTS" in sections and len(sections["OBSERVED_EFFECTS"]) >= 400:
            coarse_idx = observation_content.find("Coarse map")
            if coarse_idx < 0:
                coarse_idx = observation_content.lower().find("coarse map")
            if coarse_idx >= 0:
                prefix = observation_content[:coarse_idx].rstrip()
                observation_content = prefix + "\n[coarse map suppressed: effects context is rich]"

        parts: list[str] = []
        seen = set()
        for key in ordered_keys:
            content = observation_content if key == "OBSERVATION" else sections.get(key, "")
            if not content:
                continue
            seen.add(key)
            if key == "SYSTEM":
                parts.append(content)
            else:
                parts.append(f"=== {key} ===")
                parts.append(content)

        # Any sections not in the canonical list, append at end
        for key, content in sections.items():
            if key not in seen and content:
                parts.append(f"=== {key} ===")
                parts.append(content)

        return "\n".join(parts)

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
                f"COVERAGE: Exploration coverage: "
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

    def _format_hypothesis_section(self, hyp_ctx: dict | None) -> List[str]:
        if not hyp_ctx:
            return []
        lines: List[str] = []
        for key, label in (
            ("confirmed_hypotheses", "CONFIRMED"),
            ("active_hypotheses", "ACTIVE"),
        ):
            for hyp in hyp_ctx.get(key, [])[: self.MAX_PROMPT_HYPOTHESES]:
                lines.append(
                    f"{label}: {hyp.get('description', 'unknown')} "
                    f"(conf {hyp.get('confidence', 0.0):.2f})"
                )
        for hyp in hyp_ctx.get("pruned_hypotheses", [])[: self.MAX_PROMPT_HYPOTHESES]:
            lines.append(
                f"PRUNED: {hyp.get('description', 'unknown')} "
                f"(conf {hyp.get('confidence', 0.0):.2f})"
            )
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

    def _format_compaction_section(self) -> str:
        """B116: EXPLORATION_SUMMARY - compact knowledge from long exploration runs."""
        if not self._compaction_artifact:
            return ""
        art = self._compaction_artifact
        lines = []
        if art.action_summaries:
            lines.append("KNOWN ACTION EFFECTS:")
            for action, summary in art.action_summaries.items():
                lines.append(f"  {summary}")
        if art.known_loops:
            lines.append("KNOWN LOOPS (sequences to avoid):")
            for loop in art.known_loops[:3]:
                lines.append(f"  {' -> '.join(loop)}")
        if art.confirmed_rules:
            lines.append("CONFIRMED RULES:")
            for rule in art.confirmed_rules[:3]:
                lines.append(f"  {rule}")
        return "\n".join(lines)

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
        
        # B120: Annotate color summary with roles
        if colors:
            color_parts = []
            for c in colors[:6]:
                cid = c["value"]
                part = f"{cid}:{c['count']}"
                entity = self._entity_map.get(cid) if self._entity_map else None
                if entity and entity["role"] != "unknown":
                    part += f"({entity['role']})"
                color_parts.append(part)
            color_summary = ", ".join(color_parts)
        else:
            color_summary = "none"

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
            self._consecutive_no_progress_steps += 1
        else:
            self._consecutive_no_progress_steps = 0

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
            "pruning_decisions": list(self._pruning_decisions),
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

        # B120: Entity role annotations
        if self._entity_map:
            entity_annotations = []
            for color_info in colors[:6]:
                cid = color_info["value"] if isinstance(color_info, dict) else color_info
                entity = self._entity_map.get(cid)
                if entity and entity["role"] != "unknown":
                    annotation = f"color {cid} = {entity['role']}"
                    if entity.get("position"):
                        annotation += f" at row {entity['position']['row']:.0f}, col {entity['position']['col']:.0f}"
                    entity_annotations.append(annotation)
            entity_desc = "; ".join(entity_annotations) if entity_annotations else "pending"
        else:
            entity_desc = "pending"

        return (
            f"[PUZZLE STRUCTURE] Task {observation['task_id']} from {observation['dataset_id']}. "
            f"Grid: {rows}x{cols}. State: {state}. Energy: {energy:.0%}. "
            f"Frame hash: {frame_hash}. "
            f"Colors: {color_desc}. "
            f"Entity roles: {entity_desc}. "
            f"Shapes ({len(shapes)}): {shape_desc}. "
            f"Available actions: {', '.join(available) if available else 'pending'}. "
            f"Spatial sketch 4x4: {spatial_sketch or '(empty)'}."
        )
