"""ARC-AGI-3 adapter that bridges episodes to SideQuests tools."""

from __future__ import annotations

import copy
import logging
from collections import Counter, deque
from typing import Any, Callable, List, Mapping, Optional, Protocol, Sequence

from .schema import (
    ARC3Action,
    ARC3ColorSummary,
    ARC3Observation,
    ARC3ShapeSummary,
)


class BrainClientProtocol(Protocol):
    """Very small protocol covering the MCP tools we actually invoke."""

    async def notify_turn(self, *, role: str, content: str, session_id: str) -> Mapping[str, Any]:
        ...

    async def current_truth(
        self, *, query: str, session_id: str, scope: str, limit: int
    ) -> Mapping[str, Any]:
        ...

    # NEW — Active planning (B67)
    async def register_plan(self, *, goal: str, steps: List[str], session_id: str) -> Mapping[str, Any]:
        ...

    async def report_outcome(self, *, plan_id: str, outcome: str, valence: float, session_id: str) -> Mapping[str, Any]:
        ...

    # NEW — Retrieval tools the agent needs
    async def recall_plans(self, *, goal_query: str, session_id: str, min_valence: float, limit: int) -> Mapping[str, Any]:
        ...

    async def recall_relevant_lessons(self, *, query: str, limit: int) -> Mapping[str, Any]:
        ...

    async def analogical_search(self, *, query: str, current_quest_id: str, limit: int, min_similarity: float) -> Mapping[str, Any]:
        ...

    async def branch_quest(self, *, name: str, purpose: str, parent_quest_id: str) -> Mapping[str, Any]:
        ...


class NoOpBrainClient(BrainClientProtocol):
    """Brain client that does nothing (for baseline mode)."""
    async def notify_turn(self, *, role: str, content: str, session_id: str) -> Mapping[str, Any]:
        return {"status": "skipped"}

    async def current_truth(self, *, query: str, session_id: str, scope: str, limit: int) -> Mapping[str, Any]:
        return {"results": []}

    async def register_plan(self, *, goal: str, steps: List[str], session_id: str) -> Mapping[str, Any]:
        return {"plan_id": None, "warnings": [], "suggestions": []}

    async def report_outcome(self, *, plan_id: str, outcome: str, valence: float, session_id: str) -> Mapping[str, Any]:
        return {"updated": False}

    async def recall_plans(self, *, goal_query: str, session_id: str, min_valence: float, limit: int) -> Mapping[str, Any]:
        return {"plans": []}

    async def recall_relevant_lessons(self, *, query: str, limit: int) -> Mapping[str, Any]:
        return {"lessons": []}

    async def analogical_search(self, *, query: str, current_quest_id: str, limit: int, min_similarity: float) -> Mapping[str, Any]:
        return {"results": []}

    async def branch_quest(self, *, name: str, purpose: str, parent_quest_id: str) -> Mapping[str, Any]:
        return {"side_quest_id": None, "name": name, "parent_quest_id": parent_quest_id}


class LocalBrainClient(BrainClientProtocol):
    """Brain client that calls handlers directly (for augmented mode)."""
    def __init__(self, db, config):
        self.db = db
        self.config = config
        # Late import to avoid circular dependencies
        from mcp_engine.tools import (
            notify_turn, current_truth, register_plan, report_outcome,
            recall_plans, recall_relevant_lessons, analogical_search,
            branch_quest
        )
        self._notify_turn_handler = notify_turn
        self._current_truth_handler = current_truth
        self._register_plan_handler = register_plan
        self._report_outcome_handler = report_outcome
        self._recall_plans_handler = recall_plans
        self._recall_relevant_lessons_handler = recall_relevant_lessons
        self._analogical_search_handler = analogical_search
        self._branch_quest_handler = branch_quest

    async def notify_turn(self, *, role: str, content: str, session_id: str) -> Mapping[str, Any]:
        params = {"role": role, "content": content, "session_id": session_id}
        return await self._notify_turn_handler(params, self.db, self.config)

    async def current_truth(self, *, query: str, session_id: str, scope: str, limit: int) -> Mapping[str, Any]:
        params = {"query": query, "session_id": session_id, "scope": scope, "limit": limit}
        return await self._current_truth_handler(params, self.db, self.config)

    async def register_plan(self, *, goal: str, steps: List[str], session_id: str) -> Mapping[str, Any]:
        params = {"goal": goal, "steps": steps, "session_id": session_id}
        return await self._register_plan_handler(params, self.db, self.config)

    async def report_outcome(self, *, plan_id: str, outcome: str, valence: float, session_id: str) -> Mapping[str, Any]:
        params = {"plan_id": plan_id, "outcome": outcome, "valence": valence, "session_id": session_id}
        return await self._report_outcome_handler(params, self.db, self.config)

    async def recall_plans(self, *, goal_query: str, session_id: str, min_valence: float, limit: int) -> Mapping[str, Any]:
        params = {"goal_query": goal_query, "session_id": session_id, "min_valence": min_valence, "limit": limit}
        return await self._recall_plans_handler(params, self.db, self.config)

    async def recall_relevant_lessons(self, *, query: str, limit: int) -> Mapping[str, Any]:
        params = {"query": query, "limit": limit}
        return await self._recall_relevant_lessons_handler(params, self.db, self.config)

    async def analogical_search(self, *, query: str, current_quest_id: str, limit: int, min_similarity: float) -> Mapping[str, Any]:
        params = {"query": query, "current_quest_id": current_quest_id, "limit": limit, "min_similarity": min_similarity}
        return await self._analogical_search_handler(params, self.db, self.config)

    async def branch_quest(self, *, name: str, purpose: str, parent_quest_id: str) -> Mapping[str, Any]:
        params = {"name": name, "purpose": purpose, "parent_quest_id": parent_quest_id}
        return await self._branch_quest_handler(params, self.db, self.config)


class ARC3Adapter:
    """Normalize ARC episodes and drive SideQuests notify/current_truth calls."""

    def __init__(
        self,
        brain_client: BrainClientProtocol,
        session_id: str,
        dataset_id: str = "arc-agi-3",
        task_id: str = "unknown",
        telemetry_hook: Optional[Callable[[Mapping[str, Any]], None]] = None,
    ) -> None:
        self.brain_client = brain_client
        self.session_id = session_id
        self.dataset_id = dataset_id
        self.task_id = task_id
        self.episode_num = 1
        self.step_num = 0
        self.telemetry_hook = telemetry_hook
        self._telemetry: List[Mapping[str, Any]] = []
        self.logger = logging.getLogger(__name__)

    # --- public helpers ---------------------------------------------------

    def start_episode(self, episode_num: int = 1) -> None:
        """Reset the internal counters for a new ARC episode."""

        self.episode_num = episode_num
        self.step_num = 0

    def normalize_observation(self, raw: Mapping[str, Any]) -> ARC3Observation:
        """Convert the raw FrameResponse into a stable normalized snapshot."""

        grid = self._resolve_grid(raw.get("frame"))
        if not grid:
            raise ValueError("Observation payload missing grid data")

        dataset_id = raw.get("dataset_id") or raw.get("game_id") or self.dataset_id
        task_id = raw.get("task_id") or raw.get("guid") or self.task_id
        episode_num = int(raw.get("episode_num") or raw.get("episode") or self.episode_num)
        step_num = int(raw.get("step_num") or (self.step_num + 1))

        self.dataset_id = dataset_id
        self.task_id = task_id
        self.episode_num = episode_num

        available_actions = self._normalize_available_actions(raw.get("available_actions") or [])
        state = str(raw.get("state") or "NOT_STARTED")
        energy_estimate = self._estimate_energy(grid)

        # B88: Add frame_hash and invariant_regions (populated later by orchestrator)
        from agents.arc3.hypothesis import StateNode
        frame_hash = StateNode.hash_grid(grid)

        return {
            "dataset_id": dataset_id,
            "task_id": task_id,
            "episode_num": episode_num,
            "step_num": step_num,
            "grid": grid,
            "colors": self._summarize_colors(grid),
            "shapes": self._detect_shapes(grid),
            "available_actions": available_actions,
            "state": state,
            "energy_estimate": energy_estimate,
            "frame_hash": frame_hash,
            "invariant_regions": [],
        }

    def normalize_action(
        self, raw_action: Mapping[str, Any]
    ) -> ARC3Action:
        """Turn an ARC action payload into a deterministic change descriptor."""

        action_type = (
            raw_action.get("action_id")
            or raw_action.get("action_type")
            or raw_action.get("type")
            or raw_action.get("name")
        )
        if not action_type:
            raise ValueError("ARC action missing action_type")
        normalized_type = str(action_type).upper()

        coords = self._coords_from_action(raw_action)
        grid_change = self._build_grid_change(raw_action, coords)
        rationale = (
            raw_action.get("rationale")
            or raw_action.get("reasoning")
            or raw_action.get("comment")
            or "ARC action"
        )

        deterministic_id = self._build_action_id(normalized_type, grid_change)

        metadata = dict(raw_action.get("metadata") or {})

        return {
            "action_type": normalized_type,
            "grid_change": grid_change,
            "rationale": str(rationale),
            "deterministic_id": deterministic_id,
            "metadata": metadata,
        }

    def to_turn_narrative(
        self,
        obs: ARC3Observation,
        action: ARC3Action,
        reward: Optional[float] = None,
    ) -> str:
        """Summarize a step for passive ingestion."""

        coords = action["grid_change"].get("coords")
        coords_text = f"cell {coords}" if coords else "the grid"
        change_value = action["grid_change"].get("value")
        rationale = action["rationale"]
        reward_text = f" reward {reward:.2f}" if reward is not None else ""

        return (
            f"[{obs['dataset_id']}:{obs['task_id']}] "
            f"Episode {obs['episode_num']} · Step {obs['step_num']}: "
            f"{action['action_type']} at {coords_text} sets {change_value} · {rationale}.{reward_text}"
        )

    async def ingest_step(
        self,
        raw_observation: Mapping[str, Any],
        raw_action: Mapping[str, Any],
        reward: Optional[float] = None,
        recall_query: Optional[str] = None,
    ) -> Mapping[str, Any]:
        """Normalize, log, ingest, and optionally recall memory for one ARC turn."""

        memory = None
        if recall_query:
            memory = await self.current_truth(recall_query)

        normalized_obs = self.normalize_observation(raw_observation)
        normalized_action = self.normalize_action(raw_action)
        narrative = self.to_turn_narrative(normalized_obs, normalized_action, reward)
        await self.notify_turn(narrative)

        entry = {
            "observation": normalized_obs,
            "action": normalized_action,
            "reward": reward,
            "memory": memory,
        }
        self._telemetry.append(copy.deepcopy(entry))
        if self.telemetry_hook:
            self.telemetry_hook(entry)

        self.step_num += 1
        return {"narrative": narrative, "memory": memory}

    async def notify_turn(self, content: str, role: str = "assistant") -> Mapping[str, Any]:
        """Forward the turn narrative to SideQuests."""

        return await self.brain_client.notify_turn(
            role=role, content=content, session_id=self.session_id
        )

    async def current_truth(
        self,
        query: str,
        scope: str = "branch",
        limit: int = 5,
    ) -> Mapping[str, Any]:
        """Recall relevant memory for the current session."""

        return await self.brain_client.current_truth(
            query=query, session_id=self.session_id, scope=scope, limit=limit
        )

    def get_telemetry_trace(self) -> List[Mapping[str, Any]]:
        """Return a deterministic replay trace of every logged step."""

        return [copy.deepcopy(entry) for entry in self._telemetry]

    # --- helper utilities ----------------------------------------------

    def _resolve_grid(self, frame_obj: Any) -> List[List[int]]:
        if not frame_obj or not isinstance(frame_obj, list):
            return []

        first = frame_obj[0]
        if isinstance(first, list) and first and isinstance(first[0], list):
            candidate = first
        elif isinstance(first, list):
            candidate = frame_obj
        else:
            return []

        if not candidate or not isinstance(candidate[0], list):
            return []

        return [self._to_row(row) for row in candidate]

    def _normalize_available_actions(self, actions: Sequence[Any]) -> List[str]:
        normalized: List[str] = []
        for action in actions:
            if isinstance(action, int):
                normalized.append(f"ACTION{action}")
                continue

            text = str(action).strip()
            if not text:
                continue
            if text.isdigit():
                normalized.append(f"ACTION{text}")
            else:
                normalized.append(text.upper())
        return normalized

    def _to_row(self, row: Sequence[Any]) -> List[int]:
        return [int(cell) for cell in row]

    def _summarize_colors(self, grid: List[List[int]]) -> List[ARC3ColorSummary]:
        counts: Counter[int] = Counter()
        for row in grid:
            for pixel in row:
                counts[int(pixel)] += 1
        return [
            {"value": value, "count": count}
            for value, count in sorted(counts.items(), key=lambda item: item[0])
        ]

    def _detect_shapes(self, grid: List[List[int]]) -> List[ARC3ShapeSummary]:
        if not grid or not grid[0]:
            return []

        rows, cols = len(grid), len(grid[0])
        visited = [[False] * cols for _ in range(rows)]
        shapes: List[ARC3ShapeSummary] = []

        for r in range(rows):
            for c in range(cols):
                if visited[r][c]:
                    continue
                target_value = grid[r][c]
                coords: List[tuple[int, int]] = []
                queue = deque([(r, c)])
                visited[r][c] = True
                while queue:
                    pr, pc = queue.popleft()
                    coords.append((pr, pc))
                    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nr, nc = pr + dr, pc + dc
                        if (
                            0 <= nr < rows
                            and 0 <= nc < cols
                            and not visited[nr][nc]
                            and grid[nr][nc] == target_value
                        ):
                            visited[nr][nc] = True
                            queue.append((nr, nc))
                coords_sorted = sorted(coords)
                shapes.append(
                    {
                        "color": int(target_value),
                        "size": len(coords_sorted),
                        "coords": coords_sorted,
                    }
                )
        shapes.sort(key=lambda shape: (shape["color"], shape["size"], shape["coords"]))
        return shapes

    def _estimate_energy(self, grid: List[List[int]]) -> float:
        """Estimate energy/life bar from the bottom rows of the 64x64 grid."""
        return 1.0

    def _coords_from_action(self, raw_action: Mapping[str, Any]) -> Optional[List[int]]:
        if "coords" in raw_action:
            coords = raw_action["coords"]
            if isinstance(coords, Sequence) and len(coords) >= 2:
                return [int(coords[0]), int(coords[1])]
        row = raw_action.get("row")
        col = raw_action.get("col")
        if row is not None and col is not None:
            return [int(row), int(col)]
        x = raw_action.get("x")
        y = raw_action.get("y")
        if x is not None and y is not None:
            return [int(y), int(x)]
        return None

    def _build_grid_change(
        self, raw_action: Mapping[str, Any], coords: Optional[List[int]]
    ) -> Mapping[str, Any]:
        change: dict[str, Any] = {}
        if coords is not None:
            change["coords"] = coords
        for field in ("value", "target_value", "prev_value", "direction"):
            if field in raw_action:
                change[field] = raw_action[field]
        return change

    def _build_action_id(self, action_type: str, grid_change: Mapping[str, Any]) -> str:
        parts = [action_type]
        coords = grid_change.get("coords")
        if coords:
            parts.append(f"coords={coords[0]}:{coords[1]}")
        if "value" in grid_change:
            parts.append(f"new={grid_change['value']}")
        if "prev_value" in grid_change:
            parts.append(f"prev={grid_change['prev_value']}")
        return "|".join(parts)
