"""Durable ARC run driver tying orchestrator + checkpoints + harness."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict
from typing import Any, List, Mapping

from benchmarks.ab_harness import ABTask, ABTaskResult, ABVariant
from benchmarks.arc3.adapter import ARC3Adapter, BrainClientProtocol
from benchmarks.arc3.harness import ARC3Harness
from agents.arc3.checkpoint import CheckpointManager
from agents.arc3.orchestrator import ARCOrchestrator
from agents.arc3.api_knowledge import ingest_api_knowledge

logger = logging.getLogger(__name__)


class DurableARCRunner:
    """Crash-safe scorecard driver with SideQuests orchestrator."""

    def __init__(self, harness: ARC3Harness, brain_client: BrainClientProtocol, config: dict):
        self.harness = harness
        self.brain = brain_client
        self.config = config
        self._knowledge_seeded = False

    async def _ensure_api_knowledge(self, session_id: str) -> None:
        """Ingest ARC API contract into SideQuests once per run."""
        if self._knowledge_seeded:
            return
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

        start_time = time.time()
        total_steps = 0
        success = False
        error_msg: str | None = None
        total_tokens_input = 0
        total_tokens_output = 0
        bootstrap_write_trace: list[dict] = []
        final_write_trace: list[dict] = []

        for attempt in range(1, max_retries + 1):
            # (Re-)initialize the game environment
            frame_response, guid = await self._initial_frame(game_id)
            observation = adapter.normalize_observation(frame_response)
            orchestrator.set_write_trace_context("bootstrap")
            memory_context = await orchestrator.perceive(observation, step=0)
            await orchestrator.plan(observation, memory_context)
            bootstrap_write_trace = orchestrator.consume_write_trace()

            steps_this_attempt = 0
            while steps_this_attempt < max_steps:
                prior_step = orchestrator._step_history[-1] if steps_this_attempt > 0 and orchestrator._step_history else None
                # B88 — Update hypothesis engine
                orchestrator.set_write_trace_context(f"step-{total_steps + 1}")
                hyp_ctx = await orchestrator.hypothesize(
                    observation,
                    prior_step.get("action_id") if prior_step else None,
                    total_steps,
                    transition_meta=prior_step,
                )

                # B95 — Solve engine
                await orchestrator.solve(observation, hyp_ctx, total_steps)

                action = await orchestrator.act(observation, memory_context, total_steps + 1)
                total_tokens_input += self.harness.serializer._estimate_tokens(json.dumps(observation))
                total_tokens_output += self.harness.serializer._estimate_tokens(str(action))

                frame_response, reward, done, guid = await self._execute_action(
                    game_id, guid, action, total_steps
                )
                recall_query = "What did I learn from similar puzzles?"
                await adapter.ingest_step(frame_response, action, reward=reward, recall_query=recall_query)
                orchestrator.record_step_result(reward, done)

                observation = adapter.normalize_observation(frame_response)
                state = observation.get("state", "NOT_FINISHED")
                if orchestrator._step_history:
                    orchestrator._step_history[-1]["state_after"] = state
                    orchestrator._step_history[-1]["board_after"] = orchestrator._snapshot_for_trace(observation)
                    orchestrator._step_history[-1]["write_trace"] = orchestrator.consume_write_trace()
                total_steps += 1
                steps_this_attempt += 1

                if state == "WIN":
                    success = True
                    await orchestrator.hypothesis_mgr.distill_to_brain()
                    break
                elif state == "GAME_OVER":
                    await orchestrator.hypothesis_mgr.distill_to_brain()
                    # Record pain so Amygdala Reflex can block this strategy next time
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
        return (
            task_result,
            duration,
        )

    async def _initial_frame(self, game_id: str) -> tuple[dict, str | None]:
        if self.harness.mock_api:
            frame = self.harness._get_mock_initial_frame(game_id)
            return frame, frame.get("guid")

        session = getattr(self.harness, "_session", None)
        if session is None:
            raise RuntimeError("ARC API session not initialized. Did you call harness.setup()?")

        scorecard_resp = await session.post("/api/scorecard/open", json={})
        scorecard_resp.raise_for_status()
        card_id = scorecard_resp.json()["card_id"]

        reset_resp = await session.post(
            "/api/cmd/RESET",
            json={"game_id": game_id, "card_id": card_id},
        )
        reset_resp.raise_for_status()
        frame = reset_resp.json()
        return frame, frame.get("guid")

    async def _execute_action(
        self, game_id: str, guid: str | None, action: Mapping[str, Any], step: int
    ) -> tuple[dict, float, bool, str | None]:
        if self.harness.mock_api:
            frame, reward, done = self.harness._execute_mock_action(game_id, action, step)
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

        action_resp = await session.post(f"/api/cmd/{action_id}", json=action_payload)
        action_resp.raise_for_status()
        frame = action_resp.json()
        reward = 1.0 if frame.get("state") == "WIN" else 0.0
        done = frame.get("state") in ("WIN", "GAME_OVER")
        return frame, reward, done, frame.get("guid", guid)

    def _submission_row_from_result(self, result: dict | None) -> dict:
        metadata = self._build_metadata(result or {})

        predictions = []
        final_obs = result.get("final_observation") if result else None
        if final_obs:
            if isinstance(final_obs, dict) and "grid" in final_obs:
                predictions = [final_obs["grid"]]
            elif hasattr(final_obs, "get") and final_obs.get("grid"):
                predictions = [final_obs["grid"]]

        debug_steps = result.get("debug_steps") if result else []
        progress_log = []
        prompt_trace = []
        for step in debug_steps or []:
            progress_log.append(
                {
                    "step": step.get("step"),
                    "state_before": step.get("state_before"),
                    "solve_context": step.get("solve_context"),
                    "action_id": step.get("action_id"),
                    "rationale": step.get("rationale"),
                    "reward": step.get("reward"),
                    "done": step.get("done"),
                    "state_after": step.get("state_after"),
                    "board_before": step.get("board_before"),
                    "board_after": step.get("board_after"),
                    "write_trace": step.get("write_trace", []),
                }
            )
            prompt_trace.append(
                {
                    "step": step.get("step"),
                    "available_actions": step.get("available_actions", []),
                    "prompt": step.get("prompt"),
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
        return {
            "game_id": result.get("game_id") if result else "",
            "task_id": result.get("task_id") if result else "",
            "correct": result.get("correct") if result else None,
            "steps": result.get("steps") if result else None,
            "bootstrap_write_trace": result.get("bootstrap_write_trace", []) if result else [],
            "progress_log": progress_log,
            "prompt_trace": prompt_trace,
            "solve_phase_summary": solve_phase_summary,
            "predictions": predictions,
            "confidence": [1.0 if is_correct else 0.0],
            "final_write_trace": result.get("final_write_trace", []) if result else [],
            "metadata": metadata,
        }

    def _build_metadata(self, data: dict) -> dict:
        runtime = float(data.get("runtime_seconds") or 0.0)
        metadata = {
            "model": self.config.get("llm", {}).get("model", "unknown"),
            "memory_enabled": True,
            "runtime_seconds": round(runtime, 2),
            "steps": data.get("steps"),
            "correct": data.get("correct"),
            "tokens_input": data.get("tokens_input"),
            "tokens_output": data.get("tokens_output"),
            "final_state": data.get("final_state"),
        }
        # B89: Add benchmark metrics to metadata
        if data.get("benchmark_metrics"):
            metadata["benchmark_metrics"] = data["benchmark_metrics"]
        if data.get("solve_phase_summary"):
            metadata["solve_phase_summary"] = data["solve_phase_summary"]
        return metadata
