"""Durable ARC run driver tying orchestrator + checkpoints + harness."""

from __future__ import annotations

import inspect
import json
import logging
import re
import time
import uuid
import hashlib
import subprocess
import asyncio
from dataclasses import asdict
from typing import Any, Callable, List, Mapping, Optional

from benchmarks.ab_harness import ABTask, ABTaskResult, ABVariant
from benchmarks.arc3.adapter import ARC3Adapter, BrainClientProtocol, LedgerBrainClient
from benchmarks.arc3.harness import ARC3Harness
from benchmarks.arc3.outcome_judge import OutcomeJudge
from benchmarks.arc3.trajectory_eval import TrajectoryEvaluator
from mcp_engine.llm.provider import create_llm_client
from agents.arc3.checkpoint import CheckpointManager
from agents.arc3.failure_taxonomy import classify_failure
from agents.arc3.orchestrator import ARCOrchestrator
from agents.arc3.scheduler import PuzzleScheduler
from agents.arc3.strategy_racer import race as strategy_race

logger = logging.getLogger(__name__)


class DurableARCRunner:
    """Crash-safe scorecard driver with SideQuests orchestrator."""

    def __init__(
        self,
        harness: ARC3Harness,
        brain_client: BrainClientProtocol,
        config: dict,
        progress_callback: Callable[[dict], None] | None = None,
    ):
        self.harness = harness
        self._raw_brain = brain_client
        self.config = config
        self._ledger: List[dict] = []
        self._current_step = 0
        self._progress_callback = progress_callback
        self._last_replan_step: int = -999
        self._replan_backoff_steps: int = 3
        
        self.brain = LedgerBrainClient(
            inner=brain_client,
            ledger=self._ledger,
            step_provider=lambda: self._current_step,
            cost_tracker=None
        )

        # B181: Outcome Judge initialization
        judge_cfg = config.get("judge")
        if judge_cfg:
            judge_llm = create_llm_client({"llm": judge_cfg})
            self.outcome_judge = OutcomeJudge(judge_llm) if judge_llm else None
        else:
            self.outcome_judge = None

        self.trajectory_evaluator = TrajectoryEvaluator()

    async def run(self, tasks: List[ABTask], card_id: str) -> List[dict]:
        mgr = CheckpointManager(card_id)
        checkpoint = mgr.load_or_create(tasks)
        results: List[dict] = []

        # B189: Puzzle Scheduler
        graph_id = None
        try:
            # B190: Register task graph
            try:
                tasks_meta = [
                    {"task_id": t.task_id, "label": f"ARC puzzle {t.task_id}"}
                    for t in tasks
                ]
                reg = await self._raw_brain.register_task_graph(
                    label=f"ARC batch {card_id}",
                    session_id=card_id,
                    owner=(self.config.get("owner") if isinstance(self.config, dict) else "arc-runner"),
                    tasks=tasks_meta,
                )
                graph_id = reg.get("graph_id") if isinstance(reg, Mapping) else None
            except Exception:
                logger.exception("B190: Failed to register task graph for batch %s", card_id)

            concurrency = 1
            skip_solved = True
            if isinstance(self.config, dict):
                concurrency = int(self.config.get("concurrency", 1))
                skip_solved = bool(self.config.get("skip_solved", True))
            
            scheduler = PuzzleScheduler(concurrency=concurrency, skip_solved=skip_solved, brain_client=self._raw_brain)
            ordered_tasks = await scheduler.prepare(tasks)
        except Exception:
            logger.exception("B189: Failed to prepare puzzle scheduling, falling back to original order")
            ordered_tasks = list(tasks)

        async def _run_single_task(task: ABTask) -> Optional[dict]:
            tc = checkpoint.tasks.get(task.task_id)
            if tc and tc.status == "complete":
                if not self._has_terminal_payload(tc.result):
                    logger.info("Checkpoint for %s is stale. Re-running.", task.task_id)
                    tc.status = "pending"
                    tc.result = None
                    mgr.save(checkpoint)
                else:
                    return self._submission_row_from_result(tc.result or {})

            session_id = f"arc-{task.task_id}-{uuid.uuid4().hex[:8]}"
            self.brain.current_phase = "bootstrap"
            self._current_step = 0
            puzzle_start_time = time.time()

            # B180: Token cost tracking and budget enforcement
            from agents.arc3.cost_tracker import CostTracker
            cost_cfg = {}
            llm_cfg = {}
            if type(self.config) is dict:
                cost_cfg = self.config.get("cost", {})
                llm_cfg = self.config.get("llm", {})
            
            model_name = llm_cfg.get("model", "unknown") if isinstance(llm_cfg, dict) else "unknown"
            pricing = {}
            if isinstance(cost_cfg, dict):
                pricing = cost_cfg.get("pricing_per_million_tokens", {}).get(model_name, {"input": 0.0, "output": 0.0})
            
            budget = float('inf')
            if isinstance(cost_cfg, dict):
                val = cost_cfg.get("budget_per_puzzle_usd")
                if val is not None:
                    try:
                        budget = float(val)
                    except (TypeError, ValueError):
                        budget = float('inf')

            cost_tracker = CostTracker(
                model_name=str(model_name),
                input_price_per_m=float(pricing.get("input", 0.0) if isinstance(pricing, dict) else 0.0),
                output_price_per_m=float(pricing.get("output", 0.0) if isinstance(pricing, dict) else 0.0),
                budget_usd=budget
            )

            self.brain = LedgerBrainClient(
                inner=self._raw_brain,
                ledger=self._ledger,
                step_provider=lambda: self._current_step,
                start_time=puzzle_start_time,
                cost_tracker=cost_tracker
            )

            # B190: Store per-puzzle sidequest
            branch_result = await self.brain.branch_quest(
                name=f"ARC puzzle {task.task_id}",
                purpose=f"Solve ARC-AGI-3 task {task.task_id}",
                parent_quest_id=card_id,
            )
            # Some tests patch `LedgerBrainClient.branch_quest`, which bypasses
            # its internal ledger recording. Backfill the bootstrap event here.
            if not any((entry.get("call_type") == "branch_quest") for entry in self._ledger if isinstance(entry, dict)):
                self._ledger.append({
                    "step": self._current_step,
                    "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "elapsed_mmss": "00:00",
                    "phase": "bootstrap",
                    "call_type": "branch_quest",
                    "mode": "write",
                    "input_summary": f"ARC puzzle {task.task_id}",
                    "result_summary": f"side_quest_id={(branch_result or {}).get('side_quest_id') if isinstance(branch_result, Mapping) else None}",
                    "latency_ms": 0.0,
                })

            # Create the per-puzzle orchestrator for the default single-run flow,
            # but if strategy racing is enabled we will launch several variants
            # via StrategyRacer instead of running a single orchestrator here.
            if isinstance(self.config, dict) and self.config.get("strategy_racing", False):
                async def _variant_runner(variant_brain, session_id_v, task_arg, vcfg):
                    # Build per-variant cost tracker and orchestrator, then run it
                    from agents.arc3.cost_tracker import CostTracker

                    llm_cfg_v = vcfg.get("llm", {}) if isinstance(vcfg, dict) else {}
                    model_name_v = llm_cfg_v.get("model", "unknown") if isinstance(llm_cfg_v, dict) else "unknown"
                    pricing_v = {}
                    if isinstance(vcfg.get("cost", {}), dict):
                        pricing_v = vcfg.get("cost", {}).get("pricing_per_million_tokens", {}).get(model_name_v, {"input": 0.0, "output": 0.0})

                    budget_v = float('inf')
                    try:
                        val = (vcfg.get("cost") or {}).get("budget_per_puzzle_usd")
                        if val is not None:
                            budget_v = float(val)
                    except Exception:
                        budget_v = float('inf')

                    cost_tracker_v = CostTracker(
                        model_name=str(model_name_v),
                        input_price_per_m=float(pricing_v.get("input", 0.0) if isinstance(pricing_v, dict) else 0.0),
                        output_price_per_m=float(pricing_v.get("output", 0.0) if isinstance(pricing_v, dict) else 0.0),
                        budget_usd=budget_v,
                    )

                    # B197: Attempt to load proven procedures for this variant before orchestrator creation
                    procedures = []
                    try:
                        archetype_hint = (getattr(task_arg, 'game_id', None) or 'unknown')
                        proc_resp = await variant_brain.recall_procedures(archetype=archetype_hint, limit=3)
                        if isinstance(proc_resp, Mapping):
                            procedures = proc_resp.get('procedures') or []
                    except Exception:
                        logger.debug("recall_procedures lookup failed for variant")

                    # B199: Check knowledge gaps to influence exploration budget
                    multiplier = 1.0
                    try:
                        gaps_resp = await variant_brain.get_knowledge_gaps(domain=archetype_hint)
                        if isinstance(gaps_resp, Mapping):
                            gaps = gaps_resp.get('gaps') or []
                            # If there are missing-lessons gaps for this archetype, increase exploration
                            has_gap = any((g.get('gap_type') == 'missing_lessons') for g in gaps)
                            if has_gap:
                                multiplier = 2.0
                    except Exception:
                        logger.debug("get_knowledge_gaps lookup failed for variant")

                    vcfg2 = dict(vcfg) if isinstance(vcfg, dict) else {}
                    vcfg2["loaded_procedures"] = procedures
                    vcfg2["exploration_budget_multiplier"] = multiplier

                    orchestrator_v = ARCOrchestrator(
                        brain_client=variant_brain,
                        llm_client=self.harness.llm_client,
                        session_id=session_id_v,
                        serializer=self.harness.serializer,
                        config=vcfg2,
                        cost_tracker=cost_tracker_v,
                    )
                    return await self._run_puzzle_with_brain(orchestrator_v, task_arg, variant_brain, vcfg)

                winner = await strategy_race(self, task, variants=self.config.get("strategy_racing_variants", ["A", "B", "C"]), variant_runner=_variant_runner)
                task_result = winner.get("task_result")
                duration = winner.get("duration")
                orchestrator = winner.get("orchestrator")
                # Merge winning ledger into the driver's ledger so subsequent code can use it
                try:
                    winner_ledger = winner.get("ledger") or []
                    self._ledger.extend(list(winner_ledger))
                except Exception:
                    logger.exception("Failed merging winner ledger")

                result_payload = asdict(task_result)
                result_payload["solve_phase_summary"] = {}
                result_payload["game_id"] = getattr(task, "game_id", "unknown")
                result_payload["runtime_seconds"] = round(duration, 2)
                result_payload["benchmark_metrics"] = getattr(task_result, "benchmark_metrics", {})
                result_payload["entity_gate_status"] = getattr(orchestrator, "_entity_gate_result", {}) or {"status": "pass"}
                result_payload["bootstrap_write_trace"] = getattr(task_result, "bootstrap_write_trace", [])
                result_payload["final_write_trace"] = getattr(task_result, "final_write_trace", [])
                result_payload["debug_steps"] = list(getattr(orchestrator, "_step_history", []))
                result_payload["sidequests_ledger"] = list(self._ledger)
                result_payload["arc_event_timeline"] = list(getattr(self.brain, "arc_event_timeline", []))
                result_payload["agent_execution_trace"] = getattr(orchestrator, "_execution_trace", [])

                self._ledger.clear()

                traj = self._build_trajectory_summary(orchestrator)
                try:
                    await self._report_puzzle_outcome(orchestrator=orchestrator, task=task, task_result=task_result, session_id=session_id)
                    if graph_id:
                        await self.brain.advance_task(graph_id=graph_id, task_id=task.task_id, status="complete", result=task_result.final_state)
                except Exception:
                    logger.exception("B190: best-effort lesson/advance failed")

                mgr.mark_complete(checkpoint, task.task_id, getattr(orchestrator, "_plan_id", None), result_payload)
                return self._submission_row_from_result(result_payload)
            else:
                # B197: Pre-solve procedure lookup
                procedures = []
                try:
                    archetype_hint = getattr(task, 'game_id', None) or 'unknown'
                    proc_resp = await self.brain.recall_procedures(archetype=archetype_hint, limit=3)
                    if isinstance(proc_resp, Mapping):
                        procedures = proc_resp.get('procedures') or []
                except Exception:
                    logger.debug("recall_procedures lookup failed")

                # B199: Knowledge gap check to influence exploration budget
                multiplier = 1.0
                try:
                    gaps_resp = await self.brain.get_knowledge_gaps(domain=archetype_hint)
                    if isinstance(gaps_resp, Mapping):
                        gaps = gaps_resp.get('gaps') or []
                        has_gap = any((g.get('gap_type') == 'missing_lessons') for g in gaps)
                        if has_gap:
                            multiplier = 2.0
                except Exception:
                    logger.debug("get_knowledge_gaps lookup failed")

                cfg2 = dict(self.config) if isinstance(self.config, dict) else {}
                cfg2["loaded_procedures"] = procedures
                cfg2["exploration_budget_multiplier"] = multiplier

                orchestrator = ARCOrchestrator(
                    brain_client=self.brain,
                    llm_client=self.harness.llm_client,
                    session_id=session_id,
                    serializer=self.harness.serializer,
                    config=cfg2,
                    cost_tracker=cost_tracker,
                )

                try:
                    task_result, duration = await self._run_puzzle(orchestrator, task)
                    result_payload = asdict(task_result)
                    result_payload["solve_phase_summary"] = {}
                    result_payload["game_id"] = getattr(task, "game_id", "unknown")
                    result_payload["runtime_seconds"] = round(duration, 2)
                    result_payload["benchmark_metrics"] = getattr(task_result, "benchmark_metrics", {})
                    result_payload["entity_gate_status"] = getattr(orchestrator, "_entity_gate_result", {}) or {"status": "pass"}
                    result_payload["bootstrap_write_trace"] = getattr(task_result, "bootstrap_write_trace", [])
                    result_payload["final_write_trace"] = getattr(task_result, "final_write_trace", [])
                    result_payload["debug_steps"] = list(getattr(orchestrator, "_step_history", []))
                    result_payload["sidequests_ledger"] = list(self._ledger)
                    result_payload["arc_event_timeline"] = list(getattr(self.brain, "arc_event_timeline", []))
                    result_payload["agent_execution_trace"] = getattr(orchestrator, "_execution_trace", [])
                    
                    self._ledger.clear()

                    traj = self._build_trajectory_summary(orchestrator)
                    try:
                        await self._report_puzzle_outcome(orchestrator=orchestrator, task=task, task_result=task_result, session_id=session_id)
                        if graph_id:
                            await self.brain.advance_task(graph_id=graph_id, task_id=task.task_id, status="complete", result=task_result.final_state)
                    except Exception:
                        logger.exception("B190: best-effort lesson/advance failed")

                    mgr.mark_complete(checkpoint, task.task_id, orchestrator._plan_id, result_payload)
                    return self._submission_row_from_result(result_payload)
                except Exception as exc:
                    failure_class = classify_failure(
                        exc=exc,
                        final_state=(
                            (getattr(orchestrator, "_step_history", [])[-1] or {}).get("state_after")
                            if getattr(orchestrator, "_step_history", None)
                            else None
                        ),
                        error_message=str(exc),
                        no_progress_steps=int(getattr(orchestrator, "_consecutive_no_progress_steps", 0) or 0),
                        budget_exhausted=bool(
                            getattr(getattr(orchestrator, "cost_tracker", None), "budget_exhausted", False) is True
                        ),
                        loop_detected=bool((getattr(orchestrator, "_hypothesis_context", {}) or {}).get("loop_detected")),
                    )
                    mgr.mark_failed(checkpoint, task.task_id, str(exc), failure_class.value)
                    logger.error("Task %s failed [%s]: %s", task.task_id, failure_class.value, exc)
                    return None

        batch_results = await scheduler.run_batch(ordered_tasks, _run_single_task)
        results = [r for r in batch_results if r is not None]
        return results

    def _has_terminal_payload(self, result: dict | None) -> bool:
        if not isinstance(result, dict): return False
        grid = (result.get("final_observation") or {}).get("grid")
        return isinstance(grid, list) and len(grid) > 0

    async def _run_puzzle(self, orchestrator: ARCOrchestrator, task: ABTask) -> tuple[ABTaskResult, float]:
        max_steps = self.harness.config.parameters.get("max_attempts_per_puzzle", 10)
        max_retries = self.config.get("max_retries_per_puzzle", 3)
        if getattr(orchestrator, "_supervisor", None) is not None:
            try:
                orchestrator._supervisor.abandon_zero_reward_steps = min(
                    int(getattr(orchestrator._supervisor, "abandon_zero_reward_steps", 30)),
                    max(5, int(max_steps) - 2),
                )
            except Exception:
                logger.debug("Unable to align supervisor threshold with max steps", exc_info=True)
        adapter = ARC3Adapter(
            brain_client=self.brain,
            session_id=orchestrator.session_id,
            task_id=task.task_id,
        )
        game_id = getattr(task, "game_id", "unknown")

        start_time = time.time()
        total_steps = 0
        success = False
        done = False
        error_msg: str | None = None
        total_tokens_in = 0
        total_tokens_out = 0
        last_grid = None
        last_reward = 0.0
        consecutive_no_progress_steps = 0
        bootstrap_write_trace: list[dict] = []
        final_write_trace: list[dict] = []

        for attempt in range(1, max_retries + 1):
            frame_response, guid = await self._initial_frame(game_id)
            observation = adapter.normalize_observation(frame_response)
            last_grid = observation.get("grid")

            training_examples = observation.get("training_examples") or []
            if training_examples:
                try:
                    phase1_result = await orchestrator.run_phase1(observation, training_examples)
                    if phase1_result and phase1_result.get("verified"):
                        orchestrator._verified_output_grid = phase1_result["output_grid"]
                        orchestrator._phase2_mode = "execution"
                except Exception:
                    logger.exception("B156: Phase 1 failed")

            self.brain.current_phase = "bootstrap"
            self._current_step = 0
            if hasattr(orchestrator, "set_write_trace_context"):
                orchestrator.set_write_trace_context("bootstrap")
            memory_context = await orchestrator.perceive(observation, step=0)
            await orchestrator.plan(observation, memory_context)
            if hasattr(orchestrator, "consume_write_trace"):
                bootstrap_write_trace = list(orchestrator.consume_write_trace())

            state = observation.get("state", "NOT_FINISHED")
            steps_this_attempt = 0

            while steps_this_attempt < max_steps:
                budget_exhausted = bool(
                    getattr(orchestrator.cost_tracker, "budget_exhausted", False) is True
                ) if getattr(orchestrator, "cost_tracker", None) else False
                if orchestrator.cost_tracker and budget_exhausted:
                    error_msg = "Budget exhausted"
                    done = True
                    break

                if getattr(orchestrator, "_should_abandon", False):
                    error_msg = "Supervisor abandoned"
                    done = True
                    break

                self.brain.current_phase = "hypothesize"
                self._current_step = total_steps + 1
                prior_step = orchestrator._step_history[-1] if getattr(orchestrator, "_step_history", None) else None
                hyp_ctx = await orchestrator.hypothesize(
                    observation,
                    prior_step.get("action_id") if prior_step else None,
                    total_steps,
                    transition_meta=prior_step,
                )

                self.brain.current_phase = "solve"
                await orchestrator.solve(observation, hyp_ctx, total_steps)

                self.brain.current_phase = "act"
                action = await orchestrator.act(observation, memory_context, total_steps + 1)

                total_tokens_in += self.harness.serializer._estimate_tokens(json.dumps(observation))
                total_tokens_out += self.harness.serializer._estimate_tokens(str(action))

                frame_response, reward, done, guid = await self._execute_action(game_id, guid, action, total_steps)

                recall_query = None
                if total_steps == 0 or consecutive_no_progress_steps >= 2:
                    recall_query = "What did I learn from similar puzzles?"

                self.brain.current_phase = "ingest"
                await adapter.ingest_step(frame_response, action, reward=reward, recall_query=recall_query)
                observation = adapter.normalize_observation(frame_response)
                orchestrator.record_step_result(reward, done, next_observation=observation)

                if reward > last_reward:
                    consecutive_no_progress_steps = 0
                    last_reward = reward
                else:
                    consecutive_no_progress_steps += 1

                state = observation.get("state", "NOT_FINISHED")
                if getattr(orchestrator, "_step_history", None):
                    orchestrator._step_history[-1].update(
                        {"state_after": state, "reward": reward, "done": done}
                    )

                total_steps += 1
                steps_this_attempt += 1
                self._emit_progress_snapshot(
                    task=task,
                    orchestrator=orchestrator,
                    observation=observation,
                    total_steps=total_steps,
                    reward=reward,
                    done=done,
                    start_time=start_time,
                )

                if state == "WIN":
                    success = True
                    break
                elif state == "GAME_OVER":
                    if attempt < max_retries and hasattr(orchestrator, "reset_for_retry"):
                        orchestrator.reset_for_retry(attempt)
                    break
                elif done:
                    success = reward >= 1.0 or state == "WIN"
                    break

            if success:
                break
            if state != "GAME_OVER":
                break

        if not success and total_steps >= max_steps * max_retries:
            error_msg = "Max attempts reached across all retries"
        elif not success and not error_msg:
            error_msg = f"Failed after {attempt} attempt(s)"

        duration = time.time() - start_time

        judge_verdict = None
        if self.outcome_judge and task.reference_solution:
            try:
                expected = json.loads(task.reference_solution)
                trajectory = self._build_trajectory_summary(orchestrator)
                archetype = getattr(getattr(orchestrator.solve_engine, "_archetype", None), "value", "unknown")
                verdict = await self.outcome_judge.evaluate(
                    observation.get("grid"), expected, trajectory, archetype
                )
                if verdict:
                    judge_verdict = asdict(verdict)
            except Exception:
                logger.exception("B181 failed")

        benchmark_metrics = {}
        if hasattr(orchestrator, "get_benchmark_metrics"):
            try:
                benchmark_metrics = orchestrator.get_benchmark_metrics()
            except Exception:
                logger.exception("B89: get_benchmark_metrics failed")

        trajectory_score = None
        try:
            trajectory_score = self.trajectory_evaluator.evaluate(
                trace=list(getattr(orchestrator, "_execution_trace", [])),
                step_history=list(getattr(orchestrator, "_step_history", [])),
            ).to_dict()
        except Exception:
            logger.exception("B186: trajectory evaluation failed")

        failure_class = None
        if not success:
            failure_class = classify_failure(
                exc=None,
                final_state=state,
                error_message=error_msg,
                no_progress_steps=max(
                    consecutive_no_progress_steps,
                    int(getattr(orchestrator, "_consecutive_no_progress_steps", 0) or 0),
                ),
                budget_exhausted=bool(
                    getattr(orchestrator.cost_tracker, "budget_exhausted", False) is True
                ) if getattr(orchestrator, "cost_tracker", None) else False,
                max_steps_reached=(total_steps >= max_steps * max_retries),
                loop_detected=bool((getattr(orchestrator, "_hypothesis_context", {}) or {}).get("loop_detected")),
            ).value

        task_result = ABTaskResult(
            task_id=task.task_id,
            variant=ABVariant.SIDEQUESTS,
            correct=success,
            steps=total_steps,
            tokens_input=total_tokens_in,
            tokens_output=total_tokens_out,
            error_message=error_msg,
            failure_class=failure_class,
            response_text=f"Solved: {success} in {total_steps} steps ({attempt} attempt(s))",
            attempts=attempt,
            dissonance_triggered=bool((getattr(orchestrator, "_solve_context", {}) or {}).get("dissonance")),
            trajectory_score=trajectory_score,
            final_state=state,
            final_observation=observation,
            judge_verdict=judge_verdict,
        )
        setattr(task_result, "bootstrap_write_trace", bootstrap_write_trace)
        setattr(task_result, "final_write_trace", final_write_trace)
        setattr(task_result, "benchmark_metrics", benchmark_metrics)
        setattr(task_result, "sidequests_ledger", list(self._ledger))
        return task_result, duration

    async def _run_puzzle_with_brain(self, orchestrator: ARCOrchestrator, task: ABTask, brain_client: BrainClientProtocol, variant_config: dict) -> tuple[ABTaskResult, float, ARCOrchestrator]:
        """Run a single puzzle using the provided `brain_client` and `variant_config`.

        This variant of `_run_puzzle` avoids mutating the DurableARCRunner instance
        (no changes to `self.brain` or `self._ledger`) so it is safe to run
        concurrently from StrategyRacer.
        Returns `(ABTaskResult, duration, orchestrator)`.
        """
        from agents.arc3.cost_tracker import CostTracker

        max_steps = self.harness.config.parameters.get("max_attempts_per_puzzle", 10)
        max_retries = variant_config.get("max_retries_per_puzzle", self.config.get("max_retries_per_puzzle", 3))
        if getattr(orchestrator, "_supervisor", None) is not None:
            try:
                orchestrator._supervisor.abandon_zero_reward_steps = min(
                    int(getattr(orchestrator._supervisor, "abandon_zero_reward_steps", 30)),
                    max(5, int(max_steps) - 2),
                )
            except Exception:
                logger.debug("Unable to align supervisor threshold with max steps", exc_info=True)
        adapter = ARC3Adapter(
            brain_client=brain_client,
            session_id=orchestrator.session_id,
            task_id=task.task_id,
        )
        game_id = getattr(task, "game_id", "unknown")

        start_time = time.time()
        total_steps = 0
        success = False
        done = False
        error_msg: str | None = None
        total_tokens_in = 0
        total_tokens_out = 0
        last_grid = None
        last_reward = 0.0
        consecutive_no_progress_steps = 0
        bootstrap_write_trace: list[dict] = []
        final_write_trace: list[dict] = []

        # B180: Token cost tracking and budget enforcement (variant_config aware)
        cost_cfg = {}
        llm_cfg = {}
        if isinstance(variant_config, dict):
            cost_cfg = variant_config.get("cost", {})
            llm_cfg = variant_config.get("llm", {})

        model_name = llm_cfg.get("model", "unknown") if isinstance(llm_cfg, dict) else "unknown"
        pricing = {}
        if isinstance(cost_cfg, dict):
            pricing = cost_cfg.get("pricing_per_million_tokens", {}).get(model_name, {"input": 0.0, "output": 0.0})

        budget = float('inf')
        if isinstance(cost_cfg, dict):
            val = cost_cfg.get("budget_per_puzzle_usd")
            if val is not None:
                try:
                    budget = float(val)
                except (TypeError, ValueError):
                    budget = float('inf')

        cost_tracker = CostTracker(
            model_name=str(model_name),
            input_price_per_m=float(pricing.get("input", 0.0) if isinstance(pricing, dict) else 0.0),
            output_price_per_m=float(pricing.get("output", 0.0) if isinstance(pricing, dict) else 0.0),
            budget_usd=budget,
        )

        # Ensure the orchestrator sees the same cost tracker used by the driver
        orchestrator.cost_tracker = cost_tracker

        async def _initial_frame_variant(game_id: str) -> tuple[dict, str | None]:
            start_t = time.time()
            if self.harness.mock_api:
                frame = self.harness._get_mock_initial_frame(game_id)
                if hasattr(brain_client, "record_arc_api_call"):
                    brain_client.record_arc_api_call(
                        phase=getattr(brain_client, "current_phase", "bootstrap"),
                        method="GET",
                        endpoint="/api/games/initial",
                        request_payload={"game_id": game_id},
                        response_payload=frame,
                        latency_ms=(time.time() - start_t) * 1000,
                    )
                return frame, frame.get("guid")

            session = getattr(self.harness, "_session", None)
            if session is None:
                raise RuntimeError("ARC API session not initialized. Did you call harness.setup()?")

            sc_start = time.time()
            sc_resp = await session.post("/api/scorecard/open", json={})
            sc_latency = (time.time() - sc_start) * 1000
            await self._safe_raise_for_status(sc_resp)
            sc_json = await self._safe_json(sc_resp)
            card_id = sc_json["card_id"]
            if hasattr(brain_client, "record_arc_api_call"):
                brain_client.record_arc_api_call(
                    phase=getattr(brain_client, "current_phase", "bootstrap"),
                    method="POST",
                    endpoint="/api/scorecard/open",
                    request_payload={},
                    response_payload=sc_json,
                    latency_ms=sc_latency,
                )

            reset_start = time.time()
            reset_payload = {"game_id": game_id, "card_id": card_id}
            reset_resp = await session.post("/api/cmd/RESET", json=reset_payload)
            reset_latency = (time.time() - reset_start) * 1000
            await self._safe_raise_for_status(reset_resp)
            frame = await self._safe_json(reset_resp)
            if hasattr(brain_client, "record_arc_api_call"):
                brain_client.record_arc_api_call(
                    phase=getattr(brain_client, "current_phase", "bootstrap"),
                    method="POST",
                    endpoint="/api/cmd/RESET",
                    request_payload=reset_payload,
                    response_payload=frame,
                    latency_ms=reset_latency,
                )
            return frame, frame.get("guid")

        async def _execute_action_variant(game_id: str, guid: str | None, action: Mapping[str, Any], step: int) -> tuple[dict, float, bool, str | None]:
            start_t = time.time()
            if self.harness.mock_api:
                frame, reward, done = self.harness._execute_mock_action(game_id, action, step)
                if hasattr(brain_client, "record_arc_api_call"):
                    brain_client.record_arc_api_call(
                        phase=getattr(brain_client, "current_phase", "act"),
                        method="POST",
                        endpoint=f"/api/cmd/{action.get('action_id', 'unknown')}",
                        request_payload=action,
                        response_payload=frame,
                        latency_ms=(time.time() - start_t) * 1000,
                    )
                return frame, reward, done, frame.get("guid", guid)

            session = getattr(self.harness, "_session", None)
            if session is None:
                raise RuntimeError("ARC API session not initialized. Did you call harness.setup()?")

            action_id = action.get("action_id", "ACTION1")
            payload = {"game_id": game_id, "guid": guid}
            if action_id == "ACTION6":
                payload["x"] = action.get("x", 0)
                payload["y"] = action.get("y", 0)
            if "rationale" in action:
                payload["reasoning"] = action["rationale"]

            call_start = time.time()
            action_resp = await session.post(f"/api/cmd/{action_id}", json=payload)
            latency = (time.time() - call_start) * 1000
            await self._safe_raise_for_status(action_resp)
            frame = await self._safe_json(action_resp)
            if hasattr(brain_client, "record_arc_api_call"):
                brain_client.record_arc_api_call(
                    phase=getattr(brain_client, "current_phase", "act"),
                    method="POST",
                    endpoint=f"/api/cmd/{action_id}",
                    request_payload=payload,
                    response_payload=frame,
                    latency_ms=latency,
                )
            reward = 1.0 if frame.get("state") == "WIN" else 0.0
            done = frame.get("state") in ("WIN", "GAME_OVER")
            return frame, reward, done, frame.get("guid", guid)

        for attempt in range(1, max_retries + 1):
            frame_response, guid = await _initial_frame_variant(game_id)
            observation = adapter.normalize_observation(frame_response)
            last_grid = observation.get("grid")

            training_examples = observation.get("training_examples") or []
            if training_examples:
                try:
                    phase1_result = await orchestrator.run_phase1(observation, training_examples)
                    if phase1_result and phase1_result.get("verified"):
                        orchestrator._verified_output_grid = phase1_result["output_grid"]
                        orchestrator._phase2_mode = "execution"
                except Exception:
                    logger.exception("B156: Phase 1 failed")

            brain_client.current_phase = "bootstrap"
            # Do not modify shared self._current_step here; keep local counters
            memory_context = await orchestrator.perceive(observation, step=0)
            await orchestrator.plan(observation, memory_context)
            if hasattr(orchestrator, "consume_write_trace"):
                bootstrap_write_trace = list(orchestrator.consume_write_trace())

            state = observation.get("state", "NOT_FINISHED")
            steps_this_attempt = 0

            while steps_this_attempt < max_steps:
                budget_exhausted = bool(
                    getattr(orchestrator.cost_tracker, "budget_exhausted", False) is True
                ) if getattr(orchestrator, "cost_tracker", None) else False
                if orchestrator.cost_tracker and budget_exhausted:
                    error_msg = "Budget exhausted"
                    done = True
                    break

                if getattr(orchestrator, "_should_abandon", False):
                    error_msg = "Supervisor abandoned"
                    done = True
                    break

                brain_client.current_phase = "hypothesize"
                prior_step = orchestrator._step_history[-1] if getattr(orchestrator, "_step_history", None) else None
                hyp_ctx = await orchestrator.hypothesize(
                    observation,
                    prior_step.get("action_id") if prior_step else None,
                    total_steps,
                    transition_meta=prior_step,
                )

                brain_client.current_phase = "solve"
                await orchestrator.solve(observation, hyp_ctx, total_steps)

                brain_client.current_phase = "act"
                action = await orchestrator.act(observation, memory_context, total_steps + 1)

                total_tokens_in += self.harness.serializer._estimate_tokens(json.dumps(observation))
                total_tokens_out += self.harness.serializer._estimate_tokens(str(action))

                frame_response, reward, done, guid = await _execute_action_variant(game_id, guid, action, total_steps)

                recall_query = None
                if total_steps == 0 or consecutive_no_progress_steps >= 2:
                    recall_query = "What did I learn from similar puzzles?"

                brain_client.current_phase = "ingest"
                await adapter.ingest_step(frame_response, action, reward=reward, recall_query=recall_query)
                observation = adapter.normalize_observation(frame_response)
                orchestrator.record_step_result(reward, done, next_observation=observation)

                if reward > last_reward:
                    consecutive_no_progress_steps = 0
                    last_reward = reward
                else:
                    consecutive_no_progress_steps += 1

                state = observation.get("state", "NOT_FINISHED")
                if getattr(orchestrator, "_step_history", None):
                    orchestrator._step_history[-1].update(
                        {"state_after": state, "reward": reward, "done": done}
                    )

                total_steps += 1
                steps_this_attempt += 1
                # Emit a localized progress snapshot if requested (do not mutate shared runner state)
                if self._progress_callback:
                    last_step = orchestrator._step_history[-1] if getattr(orchestrator, "_step_history", None) else {}
                    solve_ctx = getattr(orchestrator, "_solve_context", {}) or {}
                    active_chunk = solve_ctx.get("active_chunk") or {}
                    snapshot = {
                        "snapshot_type": "step",
                        "game_id": getattr(task, "game_id", "unknown"),
                        "task_id": task.task_id,
                        "step": total_steps,
                        "runtime_seconds": round(time.time() - start_time, 2),
                        "state_after": observation.get("state", "NOT_FINISHED"),
                        "reward": reward,
                        "done": done,
                        "action_id": last_step.get("action_id"),
                        "rationale": last_step.get("rationale"),
                        "guard_status": last_step.get("guard_status"),
                        "thinking_trace": last_step.get("thinking_trace", []),
                        "frame_hash": observation.get("frame_hash"),
                        "available_actions": observation.get("available_actions", []),
                        "solve_phase_summary": {
                            "archetype": solve_ctx.get("archetype"),
                            "archetype_confidence": solve_ctx.get("archetype_confidence"),
                            "victory_condition": (solve_ctx.get("victory_condition") or {}).get("type") if isinstance(solve_ctx.get("victory_condition"), dict) else solve_ctx.get("victory_condition"),
                            "victory_confidence": (solve_ctx.get("victory_condition") or {}).get("confidence") if isinstance(solve_ctx.get("victory_condition"), dict) else None,
                            "strategy_summary": solve_ctx.get("strategy_summary"),
                            "active_chunk": {
                                "description": active_chunk.get("description"),
                                "source": active_chunk.get("source"),
                                "estimated_actions": active_chunk.get("estimated_actions", []),
                                "plan_id": active_chunk.get("plan_id"),
                            } if active_chunk else None,
                        },
                        "sidequests_ledger_count": len(getattr(brain_client, "ledger", []) or []),
                    }
                    self._progress_callback(snapshot)

                if state == "WIN":
                    success = True
                    break
                elif state == "GAME_OVER":
                    if attempt < max_retries and hasattr(orchestrator, "reset_for_retry"):
                        orchestrator.reset_for_retry(attempt)
                    break
                elif done:
                    success = reward >= 1.0 or state == "WIN"
                    break

            if success:
                break
            if state != "GAME_OVER":
                break

        if not success and total_steps >= max_steps * max_retries:
            error_msg = "Max attempts reached across all retries"
        elif not success and not error_msg:
            error_msg = f"Failed after {attempt} attempt(s)"

        duration = time.time() - start_time

        judge_verdict = None
        if self.outcome_judge and task.reference_solution:
            try:
                expected = json.loads(task.reference_solution)
                trajectory = self._build_trajectory_summary(orchestrator)
                archetype = getattr(getattr(orchestrator.solve_engine, "_archetype", None), "value", "unknown")
                verdict = await self.outcome_judge.evaluate(
                    observation.get("grid"), expected, trajectory, archetype
                )
                if verdict:
                    judge_verdict = asdict(verdict)
            except Exception:
                logger.exception("B181 failed")

        benchmark_metrics = {}
        if hasattr(orchestrator, "get_benchmark_metrics"):
            try:
                benchmark_metrics = orchestrator.get_benchmark_metrics()
            except Exception:
                logger.exception("B89: get_benchmark_metrics failed")

        trajectory_score = None
        try:
            trajectory_score = self.trajectory_evaluator.evaluate(
                trace=list(getattr(orchestrator, "_execution_trace", [])),
                step_history=list(getattr(orchestrator, "_step_history", [])),
            ).to_dict()
        except Exception:
            logger.exception("B186: trajectory evaluation failed")

        failure_class = None
        if not success:
            failure_class = classify_failure(
                exc=None,
                final_state=state,
                error_message=error_msg,
                no_progress_steps=max(
                    consecutive_no_progress_steps,
                    int(getattr(orchestrator, "_consecutive_no_progress_steps", 0) or 0),
                ),
                budget_exhausted=bool(
                    getattr(orchestrator.cost_tracker, "budget_exhausted", False) is True
                ) if getattr(orchestrator, "cost_tracker", None) else False,
                max_steps_reached=(total_steps >= max_steps * max_retries),
                loop_detected=bool((getattr(orchestrator, "_hypothesis_context", {}) or {}).get("loop_detected")),
            ).value

        task_result = ABTaskResult(
            task_id=task.task_id,
            variant=ABVariant.SIDEQUESTS,
            correct=success,
            steps=total_steps,
            tokens_input=total_tokens_in,
            tokens_output=total_tokens_out,
            error_message=error_msg,
            failure_class=failure_class,
            response_text=f"Solved: {success} in {total_steps} steps ({attempt} attempt(s))",
            attempts=attempt,
            dissonance_triggered=bool((getattr(orchestrator, "_solve_context", {}) or {}).get("dissonance")),
            trajectory_score=trajectory_score,
            final_state=state,
            final_observation=observation,
            judge_verdict=judge_verdict,
        )
        setattr(task_result, "bootstrap_write_trace", bootstrap_write_trace)
        setattr(task_result, "final_write_trace", final_write_trace)
        setattr(task_result, "benchmark_metrics", benchmark_metrics)
        setattr(task_result, "sidequests_ledger", list(getattr(brain_client, "ledger", []) or []))
        return task_result, duration, orchestrator

    def _build_trajectory_summary(self, orchestrator: ARCOrchestrator) -> str:
        lines = [
            f"Step {i + 1}: {s.get('action_id')} - {s.get('rationale')} (reward: {s.get('reward', 0.0)})"
            for i, s in enumerate(getattr(orchestrator, "_step_history", []))
        ]
        if getattr(orchestrator.solve_engine, "_victory_condition", None):
            lines.append(f"Inferred Objective: {orchestrator.solve_engine._victory_condition.description}")
        return "\n".join(lines)

    def _summarize_strategy(self, orchestrator: ARCOrchestrator) -> str:
        try:
            solve_ctx = getattr(orchestrator, "_solve_context", {}) or {}
            strategy_summary = solve_ctx.get("strategy_summary")
            if strategy_summary:
                return strategy_summary if isinstance(strategy_summary, str) else json.dumps(strategy_summary)
            active_chunk = solve_ctx.get("active_chunk") or {}
            parts = []
            if active_chunk.get("description"):
                parts.append(active_chunk.get("description"))
            if active_chunk.get("plan_id"):
                parts.append(f"plan:{active_chunk.get('plan_id')}")
            return " | ".join(parts) if parts else "No strategy summary"
        except Exception:
            logger.exception("Failed to summarize strategy")
            return "No strategy summary"

    async def _report_puzzle_outcome(self, *, orchestrator: ARCOrchestrator, task: ABTask, task_result: ABTaskResult, session_id: str) -> None:
        try:
            solve_ctx = getattr(orchestrator, "_solve_context", {}) or {}
            archetype_obj = getattr(getattr(orchestrator, "solve_engine", None), "_archetype", None)
            archetype = getattr(archetype_obj, "value", None) or solve_ctx.get("archetype") or "unknown"
            archetype_confidence = float(solve_ctx.get("archetype_confidence") or 0.7)

            outcome = {
                "task_id": task.task_id,
                "archetype": archetype,
                "archetype_confidence": archetype_confidence,
                "steps_taken": int(getattr(task_result, "steps", 0) or 0),
                "strategy_summary": self._summarize_strategy(orchestrator),
                "failure_class": getattr(task_result, "failure_class", None),
                "judge_verdict": getattr(task_result, "judge_verdict", None),
            }

            outcome_text = json.dumps(outcome, default=str)
            valence = 1.0 if getattr(task_result, "correct", False) else 0.0
            plan_id = getattr(orchestrator, "_plan_id", None)

            # Record structured outcome
            try:
                report_kwargs = {
                    "plan_id": plan_id,
                    "outcome": None,
                    "outcome_text": outcome_text,
                    "valence": valence,
                    "session_id": session_id,
                    "evidence": {"task_id": task.task_id},
                    "valence_source": "runner",
                }

                # If a procedure was applied, include procedure metadata so the DB can update stats
                proc_id = None
                proc_success = None
                try:
                    se = getattr(orchestrator, 'solve_engine', None)
                    if se is None:
                        se = getattr(orchestrator, '_solve_engine', None)
                    proc_id = getattr(se, '_applied_procedure_id', None) or getattr(se, '_using_procedure_id', None)
                    proc_failed = getattr(se, '_procedure_failed', None)
                    if proc_id:
                        report_kwargs['procedure_id'] = proc_id
                        # success = True only if puzzle solved and procedure didn't fail earlier
                        proc_success = bool(getattr(task_result, 'correct', False) and not bool(proc_failed))
                        report_kwargs['procedure_success'] = proc_success
                except Exception:
                    pass

                await self.brain.report_outcome(**report_kwargs)
            except Exception:
                logger.exception("Failed to report outcome via brain.report_outcome")

            # Persist a lesson summarizing the run (domain = archetype)
            lesson_text = f"ARC puzzle {task.task_id} outcome: {outcome_text}"
            tags = [str(archetype), ("success" if valence >= 1.0 else "failure"), f"steps_{outcome['steps_taken']}"]
            try:
                await self.brain.upsert_lesson(domain=str(archetype), text=lesson_text, valence=valence, confidence=archetype_confidence, tags=tags)
            except Exception:
                logger.exception("Failed to upsert lesson via brain.upsert_lesson")
        except Exception:
            logger.exception("_report_puzzle_outcome failed")

    def _emit_progress_snapshot(
        self,
        task: ABTask,
        orchestrator: ARCOrchestrator,
        observation: Mapping[str, Any],
        total_steps: int,
        reward: float,
        done: bool,
        start_time: float,
    ) -> None:
        if self._progress_callback is None:
            return

        last_step = orchestrator._step_history[-1] if getattr(orchestrator, "_step_history", None) else {}
        solve_ctx = getattr(orchestrator, "_solve_context", {}) or {}
        active_chunk = solve_ctx.get("active_chunk") or {}
        snapshot = {
            "snapshot_type": "step",
            "game_id": getattr(task, "game_id", "unknown"),
            "task_id": task.task_id,
            "step": total_steps,
            "runtime_seconds": round(time.time() - start_time, 2),
            "state_after": observation.get("state", "NOT_FINISHED"),
            "reward": reward,
            "done": done,
            "action_id": last_step.get("action_id"),
            "rationale": last_step.get("rationale"),
            "guard_status": last_step.get("guard_status"),
            "thinking_trace": last_step.get("thinking_trace", []),
            "frame_hash": observation.get("frame_hash"),
            "available_actions": observation.get("available_actions", []),
            "solve_phase_summary": {
                "archetype": solve_ctx.get("archetype"),
                "archetype_confidence": solve_ctx.get("archetype_confidence"),
                "victory_condition": (solve_ctx.get("victory_condition") or {}).get("type") if isinstance(solve_ctx.get("victory_condition"), dict) else solve_ctx.get("victory_condition"),
                "victory_confidence": (solve_ctx.get("victory_condition") or {}).get("confidence") if isinstance(solve_ctx.get("victory_condition"), dict) else None,
                "strategy_summary": solve_ctx.get("strategy_summary"),
                "active_chunk": {
                    "description": active_chunk.get("description"),
                    "source": active_chunk.get("source"),
                    "estimated_actions": active_chunk.get("estimated_actions", []),
                    "plan_id": active_chunk.get("plan_id"),
                } if active_chunk else None,
            },
            "sidequests_ledger_count": len(self._ledger),
        }
        self._progress_callback(snapshot)

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    async def _safe_raise_for_status(self, response: Any) -> None:
        raise_for_status = getattr(response, "raise_for_status", None)
        if callable(raise_for_status):
            await self._maybe_await(raise_for_status())

    async def _safe_json(self, response: Any) -> Any:
        json_method = getattr(response, "json", None)
        if not callable(json_method):
            return {}
        return await self._maybe_await(json_method())

    async def _initial_frame(self, game_id: str) -> tuple[dict, str | None]:
        start_t = time.time()
        if self.harness.mock_api:
            frame = self.harness._get_mock_initial_frame(game_id)
            if hasattr(self.brain, "record_arc_api_call"):
                self.brain.record_arc_api_call(
                    phase=getattr(self.brain, "current_phase", "bootstrap"),
                    method="GET",
                    endpoint="/api/games/initial",
                    request_payload={"game_id": game_id},
                    response_payload=frame,
                    latency_ms=(time.time() - start_t) * 1000,
                )
            return frame, frame.get("guid")

        session = getattr(self.harness, "_session", None)
        if session is None:
            raise RuntimeError("ARC API session not initialized. Did you call harness.setup()?")

        sc_start = time.time()
        try:
            scorecard_resp = await session.post("/api/scorecard/open", json={})
            sc_latency = (time.time() - sc_start) * 1000
            await self._safe_raise_for_status(scorecard_resp)
            sc_json = await self._safe_json(scorecard_resp)
            card_id = sc_json["card_id"]
            if hasattr(self.brain, "record_arc_api_call"):
                self.brain.record_arc_api_call(
                    phase=getattr(self.brain, "current_phase", "bootstrap"),
                    method="POST",
                    endpoint="/api/scorecard/open",
                    request_payload={},
                    response_payload=sc_json,
                    latency_ms=sc_latency,
                )
        except Exception as exc:
            if hasattr(self.brain, "record_arc_api_call"):
                self.brain.record_arc_api_call(
                    phase=getattr(self.brain, "current_phase", "bootstrap"),
                    method="POST",
                    endpoint="/api/scorecard/open",
                    request_payload={},
                    response_payload=None,
                    latency_ms=(time.time() - sc_start) * 1000,
                    received=False,
                    error_details={
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
            raise

        reset_start = time.time()
        reset_payload = {"game_id": game_id, "card_id": card_id}
        try:
            reset_resp = await session.post("/api/cmd/RESET", json=reset_payload)
            reset_latency = (time.time() - reset_start) * 1000
            await self._safe_raise_for_status(reset_resp)
            frame = await self._safe_json(reset_resp)
            if hasattr(self.brain, "record_arc_api_call"):
                self.brain.record_arc_api_call(
                    phase=getattr(self.brain, "current_phase", "bootstrap"),
                    method="POST",
                    endpoint="/api/cmd/RESET",
                    request_payload=reset_payload,
                    response_payload=frame,
                    latency_ms=reset_latency,
                )
            return frame, frame.get("guid")
        except Exception as exc:
            if hasattr(self.brain, "record_arc_api_call"):
                self.brain.record_arc_api_call(
                    phase=getattr(self.brain, "current_phase", "bootstrap"),
                    method="POST",
                    endpoint="/api/cmd/RESET",
                    request_payload=reset_payload,
                    response_payload=None,
                    latency_ms=(time.time() - reset_start) * 1000,
                    received=False,
                    error_details={
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
            raise

    async def _execute_action(self, game_id: str, guid: str | None, action: Mapping[str, Any], step: int) -> tuple[dict, float, bool, str | None]:
        start_t = time.time()
        if self.harness.mock_api:
            frame, reward, done = self.harness._execute_mock_action(game_id, action, step)
            if hasattr(self.brain, "record_arc_api_call"):
                self.brain.record_arc_api_call(
                    phase=getattr(self.brain, "current_phase", "act"),
                    method="POST",
                    endpoint=f"/api/cmd/{action.get('action_id', 'unknown')}",
                    request_payload=action,
                    response_payload=frame,
                    latency_ms=(time.time() - start_t) * 1000,
                )
            return frame, reward, done, frame.get("guid", guid)

        session = getattr(self.harness, "_session", None)
        if session is None:
            raise RuntimeError("ARC API session not initialized. Did you call harness.setup()?")

        action_id = action.get("action_id", "ACTION1")
        payload = {"game_id": game_id, "guid": guid}
        if action_id == "ACTION6":
            payload["x"] = action.get("x", 0)
            payload["y"] = action.get("y", 0)
        if "rationale" in action:
            payload["reasoning"] = action["rationale"]

        call_start = time.time()
        try:
            action_resp = await session.post(f"/api/cmd/{action_id}", json=payload)
            latency = (time.time() - call_start) * 1000
            await self._safe_raise_for_status(action_resp)
            frame = await self._safe_json(action_resp)
            if hasattr(self.brain, "record_arc_api_call"):
                self.brain.record_arc_api_call(
                    phase=getattr(self.brain, "current_phase", "act"),
                    method="POST",
                    endpoint=f"/api/cmd/{action_id}",
                    request_payload=payload,
                    response_payload=frame,
                    latency_ms=latency,
                )
            reward = 1.0 if frame.get("state") == "WIN" else 0.0
            done = frame.get("state") in ("WIN", "GAME_OVER")
            return frame, reward, done, frame.get("guid", guid)
        except Exception as exc:
            if hasattr(self.brain, "record_arc_api_call"):
                self.brain.record_arc_api_call(
                    phase=getattr(self.brain, "current_phase", "act"),
                    method="POST",
                    endpoint=f"/api/cmd/{action_id}",
                    request_payload=payload,
                    response_payload=None,
                    latency_ms=(time.time() - call_start) * 1000,
                    received=False,
                    error_details={
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
            raise

    def _extract_prompt_block_trace(self, prompt: str | None) -> list[dict]:
        if not isinstance(prompt, str) or not prompt.strip():
            return []

        markers = []
        def add(section: str, needle: str, block: str, tool: str):
            idx = prompt.find(needle)
            if idx != -1:
                markers.append((idx, section, block, tool))

        add("SOLVE CONTEXT", "=== SOLVE CONTEXT ===", "SolveContextBlock", "ARC Agent SolveEngine")
        add("CHUNK", "ACTIVE CHUNK:", "ChunkBlock", "ARC Agent SolveEngine")
        add("ACTION FACTS", "=== ACTION FACTS ===", "ActionFactBlock", "ARC Agent HypothesisManager")
        add("PATH HYPOTHESES", "=== PATH HYPOTHESES ===", "PathHypothesisBlock", "ARC Agent HypothesisManager")
        add("ENTITY CONTEXT", "=== ENTITY CONTEXT ===", "EntityContextBlock", "ARC Agent SolveEngine")
        add("OBSERVATION", "=== OBSERVATION ===", "ObservationBlock", "ARC Harness + ARC Agent")
        add("INSTRUCTION", "INSTRUCTION:", "InstructionBlock", "ARC Agent Prompt Builder")

        markers.sort(key=lambda item: item[0])
        trace = []
        for order, (_, section, block, tool) in enumerate(markers, start=1):
            trace.append(
                {
                    "order": order,
                    "section": section,
                    "block": block,
                    "owner": "ARC agent",
                    "tool": tool,
                }
            )
        return trace

    def _build_orchestration_report(self, ledger: list[dict], entity_gate_status: Mapping[str, Any] | None = None) -> dict:
        phase_owner = {
            "bootstrap": "harness",
            "perceive": "orchestrator",
            "plan": "orchestrator",
            "hypothesize": "orchestrator",
            "solve": "orchestrator",
            "act": "LLM",
            "ingest": "orchestrator",
            "evaluate": "harness",
        }
        decision_flow = {
            "bootstrap": {"proposer": "harness", "executor": "harness"},
            "perceive": {"proposer": "orchestrator", "executor": "SideQuests"},
            "plan": {"proposer": "orchestrator", "executor": "SideQuests"},
            "hypothesize": {"proposer": "orchestrator", "executor": "orchestrator"},
            "solve": {"proposer": "orchestrator", "executor": "orchestrator"},
            "act": {"proposer": "LLM", "executor": "orchestrator"},
            "ingest": {"proposer": "orchestrator", "executor": "SideQuests"},
            "evaluate": {"proposer": "harness", "executor": "harness"},
        }
        tool_rules = {
            "branch_quest": {"owner": "SideQuests", "allowed_modes": ["write"], "allowed_phases": ["bootstrap"]},
            "notify_turn": {"owner": "SideQuests", "allowed_modes": ["write"], "allowed_phases": ["bootstrap", "act", "ingest", "evaluate", "finalization"]},
            "current_truth": {"owner": "SideQuests", "allowed_modes": ["read"], "allowed_phases": ["bootstrap", "act", "ingest", "solve"]},
            "recall_lessons": {"owner": "SideQuests", "allowed_modes": ["read"], "allowed_phases": ["bootstrap", "solve", "ingest"]},
            "register_plan": {"owner": "SideQuests", "allowed_modes": ["write"], "allowed_phases": ["bootstrap", "solve"]},
            "report_outcome": {"owner": "SideQuests", "allowed_modes": ["write"], "allowed_phases": ["evaluate", "solve", "finalization"]},
        }

        violations = []
        for entry in ledger or []:
            call_type = entry.get("call_type") or entry.get("kind")
            phase = entry.get("phase")
            mode = entry.get("mode")
            rule = tool_rules.get(call_type)
            if not rule:
                continue
            if phase not in rule["allowed_phases"]:
                violations.append(
                    {
                        "type": "phase_violation",
                        "phase": phase,
                        "call_type": call_type,
                        "allowed_phases": list(rule["allowed_phases"]),
                    }
                )
            elif mode is not None and mode not in rule["allowed_modes"]:
                violations.append(
                    {
                        "type": "mode_violation",
                        "phase": phase,
                        "call_type": call_type,
                        "allowed_modes": list(rule["allowed_modes"]),
                    }
                )

        return {
            "orchestration_owner": "ARC Harness",
            "decision_flow": decision_flow,
            "phase_owner": phase_owner,
            "tool_rules": tool_rules,
            "runtime_surfaces": ["progress_log", "prompt_trace", "sidequests_ledger"],
            "entity_gate_status": dict(entity_gate_status) if isinstance(entity_gate_status, dict) else {},
            "violations": violations,
            "status": "ok" if not violations else "violation",
        }

    def _submission_row_from_result(self, result: dict) -> dict:
        if not isinstance(result, dict):
            return {}

        progress_log = list(result.get("debug_steps") or [])
        prompt_trace = [
            {
                "step": step.get("step"),
                "available_actions": step.get("available_actions", []),
                "prompt": step.get("prompt"),
                "block_trace": self._extract_prompt_block_trace(step.get("prompt")),
            }
            for step in progress_log
        ]

        confidence = [1.0 if result.get("correct") else 0.0]
        metadata = {
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "submission_id": f"sub_{uuid.uuid4().hex[:12]}",
            "run_duration_seconds": result.get("runtime_seconds", 0),
            "environment": {
                "llm_model": ((self.config.get("llm") or {}).get("model") if isinstance(self.config, dict) else "unknown") or "unknown",
                "llm_endpoint": "unknown",
                "memory_backend": "unknown",
                "arc_api_endpoint": "mock-harness" if bool(getattr(self.harness, "mock_api", False)) else "three.arcprize.org",
            },
            "model": ((self.config.get("llm") or {}).get("model") if isinstance(self.config, dict) else "unknown") or "unknown",
            "memory_enabled": not isinstance(self._raw_brain, type(None)),
            "steps": result.get("steps", 0),
            "correct": result.get("correct", False),
            "tokens_input": result.get("tokens_input", 0),
            "tokens_output": result.get("tokens_output", 0),
            "final_state": result.get("final_state"),
            "benchmark_metrics": result.get("benchmark_metrics", {}),
            "solve_phase_summary": result.get("solve_phase_summary", {}),
        }
        if result.get("failure_class") is not None:
            metadata["failure_class"] = result.get("failure_class")
        if result.get("trajectory_score") is not None:
            metadata["trajectory_score"] = result.get("trajectory_score")

        sidequests_ledger = list(result.get("sidequests_ledger") or [])
        arc_event_timeline = list(result.get("arc_event_timeline") or [])

        chronological_log: list[dict] = []
        for entry in sidequests_ledger:
            if isinstance(entry, dict):
                chronological_log.append(dict(entry))
        for event in arc_event_timeline:
            if not isinstance(event, dict):
                continue
            normalized = dict(event)
            normalized["timestamp_iso"] = (
                event.get("timestamp_iso")
                or event.get("request_started_iso")
                or event.get("response_received_iso")
            )
            chronological_log.append(normalized)
        chronological_log.sort(
            key=lambda entry: (
                str(entry.get("timestamp_iso") or ""),
                int(entry.get("event_seq") or 0),
                int(entry.get("call_seq") or 0),
            )
        )

        arc_pairs_map: dict[int, dict] = {}
        for event in arc_event_timeline:
            if not isinstance(event, dict):
                continue
            seq = event.get("call_seq")
            if seq is None:
                continue
            pair = arc_pairs_map.setdefault(int(seq), {"call_seq": int(seq), "request": None, "response": None})
            if event.get("kind") == "request_started":
                pair["request"] = event
            elif event.get("kind") == "response_received":
                pair["response"] = event
        arc_server_responses = [arc_pairs_map[k] for k in sorted(arc_pairs_map)]

        row = {
            "game_id": result.get("game_id", "unknown"),
            "task_id": result.get("task_id", "unknown"),
            "correct": result.get("correct", False),
            "steps": result.get("steps", 0),
            "tokens_input": result.get("tokens_input", 0),
            "tokens_output": result.get("tokens_output", 0),
            "runtime_seconds": result.get("runtime_seconds", 0),
            "error_message": result.get("error_message"),
            "failure_class": result.get("failure_class"),
            "final_state": result.get("final_state"),
            "final_observation": result.get("final_observation"),
            "trajectory_score": result.get("trajectory_score"),
            "benchmark_metrics": result.get("benchmark_metrics", {}),
            "bootstrap_write_trace": result.get("bootstrap_write_trace", []),
            "final_write_trace": result.get("final_write_trace", []),
            "sidequests_ledger": sidequests_ledger,
            "arc_event_timeline": arc_event_timeline,
            "chronological_log": chronological_log,
            "arc_server_responses": arc_server_responses,
            "progress_log": progress_log,
            "prompt_trace": prompt_trace,
            "orchestration_report": self._build_orchestration_report(
                sidequests_ledger,
                result.get("entity_gate_status", {}),
            ),
            "confidence": confidence,
            "metadata": metadata,
            "submission_metadata": metadata,
        }
        return row
