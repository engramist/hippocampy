"""Checkpoint system for durable ARC3 runs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from benchmarks.ab_harness import ABTask


CHECKPOINT_VERSION = 1


@dataclass
class TaskCheckpoint:
    task_id: str
    status: str        # "pending" | "complete" | "failed"
    plan_id: str | None
    result: dict | None
    attempt: int


@dataclass
class RunCheckpoint:
    version: int
    card_id: str
    tasks: Dict[str, TaskCheckpoint]


class CheckpointManager:
    """Atomic checkpoint read/write for ARC runs."""

    CHECKPOINT_DIR = Path.home() / ".sidequests" / "arc_checkpoints"

    def __init__(self, card_id: str):
        self.card_id = card_id
        self._path = self.CHECKPOINT_DIR / f"arc_run_{card_id}.json"

    # ------------------------------------------------------------------

    def load_or_create(self, tasks: List[ABTask]) -> RunCheckpoint:
        """Load an existing checkpoint or create a fresh structure."""
        self._ensure_dir()
        data = self._read()

        if data:
            version = data.get("version", CHECKPOINT_VERSION)
            card_id = data.get("card_id") or self.card_id
            tasks_map = {
                tid: TaskCheckpoint(
                    task_id=tid,
                    status=payload.get("status", "pending"),
                    plan_id=payload.get("plan_id"),
                    result=payload.get("result"),
                    attempt=int(payload.get("attempt", 0)),
                )
                for tid, payload in data.get("tasks", {}).items()
            }
        else:
            version = CHECKPOINT_VERSION
            card_id = self.card_id
            tasks_map: Dict[str, TaskCheckpoint] = {}

        for task in tasks:
            if task.task_id not in tasks_map:
                tasks_map[task.task_id] = TaskCheckpoint(
                    task_id=task.task_id,
                    status="pending",
                    plan_id=None,
                    result=None,
                    attempt=0,
                )

        checkpoint = RunCheckpoint(version=version, card_id=card_id, tasks=tasks_map)
        self.save(checkpoint)
        return checkpoint

    def save(self, checkpoint: RunCheckpoint) -> None:
        """Write the checkpoint atomically (tmp file → replace)."""
        self._ensure_dir()
        payload = {
            "version": checkpoint.version,
            "card_id": checkpoint.card_id,
            "tasks": {
                tid: {
                    "status": cp.status,
                    "plan_id": cp.plan_id,
                    "result": cp.result,
                    "attempt": cp.attempt,
                }
                for tid, cp in checkpoint.tasks.items()
            },
        }
        tmp_path = self._path.with_suffix(".json.tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        os.replace(tmp_path, self._path)

    def mark_complete(self, checkpoint: RunCheckpoint, task_id: str, plan_id: str | None, result: dict) -> None:
        """Persist a successful task outcome immediately."""
        tc = checkpoint.tasks.get(task_id)
        if tc is None:
            tc = TaskCheckpoint(task_id=task_id, status="pending", plan_id=None, result=None, attempt=0)
            checkpoint.tasks[task_id] = tc

        tc.status = "complete"
        tc.plan_id = plan_id
        tc.result = result
        tc.attempt = max(tc.attempt, 1)
        self.save(checkpoint)

    def mark_failed(self, checkpoint: RunCheckpoint, task_id: str, error: str) -> None:
        """Record a failure and increment attempt count."""
        tc = checkpoint.tasks.get(task_id)
        if tc is None:
            tc = TaskCheckpoint(task_id=task_id, status="pending", plan_id=None, result=None, attempt=0)
            checkpoint.tasks[task_id] = tc

        tc.status = "failed"
        tc.attempt += 1
        tc.result = {"error": error}
        self.save(checkpoint)

    # ------------------------------------------------------------------

    def _ensure_dir(self) -> None:
        self.CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.CHECKPOINT_DIR, 0o700)
        except OSError:
            pass

    def _read(self) -> dict | None:
        if not self._path.exists():
            return None
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return None
