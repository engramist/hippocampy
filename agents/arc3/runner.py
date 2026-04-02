"""Durable ARC run driver tying orchestrator + checkpoints + harness."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import asdict
from typing import Any, Callable, List, Mapping

from benchmarks.ab_harness import ABTask, ABTaskResult, ABVariant
from benchmarks.arc3.adapter import ARC3Adapter, BrainClientProtocol, LedgerBrainClient
from benchmarks.arc3.harness import ARC3Harness
from agents.arc3.checkpoint import CheckpointManager
from agents.arc3.orchestrator import ARCOrchestrator
from agents.arc3.api_knowledge import ingest_api_knowledge

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
        self._knowledge_seeded = False
        self._ledger: List[dict] = []
        self._current_step = 0
        self._progress_callback = progress_callback
        
        self.brain = LedgerBrainClient(
            inner=brain_client,
            ledger=self._ledger,
            step_provider=lambda: self._current_step
        )

    async def _ensure_api_knowledge(self, session_id: str) -> None:
        """Ingest ARC API contract into SideQuests once per run."""
        if self._knowledge_seeded:
            return
        self.brain.current_phase = "bootstrap"
        await ingest_api_knowledge(self.brain, session_id)
        self._knowledge_seeded = True

    async def run(self, tasks: List[ABTask], card_id: str) -> List[dict]:
        mgr = CheckpointManager(card_id)
        checkpoint = mgr.load_or_create(tasks)
        results: List[dict] = []

        for task in tasks:
            tc = checkpoint.tasks.get(task.task_id)
            if tc and tc.status == "complete":
                if not self._has_terminal_payload(tc.result):
                    logger.info(
                        "Checkpoint for %s is stale (missing final_state/final_observation). Re-running task.",
                        task.task_id,
                    )
                    tc.status = "pending"
                    tc.result = None
                    tc.plan_id = None
                    mgr.save(checkpoint)
                else:
                    results.append(self._submission_row_from_result(tc.result or {}))
                    continue

            session_id = f"arc-{task.task_id}-{uuid.uuid4().hex[:8]}"
            self.brain.current_phase = "bootstrap"
            self._current_step = 0
            puzzle_start_time = time.time()
            self.brain = LedgerBrainClient(
                inner=self._raw_brain,
                ledger=self._ledger,
                step_provider=lambda: self._current_step,
                start_time=puzzle_start_time
            )
            await self._ensure_api_knowledge(session_id)

            # Branch per puzzle so each gets its own SideQuest scope
            branch_result = await self.brain.branch_quest(
                name=f"ARC puzzle {task.task_id}",
                purpose=f"Solve ARC-AGI-3 task {task.task_id}",
                parent_quest_id=card_id,
            )
            quest_id = branch_result.get("side_quest_id") or card_id

            orchestrator = ARCOrchestrator(
                brain_client=self.brain,
                llm_client=self.harness.llm_client,
                session_id=session_id,
                serializer=self.harness.serializer,
                config=self.config,
            )

            try:
                task_result, duration = await self._run_puzzle(orchestrator, task)
                debug_steps = list(getattr(orchestrator, "_step_history", []))
                final_write_trace = getattr(task_result, "final_write_trace", [])
                if debug_steps and final_write_trace:
                    debug_steps[-1] = dict(debug_steps[-1])
                    debug_steps[-1]["write_trace"] = list(debug_steps[-1].get("write_trace", [])) + list(final_write_trace)
                result_payload = asdict(task_result)
                result_payload["solve_phase_summary"] = {}  # will be filled by _submission_row_from_result
                result_payload["game_id"] = getattr(task, "game_id", "unknown")
                result_payload["debug_steps"] = debug_steps
                result_payload["bootstrap_write_trace"] = getattr(task_result, "bootstrap_write_trace", [])
                result_payload["final_write_trace"] = final_write_trace
                result_payload["runtime_seconds"] = round(duration, 2)
                # B89: Add benchmark metrics to result payload
                result_payload["benchmark_metrics"] = getattr(task_result, "benchmark_metrics", {})
                
                # B121: Add entity gate status
                result_payload["entity_gate_status"] = getattr(orchestrator, "_entity_gate_result", {})
                
                # B130: Add guard escalations
                result_payload["guard_escalations"] = getattr(orchestrator, "_guard_escalations", [])

                # B118: Run final pruning analysis for debug export
                orchestrator.analyze_ledger_and_prune()
                
                # B111: Add aggregated ledger from the shared list
                result_payload["sidequests_ledger"] = list(self._ledger)
                self._ledger.clear()  # reset for next puzzle

                mgr.mark_complete(checkpoint, task.task_id, orchestrator._plan_id, result_payload)
                results.append(self._submission_row_from_result(result_payload))
            except Exception as exc:
                mgr.mark_failed(checkpoint, task.task_id, str(exc))
                logger.error("Task %s failed: %s", task.task_id, exc)

        return results

    def _has_terminal_payload(self, result: dict | None) -> bool:
        """Return True when result contains terminal state + final grid for export."""
        if not isinstance(result, dict):
            return False

        final_state = result.get("final_state")
        final_observation = result.get("final_observation")
        if not isinstance(final_state, str) or not final_state:
            return False
        if not isinstance(final_observation, dict):
            return False

        grid = final_observation.get("grid")
        return isinstance(grid, list) and len(grid) > 0

    async def _run_puzzle(self, orchestrator: ARCOrchestrator, task: ABTask) -> tuple[ABTaskResult, float]:
        max_steps = self.harness.config.parameters.get("max_attempts_per_puzzle", 10)
        max_retries = self.config.get("max_retries_per_puzzle", 3)
        adapter = ARC3Adapter(
            brain_client=self.brain,
            session_id=orchestrator.session_id,
            task_id=task.task_id,
        )
        game_id = getattr(task, "game_id", "unknown")

        import datetime
        start_time = time.time()
        total_steps = 0
        success = False
        error_msg: str | None = None
        total_tokens_input = 0
        total_tokens_output = 0
        bootstrap_write_trace: list[dict] = []
        final_write_trace: list[dict] = []
        last_grid = None

        for attempt in range(1, max_retries + 1):
            # (Re-)initialize the game environment
            frame_response, guid = await self._initial_frame(game_id)
            observation = adapter.normalize_observation(frame_response)
            last_grid = observation.get("grid")
            orchestrator.set_write_trace_context("bootstrap")
            self.brain.current_phase = "bootstrap"
            self._current_step = 0
            memory_context = await orchestrator.perceive(observation, step=0)
            await orchestrator.plan(observation, memory_context)
            bootstrap_write_trace = orchestrator.consume_write_trace()

            steps_this_attempt = 0
            while steps_this_attempt < max_steps:
                prior_step = orchestrator._step_history[-1] if steps_this_attempt > 0 and orchestrator._step_history else None
                # B88 — Update hypothesis engine
                orchestrator.set_write_trace_context(f"step-{total_steps + 1}")
                self.brain.current_phase = "hypothesize"
                self._current_step = total_steps + 1
                hyp_ctx = await orchestrator.hypothesize(
                    observation,
                    prior_step.get("action_id") if prior_step else None,
                    total_steps,
                    transition_meta=prior_step,
                )

                # B95 — Solve engine
                self.brain.current_phase = "solve"
                await orchestrator.solve(observation, hyp_ctx, total_steps)

                self.brain.current_phase = "act"
                action = await orchestrator.act(observation, memory_context, total_steps + 1)
                total_tokens_input += self.harness.serializer._estimate_tokens(json.dumps(observation))
                total_tokens_output += self.harness.serializer._estimate_tokens(str(action))

                frame_response, reward, done, guid = await self._execute_action(
                    game_id, guid, action, total_steps
                )
                recall_query = "What did I learn from similar puzzles?"
                self.brain.current_phase = "ingest"
                await adapter.ingest_step(frame_response, action, reward=reward, recall_query=recall_query)
                orchestrator.record_step_result(reward, done)

                observation = adapter.normalize_observation(frame_response)
                curr_grid = observation.get("grid")
                frame_analysis = self._analyze_frame_delta(last_grid, curr_grid)
                last_grid = curr_grid
                
                state = observation.get("state", "NOT_FINISHED")
                if orchestrator._step_history:
                    now = time.time()
                    elapsed_ms = (now - start_time) * 1000
                    elapsed_mmss = f"{int(elapsed_ms // 60000):02d}:{int((elapsed_ms % 60000) // 1000):02d}"
                    timestamp_iso = datetime.datetime.fromtimestamp(now, datetime.timezone.utc).isoformat().replace("+00:00", "Z")
                    
                    orchestrator._step_history[-1]["state_after"] = state
                    orchestrator._step_history[-1]["board_after"] = orchestrator._snapshot_for_trace(observation)
                    orchestrator._step_history[-1]["write_trace"] = orchestrator.consume_write_trace()
                    orchestrator._step_history[-1]["frame_analysis"] = frame_analysis
                    orchestrator._step_history[-1]["timestamp_iso"] = timestamp_iso
                    orchestrator._step_history[-1]["elapsed_mmss"] = elapsed_mmss
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
                    self.brain.current_phase = "finalization"
                    await orchestrator.hypothesis_mgr.distill_to_brain(orchestrator.solve_engine._object_roles)
                    break
                elif state == "GAME_OVER":
                    self.brain.current_phase = "finalization"
                    await orchestrator.hypothesis_mgr.distill_to_brain(orchestrator.solve_engine._object_roles)
                    # Record pain so Amygdala Reflex can block this strategy next time
                    self.brain.current_phase = "evaluate"
                    await orchestrator.evaluate(
                        False, steps_this_attempt, max_steps,
                        final_observation=observation,
                    )
                    game_over_write_trace = orchestrator.consume_write_trace()
                    if orchestrator._step_history and game_over_write_trace:
                        orchestrator._step_history[-1]["write_trace"] = list(
                            orchestrator._step_history[-1].get("write_trace", [])
                        ) + list(game_over_write_trace)
                    if game_over_write_trace:
                        final_write_trace = list(game_over_write_trace)
                    if attempt < max_retries:
                        logger.info(
                            "GAME_OVER on attempt %d/%d for %s — retrying with new strategy",
                            attempt, max_retries, task.task_id,
                        )
                        orchestrator.reset_for_retry(attempt)
                    break
                elif done:
                    success = reward >= 1.0
                    break

                # B118: Run periodic pruning analysis every 5 steps
                if total_steps % 5 == 0:
                    orchestrator.analyze_ledger_and_prune()

            if success:
                break
            if state != "GAME_OVER":
                # Ran out of steps without a terminal state
                break

        if not success and total_steps >= max_steps * max_retries:
            error_msg = "Max attempts reached across all retries"
        elif not success and not error_msg:
            error_msg = f"Failed after {attempt} attempt(s)"

        duration = time.time() - start_time

        # Final evaluation (only if we haven't just evaluated on GAME_OVER)
        if success or state != "GAME_OVER":
            orchestrator.set_write_trace_context("finalization")
            self.brain.current_phase = "evaluate"
            await orchestrator.evaluate(success, total_steps, max_steps * max_retries, final_observation=observation)
        post_run_write_trace = orchestrator.consume_write_trace()
        if post_run_write_trace:
            final_write_trace.extend(post_run_write_trace)

        print(f"\n[DEBUG _run_puzzle] state={state}, success={success}, observation keys={list(observation.keys()) if isinstance(observation, dict) else 'not-dict'}\n", flush=True)

        # B89: Collect benchmark metrics
        benchmark_metrics = orchestrator.get_benchmark_metrics()

        task_result = ABTaskResult(
            task_id=task.task_id,
            variant=ABVariant.SIDEQUESTS,
            correct=success,
            steps=total_steps,
            tokens_input=total_tokens_input,
            tokens_output=total_tokens_output,
            error_message=error_msg,
            response_text=f"Solved: {success} in {total_steps} steps ({attempt} attempt(s))",
            final_state=state,
            final_observation=observation,
        )
        setattr(task_result, "bootstrap_write_trace", bootstrap_write_trace)
        setattr(task_result, "final_write_trace", final_write_trace)
        setattr(task_result, "benchmark_metrics", benchmark_metrics)
        setattr(task_result, "sidequests_ledger", list(self._ledger))
        return (
            task_result,
            duration,
        )

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
        """Emit a compact incremental snapshot for live-watch output."""
        if self._progress_callback is None:
            return

        last_step = orchestrator._step_history[-1] if orchestrator._step_history else {}
        solve_ctx = orchestrator._solve_context or {}
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
                "victory_condition": (solve_ctx.get("victory_condition") or {}).get("type"),
                "victory_confidence": (solve_ctx.get("victory_condition") or {}).get("confidence"),
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

    async def _initial_frame(self, game_id: str) -> tuple[dict, str | None]:
        start_t = time.time()
        if self.harness.mock_api:
            frame = self.harness._get_mock_initial_frame(game_id)
            latency = (time.time() - start_t) * 1000
            self.brain.record_arc_api_call(
                phase=self.brain.current_phase,
                method="GET",
                endpoint="/api/games/initial",
                request_payload={"game_id": game_id},
                response_payload=frame,
                latency_ms=latency
            )
            return frame, frame.get("guid")

        session = getattr(self.harness, "_session", None)
        if session is None:
            raise RuntimeError("ARC API session not initialized. Did you call harness.setup()?")

        # scorecard/open call
        sc_start = time.time()
        scorecard_resp = await session.post("/api/scorecard/open", json={})
        sc_latency = (time.time() - sc_start) * 1000
        scorecard_resp.raise_for_status()
        sc_json = scorecard_resp.json()
        card_id = sc_json["card_id"]
        self.brain.record_arc_api_call(
            phase=self.brain.current_phase,
            method="POST",
            endpoint="/api/scorecard/open",
            request_payload={},
            response_payload=sc_json,
            latency_ms=sc_latency
        )

        # RESET call
        reset_start = time.time()
        reset_payload = {"game_id": game_id, "card_id": card_id}
        try:
            reset_resp = await session.post(
                "/api/cmd/RESET",
                json=reset_payload,
            )
            reset_latency = (time.time() - reset_start) * 1000
            reset_resp.raise_for_status()
            frame = reset_resp.json()
            self.brain.record_arc_api_call(
                phase=self.brain.current_phase,
                method="POST",
                endpoint="/api/cmd/RESET",
                request_payload=reset_payload,
                response_payload=frame,
                latency_ms=reset_latency
            )
            return frame, frame.get("guid")
        except Exception as exc:
            latency = (time.time() - reset_start) * 1000
            self.brain.record_arc_api_call(
                phase=self.brain.current_phase,
                method="POST",
                endpoint="/api/cmd/RESET",
                request_payload=reset_payload,
                response_payload=None,
                latency_ms=latency,
                received=False,
                error_details={"error_type": type(exc).__name__, "error_message": str(exc)}
            )
            raise

    async def _execute_action(
        self, game_id: str, guid: str | None, action: Mapping[str, Any], step: int
    ) -> tuple[dict, float, bool, str | None]:
        start_t = time.time()
        if self.harness.mock_api:
            frame, reward, done = self.harness._execute_mock_action(game_id, action, step)
            latency = (time.time() - start_t) * 1000
            self.brain.record_arc_api_call(
                phase=self.brain.current_phase,
                method="POST",
                endpoint=f"/api/cmd/{action.get('action_id', 'unknown')}",
                request_payload=action,
                response_payload=frame,
                latency_ms=latency
            )
            return frame, reward, done, frame.get("guid", guid)

        session = getattr(self.harness, "_session", None)
        if session is None:
            raise RuntimeError("ARC API session not initialized. Did you call harness.setup()?")

        action_id = action.get("action_id", "ACTION1")
        action_payload = {"game_id": game_id, "guid": guid}
        if action_id == "ACTION6":
            action_payload["x"] = action.get("x", 0)
            action_payload["y"] = action.get("y", 0)
        if "rationale" in action:
            action_payload["reasoning"] = action["rationale"]

        # POST /api/cmd/{ACTION_ID}
        call_start = time.time()
        try:
            action_resp = await session.post(f"/api/cmd/{action_id}", json=action_payload)
            latency = (time.time() - call_start) * 1000
            action_resp.raise_for_status()
            frame = action_resp.json()
            self.brain.record_arc_api_call(
                phase=self.brain.current_phase,
                method="POST",
                endpoint=f"/api/cmd/{action_id}",
                request_payload=action_payload,
                response_payload=frame,
                latency_ms=latency
            )
            reward = 1.0 if frame.get("state") == "WIN" else 0.0
            done = frame.get("state") in ("WIN", "GAME_OVER")
            return frame, reward, done, frame.get("guid", guid)
        except Exception as exc:
            latency = (time.time() - call_start) * 1000
            error_details = {
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
            # Record failure in ledger
            self.brain.record_arc_api_call(
                phase=self.brain.current_phase,
                method="POST",
                endpoint=f"/api/cmd/{action_id}",
                request_payload=action_payload,
                response_payload=None,
                latency_ms=latency,
                received=False,
                error_details=error_details
            )
            raise

    def _analyze_frame_delta(self, prev_frame: List[List[int]] | None, curr_frame: List[List[int]]) -> dict:
        """B130: Capture pixel-level changes between consecutive frames."""
        if prev_frame is None:
            return {
                "pixels_changed": 0,
                "movement_detected": False,
                "bounding_box_change": None,
                "new_colors_introduced": [],
                "colors_removed": [],
                "analysis": "Initial frame"
            }
        
        rows = len(curr_frame)
        cols = len(curr_frame[0]) if rows > 0 else 0
        if rows != len(prev_frame) or (rows > 0 and cols != len(prev_frame[0])):
            return {
                "pixels_changed": -1,
                "movement_detected": True,
                "bounding_box_change": "Resized",
                "new_colors_introduced": [],
                "colors_removed": [],
                "analysis": f"Grid resized from {len(prev_frame)}x{len(prev_frame[0]) if len(prev_frame)>0 else 0} to {rows}x{cols}"
            }

        changed = 0
        new_colors = set()
        prev_colors = set()
        curr_colors = set()
        
        for r in range(rows):
            for c in range(cols):
                prev_val = prev_frame[r][c]
                curr_val = curr_frame[r][c]
                prev_colors.add(prev_val)
                curr_colors.add(curr_val)
                if prev_val != curr_val:
                    changed += 1
        
        new_colors_list = sorted(list(curr_colors - prev_colors))
        removed_colors_list = sorted(list(prev_colors - curr_colors))
        
        analysis = f"Frame changed: {changed} pixels affected" if changed > 0 else "Frame unchanged"
        
        return {
            "pixels_changed": changed,
            "movement_detected": changed > 0,
            "bounding_box_change": None,
            "new_colors_introduced": new_colors_list,
            "colors_removed": removed_colors_list,
            "analysis": analysis
        }

    def _submission_row_from_result(self, result: dict | None) -> dict:
        metadata = self._build_submission_metadata(result or {})

        debug_steps = result.get("debug_steps") if result else []
        progress_log = []
        prompt_trace = []
        for step in debug_steps or []:
            progress_log.append(
                {
                    "step": step.get("step"),
                    "timestamp_iso": step.get("timestamp_iso"),
                    "elapsed_mmss": step.get("elapsed_mmss"),
                    "state_before": step.get("state_before"),
                    "solve_context": step.get("solve_context"),
                    "action_id": step.get("action_id"),
                    "rationale": step.get("rationale"),
                    "reward": step.get("reward"),
                    "done": step.get("done"),
                    "state_after": step.get("state_after"),
                    "board_before": step.get("board_before"),
                    "board_after": step.get("board_after"),
                    "frame_analysis": step.get("frame_analysis"),
                    "write_trace": step.get("write_trace", []),
                }
            )
            prompt_trace.append(
                {
                    "step": step.get("step"),
                    "available_actions": step.get("available_actions", []),
                    "prompt": step.get("prompt"),
                    "block_trace": self._extract_prompt_block_trace(step.get("prompt")),
                }
            )

        # Collect unique archetype/victory evolution across steps
        archetypes_seen = []
        victories_seen = []
        final_solve_ctx = None
        for s in debug_steps or []:
            sc = s.get("solve_context")
            if sc:
                a = sc.get("archetype", "unknown")
                if not archetypes_seen or archetypes_seen[-1] != a:
                    archetypes_seen.append(a)
                v = (sc.get("victory_condition") or {}).get("type", "unknown")
                if not victories_seen or victories_seen[-1] != v:
                    victories_seen.append(v)
                final_solve_ctx = sc

        solve_phase_summary = {
            "archetype_evolution": archetypes_seen,
            "victory_evolution": victories_seen,
            "final_archetype": final_solve_ctx.get("archetype") if final_solve_ctx else "unknown",
            "final_archetype_confidence": final_solve_ctx.get("archetype_confidence", 0.0) if final_solve_ctx else 0.0,
            "final_victory_condition": (final_solve_ctx.get("victory_condition") or {}).get("type", "unknown") if final_solve_ctx else "unknown",
            "final_victory_confidence": (final_solve_ctx.get("victory_condition") or {}).get("confidence", 0.0) if final_solve_ctx else 0.0,
            "final_strategy_summary": final_solve_ctx.get("strategy_summary", "") if final_solve_ctx else "",
            "dissonance_triggered": any(
                (s.get("solve_context") or {}).get("dissonance") for s in (debug_steps or [])
            ),
            "object_roles": final_solve_ctx.get("object_roles", {}) if final_solve_ctx else {},
        }
        metadata["solve_phase_summary"] = solve_phase_summary

        is_correct = bool(result.get("correct")) if result else False
        sidequests_ledger = result.get("sidequests_ledger", []) if result else []
        entity_gate_status = result.get("entity_gate_status", {}) if result else {}
        guard_escalations = result.get("guard_escalations", []) if result else []
        orchestration_report = self._build_orchestration_report(sidequests_ledger, entity_gate_status, guard_escalations)
        return {
            "game_id": result.get("game_id") if result else "",
            "task_id": result.get("task_id") if result else "",
            "correct": result.get("correct") if result else None,
            "steps": result.get("steps") if result else None,
            "bootstrap_write_trace": result.get("bootstrap_write_trace", []) if result else [],
            "sidequests_ledger": sidequests_ledger,
            "entity_gate_status": entity_gate_status,
            "progress_log": progress_log,
            "prompt_trace": prompt_trace,
            "orchestration_report": orchestration_report,
            "solve_phase_summary": solve_phase_summary,
            "confidence": [1.0 if is_correct else 0.0],
            "final_write_trace": result.get("final_write_trace", []) if result else [],
            "submission_metadata": metadata, # B130 renaming metadata to submission_metadata
            "metadata": metadata, # preserve for compatibility
        }
    def _build_orchestration_report(self, sidequests_ledger: List[dict], entity_gate_status: dict | None = None, guard_escalations: List[dict] | None = None) -> dict:
        """Return ownership + policy checks for ARC harness orchestration."""
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
            "notify_turn": {
                "owner": "SideQuests",
                "allowed_modes": ["write"],
                "allowed_phases": ["bootstrap", "act", "ingest", "evaluate", "finalization"],
            },
            "current_truth": {
                "owner": "SideQuests",
                "allowed_modes": ["read"],
                "allowed_phases": ["bootstrap", "ingest", "act"],
            },
            "register_plan": {
                "owner": "SideQuests",
                "allowed_modes": ["write"],
                "allowed_phases": ["bootstrap", "solve"],
            },
            "report_outcome": {
                "owner": "SideQuests",
                "allowed_modes": ["write"],
                "allowed_phases": ["evaluate", "finalization"],
            },
            "recall_plans": {
                "owner": "SideQuests",
                "allowed_modes": ["read"],
                "allowed_phases": ["bootstrap", "solve"],
            },
            "recall_lessons": {
                "owner": "SideQuests",
                "allowed_modes": ["read"],
                "allowed_phases": ["bootstrap", "solve"],
            },
            "analogical_search": {
                "owner": "SideQuests",
                "allowed_modes": ["read"],
                "allowed_phases": ["bootstrap", "solve"],
            },
            "branch_quest": {
                "owner": "SideQuests",
                "allowed_modes": ["write"],
                "allowed_phases": ["bootstrap"],
            },
            "arc_api_action": {
                "owner": "harness",
                "allowed_modes": ["read", "write"],
                "allowed_phases": ["bootstrap", "act"],
            }
        }

        violations: List[dict] = []
        for idx, entry in enumerate(sidequests_ledger or []):
            call_type = entry.get("call_type")
            phase = entry.get("phase")
            mode = entry.get("mode")
            step = entry.get("step")

            if phase not in decision_flow and phase != "finalization":
                violations.append(
                    {
                        "index": idx,
                        "step": step,
                        "type": "unknown_phase",
                        "phase": phase,
                        "call_type": call_type,
                    }
                )

            rule = tool_rules.get(call_type)
            if rule is None:
                violations.append(
                    {
                        "index": idx,
                        "step": step,
                        "type": "unknown_tool",
                        "phase": phase,
                        "call_type": call_type,
                    }
                )
                continue

            if mode not in rule["allowed_modes"]:
                violations.append(
                    {
                        "index": idx,
                        "step": step,
                        "type": "mode_violation",
                        "phase": phase,
                        "call_type": call_type,
                        "observed_mode": mode,
                        "allowed_modes": list(rule["allowed_modes"]),
                    }
                )

            if phase not in rule["allowed_phases"]:
                violations.append(
                    {
                        "index": idx,
                        "step": step,
                        "type": "phase_violation",
                        "phase": phase,
                        "call_type": call_type,
                        "allowed_phases": list(rule["allowed_phases"]),
                    }
                )

        # B118: Surface pruning decisions
        pruning_decisions = []
        if sidequests_ledger:
            # Stats for report
            latencies = [e.get("latency_ms", 0) for e in sidequests_ledger if e.get("latency_ms")]
            avg_latency = sum(latencies) / len(latencies) if latencies else 0
            
            # Simple check for any high-latency call types
            slow_calls = [e for e in sidequests_ledger if e.get("latency_ms", 0) > 1000]
            if slow_calls:
                pruning_decisions.append({
                    "observed_slow_calls": len(slow_calls),
                    "avg_latency_ms": round(avg_latency, 1),
                })

        surfaces = {
            "arc_harness": {
                "owner": "ARC Harness",
                "responsibility": "Orchestration and phase control",
            },
            "arc_agent": {
                "owner": "ARC Agent",
                "responsibility": "Reasoning, hypotheses, solve context, action proposals",
            },
            "sidequests": {
                "owner": "SideQuests",
                "responsibility": "Memory and planning tools",
            },
            "arc_api": {
                "owner": "ARC Environment",
                "responsibility": "State transitions and available_actions contract",
            },
        }

        return {
            "orchestration_owner": "ARC Harness",
            "decision_flow": decision_flow,
            "phase_owner": {k: v["proposer"] for k, v in decision_flow.items()}, # compatibility
            "tool_rules": tool_rules,
            "runtime_surfaces": surfaces,
            "policy_violations": violations,
            "violations": violations, # compatibility
            "entity_gate_status": entity_gate_status or {},
            "guard_escalations": guard_escalations or [],
            "sidequests_ledger_stats": {
                "total_calls": len(sidequests_ledger),
                "high_latency_calls": len([e for e in sidequests_ledger if e.get("latency_ms", 0) > 500]),
            },
            "pruning_decisions": pruning_decisions,
            "status": "ok" if not violations else "violation",
        }

    def _extract_prompt_block_trace(self, prompt: Any) -> List[dict]:
        """Return ordered prompt blocks with canonical names and producer ownership."""
        if not isinstance(prompt, str) or not prompt.strip():
            return []

        lines = prompt.splitlines()
        section_order: List[str] = []

        # Preserve the actual section order as rendered in the prompt.
        if any(line.startswith("SYSTEM:") for line in lines):
            section_order.append("SYSTEM")
        if any(line.startswith("STATE:") for line in lines):
            section_order.append("STATE")

        header_re = re.compile(r"^===\s+([A-Z_ ]+)\s+===$")
        for line in lines:
            m = header_re.match(line.strip())
            if m:
                section = m.group(1).strip().replace(" ", "_")
                section_order.append(section)

        if any(line.startswith("INSTRUCTION:") for line in lines):
            section_order.append("INSTRUCTION")

        block_map = {
            "OBSERVATION": {
                "block": "ObservationBlock",
                "owner": "ARC agent",
                "tool": "ARC Harness + ARC Agent",
            },
            "ACTION_FACTS": {
                "block": "ActionFactBlock",
                "owner": "ARC agent",
                "tool": "ARC Agent HypothesisManager",
            },
            "PATH_HYPOTHESES": {
                "block": "PathHypothesisBlock",
                "owner": "ARC agent",
                "tool": "ARC Agent HypothesisManager",
            },
            "SOLVE_CONTEXT": {
                "block": "SolveContextBlock",
                "owner": "ARC agent",
                "tool": "ARC Agent SolveEngine",
            },
            "INSTRUCTION": {
                "block": "InstructionBlock",
                "owner": "ARC agent",
                "tool": "ARC Agent Prompt Builder",
            },
        }

        trace: List[dict] = []
        order = 1
        for section in section_order:
            mapped = block_map.get(section)
            if not mapped:
                continue
            trace.append(
                {
                    "order": order,
                    "section": section,
                    "block": mapped["block"],
                    "owner": mapped["owner"],
                    "tool": mapped["tool"],
                }
            )
            order += 1

            # ChunkBlock is encoded inside SOLVE_CONTEXT as ACTIVE CHUNK lines.
            if section == "SOLVE_CONTEXT" and "ACTIVE CHUNK:" in prompt:
                trace.append(
                    {
                        "order": order,
                        "section": "SOLVE_CONTEXT",
                        "block": "ChunkBlock",
                        "owner": "ARC agent",
                        "tool": "ARC Agent SolveEngine",
                    }
                )
                order += 1

        return trace

    def _build_submission_metadata(self, data: dict) -> dict:
        import datetime
        runtime = float(data.get("runtime_seconds") or 0.0)
        
        # B130 schema
        metadata = {
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "submission_id": f"sub_{uuid.uuid4().hex[:12]}",
            "run_duration_seconds": round(runtime, 2),
            "environment": {
                "llm_model": self.config.get("llm", {}).get("model", "unknown"),
                "llm_endpoint": self.config.get("llm", {}).get("endpoint", "unknown"),
                "memory_backend": "kuzu_0.11.3",
                "arc_api_endpoint": "three.arcprize.org" if not self.harness.mock_api else "mock-harness"
            },
            # B89 Compatibility
            "model": self.config.get("llm", {}).get("model", "unknown"),
            "memory_enabled": True,
            "steps": data.get("steps"),
            "correct": data.get("correct"),
            "tokens_input": data.get("tokens_input"),
            "tokens_output": data.get("tokens_output"),
            "final_state": data.get("final_state"),
        }
        
        if data.get("benchmark_metrics"):
            metadata["benchmark_metrics"] = data["benchmark_metrics"]
        if data.get("solve_phase_summary"):
            metadata["solve_phase_summary"] = data["solve_phase_summary"]
        return metadata
