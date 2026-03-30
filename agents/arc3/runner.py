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
                result_payload = asdict(task_result)
                result_payload["runtime_seconds"] = round(duration, 2)
                mgr.mark_complete(checkpoint, task.task_id, orchestrator._plan_id, result_payload)
                results.append(self._submission_row_from_result(result_payload))
            except Exception as exc:
                mgr.mark_failed(checkpoint, task.task_id, str(exc))
                logger.error("Task %s failed: %s", task.task_id, exc)

        return results

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

        for attempt in range(1, max_retries + 1):
            # (Re-)initialize the game environment
            frame_response = self._initial_frame(game_id)
            observation = adapter.normalize_observation(frame_response)
            memory_context = await orchestrator.perceive(observation)
            await orchestrator.plan(observation, memory_context)

            steps_this_attempt = 0
            while steps_this_attempt < max_steps:
                # B88 — Update hypothesis engine
                await orchestrator.hypothesize(
                    observation,
                    orchestrator._step_history[-1].get("action_id") if steps_this_attempt > 0 else None,
                    total_steps
                )

                action = await orchestrator.act(observation, memory_context, total_steps + 1)
                total_tokens_input += self.harness.serializer._estimate_tokens(json.dumps(observation))
                total_tokens_output += self.harness.serializer._estimate_tokens(str(action))

                frame_response, reward, done = self._execute_action(game_id, action, total_steps)
                recall_query = "What did I learn from similar puzzles?"
                await adapter.ingest_step(frame_response, action, reward=reward, recall_query=recall_query)
                orchestrator.record_step_result(reward, done)

                observation = adapter.normalize_observation(frame_response)
                state = observation.get("state", "NOT_FINISHED")
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
            await orchestrator.evaluate(success, total_steps, max_steps * max_retries, final_observation=observation)

        return (
            ABTaskResult(
                task_id=task.task_id,
                variant=ABVariant.SIDEQUESTS,
                correct=success,
                steps=total_steps,
                tokens_input=total_tokens_input,
                tokens_output=total_tokens_output,
                error_message=error_msg,
                response_text=f"Solved: {success} in {total_steps} steps ({attempt} attempt(s))",
            ),
            duration,
        )

    def _initial_frame(self, game_id: str) -> dict:
        if self.harness.mock_api:
            return self.harness._get_mock_initial_frame(game_id)
        return self.harness._get_mock_initial_frame(game_id)

    def _execute_action(self, game_id: str, action: Mapping[str, Any], step: int) -> tuple[dict, float, bool]:
        if self.harness.mock_api:
            return self.harness._execute_mock_action(game_id, action, step)
        return self.harness._execute_mock_action(game_id, action, step)

    def _submission_row_from_result(self, result: dict | None) -> dict:
        metadata = self._build_metadata(result or {})
        return {
            "task_id": result.get("task_id") if result else "",
            "predictions": [],
            "confidence": [1.0],
            "metadata": metadata,
        }

    def _build_metadata(self, data: dict) -> dict:
        runtime = float(data.get("runtime_seconds") or 0.0)
        return {
            "model": self.config.get("llm", {}).get("model", "unknown"),
            "memory_enabled": True,
            "runtime_seconds": round(runtime, 2),
            "steps": data.get("steps"),
            "correct": data.get("correct"),
            "tokens_input": data.get("tokens_input"),
            "tokens_output": data.get("tokens_output"),
        }
