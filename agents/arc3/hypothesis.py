"""Hypothesis Engine — game-theory-driven puzzle reasoning.

Three core components:
  StateGraph         — ephemeral in-memory directed graph of game states
  InvariantDetector  — finds static vs dynamic grid regions
  HypothesisManager  — generates, tracks, prunes, and distills hypotheses
"""

from __future__ import annotations
import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ── Data Structures ──────────────────────────────────────────────────

@dataclass
class StateNode:
    """One observed game state."""
    grid_hash: str                    # SHA-256 of flattened grid
    step: int                         # global step number when observed
    key_features: Dict[str, Any]      # color_counts, shape_count, dominant_color
    energy_estimate: Optional[float]  # from InvariantDetector HUD analysis
    grid_snapshot: List[List[int]]    # flattened 2D (first layer only) for diff

    @staticmethod
    def hash_grid(grid: Any) -> str:
        if not grid:
            return "empty"
        # Use entire grid for hashing, handle 2D or 3D
        flat = str(grid)
        return hashlib.sha256(flat.encode()).hexdigest()[:16]


@dataclass
class Transition:
    """One observed state→state edge."""
    from_hash: str
    to_hash: str
    action: str                       # e.g. "ACTION3"
    step: int
    diff_summary: str                 # human-readable diff
    pixels_changed: int               # count of changed cells
    regions_changed: List[str]        # "top-left", "center", "HUD-row-61", etc.


@dataclass
class Hypothesis:
    """One hypothesis about the game's rules."""
    id: str                           # "h-{uuid[:8]}"
    description: str                  # "ACTION3 moves player right by ~4 pixels"
    category: str                     # action_semantic | hud_element | rule | invariant
    confidence: float = 0.5           # 0.0–1.0, starts at 0.5
    support_count: int = 0
    contradiction_count: int = 0
    status: str = "active"            # active | confirmed | refuted | pruned
    source_transitions: List[int] = field(default_factory=list)  # step numbers

    def update(self, supports: bool) -> None:
        """Bayesian-ish confidence update."""
        if supports:
            self.support_count += 1
        else:
            self.contradiction_count += 1
        total = self.support_count + self.contradiction_count
        if total > 0:
            # confidence = support_count / (support_count + contradiction_count)
            self.confidence = self.support_count / total
        
        # Auto-transition status (Constants from plan: MIN_EVIDENCE=3, CONFIRM_THRESHOLD=0.8, PRUNE_THRESHOLD=0.2)
        if total >= 3:
            if self.confidence >= 0.8:
                self.status = "confirmed"
            elif self.confidence <= 0.2:
                self.status = "refuted"


# ── State Graph ──────────────────────────────────────────────────────

class StateGraph:
    """In-memory directed graph: nodes=states, edges=actions.

    Ephemeral — destroyed on retry, rebuilt from scratch.
    Used for loop detection, path analysis, unexplored action discovery.
    """

    def __init__(self) -> None:
        self.nodes: Dict[str, StateNode] = {}                  # hash → StateNode
        self.edges: Dict[str, List[Transition]] = defaultdict(list)  # from_hash → [Transition]
        self._visit_order: List[str] = []                       # ordered list of visited hashes

    def add_state(self, node: StateNode) -> bool:
        """Add a state. Returns True if this is a NEW state, False if revisit."""
        is_new = node.grid_hash not in self.nodes
        if is_new:
            self.nodes[node.grid_hash] = node
        self._visit_order.append(node.grid_hash)
        return is_new

    def add_transition(self, transition: Transition) -> None:
        self.edges[transition.from_hash].append(transition)

    def detect_loop(self) -> Optional[str]:
        """If the latest state was visited before, return its hash."""
        if len(self._visit_order) < 2:
            return None
        latest = self._visit_order[-1]
        if latest in self._visit_order[:-1]:
            return latest
        return None

    def get_unexplored_actions(
        self, from_hash: str, all_actions: List[str]
    ) -> List[str]:
        """Actions not yet tried from this state."""
        tried = {t.action for t in self.edges.get(from_hash, [])}
        return [a for a in all_actions if a not in tried]

    def get_action_effects(self, action: str) -> List[Transition]:
        """All transitions caused by a given action (across all states)."""
        results = []
        for transitions in self.edges.values():
            for t in transitions:
                if t.action == action:
                    results.append(t)
        return results

    def clear(self) -> None:
        """Reset for a new attempt."""
        self.nodes.clear()
        self.edges.clear()
        self._visit_order.clear()


# ── Invariant Detector ───────────────────────────────────────────────

class InvariantDetector:
    """Discovers which grid regions are static vs dynamic.

    Compares frames across multiple steps. Regions that NEVER change
    are structural (walls, HUD, decoration). Regions that change with
    specific actions reveal game mechanics.
    """

    def __init__(self, min_frames: int = 3) -> None:
        self.min_frames = min_frames
        self._frames: List[List[List[int]]] = []  # 2D snapshots (first layer)

    def add_frame(self, grid_2d: List[List[int]]) -> None:
        self._frames.append(grid_2d)

    def find_static_rows(self) -> List[int]:
        """Rows that haven't changed across all stored frames."""
        if len(self._frames) < self.min_frames:
            return []
        static = []
        height = len(self._frames[0])
        for row_idx in range(height):
            reference = self._frames[0][row_idx]
            if all(
                len(f) > row_idx and f[row_idx] == reference
                for f in self._frames[1:]
            ):
                static.append(row_idx)
        return static

    def find_dynamic_regions(self) -> List[Dict[str, Any]]:
        """Regions that changed between consecutive frames."""
        if len(self._frames) < 2:
            return []
        regions = []
        prev = self._frames[-2]
        curr = self._frames[-1]
        changed_rows = set()
        changed_cols = set()
        for r in range(min(len(prev), len(curr))):
            for c in range(min(len(prev[r]), len(curr[r]))):
                if prev[r][c] != curr[r][c]:
                    changed_rows.add(r)
                    changed_cols.add(c)
        if changed_rows:
            regions.append({
                "rows": sorted(changed_rows),
                "cols": sorted(changed_cols),
                "row_range": (min(changed_rows), max(changed_rows)),
                "col_range": (min(changed_cols), max(changed_cols)),
            })
        return regions

    def estimate_hud_rows(self) -> List[int]:
        """Guess HUD rows: static rows near the bottom of the grid
        that contain bar-like patterns (multiple colors, partial fill)."""
        static = self.find_static_rows()
        if not self._frames:
            return []
        grid_height = len(self._frames[0])
        # HUD is typically in the bottom 10% of the grid
        bottom_threshold = int(grid_height * 0.9)
        hud_candidates = [r for r in static if r >= bottom_threshold]
        return hud_candidates

    def clear(self) -> None:
        self._frames.clear()


# ── Hypothesis Manager ───────────────────────────────────────────────

class HypothesisManager:
    """Top-level controller: generate, track, prune, distill hypotheses.

    Owns the StateGraph and InvariantDetector. Called by the orchestrator's
    hypothesize() step.
    """

    CONFIRM_THRESHOLD: float = 0.8
    PRUNE_THRESHOLD: float = 0.2
    MIN_EVIDENCE: int = 3
    EXPLORE_ENERGY_FLOOR: float = 0.3  # below this, only exploit

    def __init__(self, brain_client: Any, session_id: str) -> None:
        self.brain = brain_client
        self.session_id = session_id
        self.graph = StateGraph()
        self.invariant_detector = InvariantDetector()
        self.hypotheses: Dict[str, Hypothesis] = {}
        self._prev_state_hash: Optional[str] = None
        self._prev_grid_2d: Optional[List[List[int]]] = None

    def observe(
        self,
        grid: Any,
        action_taken: Optional[str],
        step: int,
        available_actions: List[str],
        observation: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Main entry point — called once per frame."""
        # 1. Hash and register state
        grid_hash = StateNode.hash_grid(grid)
        
        # Resolve 2D grid for analysis
        if grid and isinstance(grid[0], list) and grid[0] and isinstance(grid[0][0], list):
             # 3D: [layer][row][col]
             grid_2d = grid[0]
        else:
             # 2D: [row][col]
             grid_2d = grid or []

        features = {
            "colors": observation.get("colors", []),
            "shapes": observation.get("shapes", []),
        }
        node = StateNode(
            grid_hash=grid_hash,
            step=step,
            key_features=features,
            energy_estimate=observation.get("energy_estimate"),
            grid_snapshot=grid_2d,
        )
        is_new = self.graph.add_state(node)

        # 2. Record transition
        if action_taken and self._prev_state_hash:
            diff = self._compute_diff(self._prev_grid_2d, grid_2d)
            transition = Transition(
                from_hash=self._prev_state_hash,
                to_hash=grid_hash,
                action=action_taken,
                step=step,
                diff_summary=diff["summary"],
                pixels_changed=diff["pixels_changed"],
                regions_changed=diff.get("regions", []),
            )
            self.graph.add_transition(transition)

            # 3. Generate / update hypotheses from this transition
            self._process_transition(transition, diff)

        # 4. Feed invariant detector
        self.invariant_detector.add_frame(grid_2d)

        # 5. Loop detection
        loop_hash = self.graph.detect_loop()

        # 6. Invariant analysis
        hud_rows = self.invariant_detector.estimate_hud_rows()
        static_rows = self.invariant_detector.find_static_rows()

        # 7. Unexplored actions from current state
        unexplored = self.graph.get_unexplored_actions(grid_hash, available_actions)

        # 8. Explore/exploit policy
        energy = observation.get("energy_estimate", 1.0)
        policy = self._decide_policy(energy)

        # Update tracking
        self._prev_state_hash = grid_hash
        self._prev_grid_2d = grid_2d

        return {
            "loop_detected": loop_hash is not None,
            "loop_hash": loop_hash,
            "is_new_state": is_new,
            "active_hypotheses": self._get_by_status("active"),
            "confirmed_hypotheses": self._get_by_status("confirmed"),
            "refuted_hypotheses": self._get_by_status("refuted"),
            "unexplored_actions": unexplored,
            "invariant_rows": static_rows,
            "hud_rows": hud_rows,
            "explore_vs_exploit": policy,
            "energy_from_hud": self._estimate_energy_from_hud(hud_rows, grid_2d),
            "state_count": len(self.graph.nodes),
            "transition_count": sum(len(v) for v in self.graph.edges.values()),
        }

    def _process_transition(self, t: Transition, diff: Dict) -> None:
        """Generate or update hypotheses from observed transition."""
        # Hypothesis: what does this action do?
        action_hyp_id = f"action-{t.action}"
        if action_hyp_id not in self.hypotheses:
            self.hypotheses[action_hyp_id] = Hypothesis(
                id=action_hyp_id,
                description=f"{t.action}: {t.diff_summary}",
                category="action_semantic",
            )
        
        # Check consistency: does this action always produce similar effects?
        prior_effects = self.graph.get_action_effects(t.action)
        if len(prior_effects) >= 2:
            # Simple consistency check: pixel change delta < 20
            consistent = all(
                abs(e.pixels_changed - t.pixels_changed) < 20
                for e in prior_effects[:-1]
            )
            self.hypotheses[action_hyp_id].update(supports=consistent)
        
        # Additional: record step
        self.hypotheses[action_hyp_id].source_transitions.append(t.step)

        # Hypothesis: no-change means wall/obstacle
        if t.pixels_changed == 0:
            wall_id = f"wall-{t.from_hash}-{t.action}"
            if wall_id not in self.hypotheses:
                self.hypotheses[wall_id] = Hypothesis(
                    id=wall_id,
                    description=f"{t.action} from state {t.from_hash[:8]} produces no change — blocked by obstacle",
                    category="rule",
                    confidence=0.7,
                    support_count=1,
                )

    def _compute_diff(
        self,
        prev: Optional[List[List[int]]],
        curr: List[List[int]],
    ) -> Dict[str, Any]:
        """Compute grid diff between two 2D frames."""
        if not prev or not curr:
            return {"summary": "initial frame", "pixels_changed": 0, "regions": []}
        changed = 0
        changed_positions = []
        for r in range(min(len(prev), len(curr))):
            for c in range(min(len(prev[r]), len(curr[r]))):
                if prev[r][c] != curr[r][c]:
                    changed += 1
                    changed_positions.append((r, c))
        if not changed_positions:
            return {"summary": "no visible change", "pixels_changed": 0, "regions": []}
        min_r = min(p[0] for p in changed_positions)
        max_r = max(p[0] for p in changed_positions)
        min_c = min(p[1] for p in changed_positions)
        max_c = max(p[1] for p in changed_positions)
        summary = (
            f"{changed} pixels changed in rows {min_r}-{max_r}, "
            f"cols {min_c}-{max_c}"
        )
        return {"summary": summary, "pixels_changed": changed, "regions": [f"r{min_r}-{max_r}_c{min_c}-{max_c}"]}

    def _decide_policy(self, energy: float) -> str:
        """Explore/exploit based on energy and hypothesis landscape."""
        active = [h for h in self.hypotheses.values() if h.status == "active"]
        confirmed = [h for h in self.hypotheses.values() if h.status == "confirmed"]
        if energy < self.EXPLORE_ENERGY_FLOOR:
            return "exploit"
        if not confirmed and active:
            return "explore"
        if len(active) > len(confirmed):
            return "explore"
        return "exploit"

    def _estimate_energy_from_hud(
        self, hud_rows: List[int], grid_2d: List[List[int]]
    ) -> Optional[float]:
        """Estimate energy from discovered HUD rows (hypothesis-driven)."""
        if not hud_rows or not grid_2d:
            return None
        # Look for bar-like pattern in HUD rows
        for row_idx in hud_rows:
            if row_idx >= len(grid_2d):
                continue
            row = grid_2d[row_idx]
            if not row:
                continue
            non_zero = sum(1 for v in row if v != 0)
            total = len(row)
            ratio = non_zero / total if total > 0 else 0
            if 0.02 < ratio < 0.98:  # looks like a partial bar
                return ratio
        return None

    def _get_by_status(self, status: str) -> List[Dict[str, Any]]:
        return [
            {"id": h.id, "description": h.description, "confidence": round(h.confidence, 2), "category": h.category}
            for h in self.hypotheses.values()
            if h.status == status
        ]

    async def distill_to_brain(self) -> int:
        """Flush confirmed + refuted hypotheses to SideQuests as durable knowledge.

        Called on WIN or GAME_OVER boundaries. Returns count of hypotheses flushed.
        """
        flushed = 0
        for h in self.hypotheses.values():
            if h.status in ("confirmed", "refuted"):
                text = f"[{h.status.upper()}] {h.description} (confidence: {h.confidence:.2f}, evidence: {h.support_count}+/{h.contradiction_count}-)"
                try:
                    await self.brain.notify_turn(
                        role="assistant",
                        content=text,
                        session_id=self.session_id,
                    )
                    flushed += 1
                except Exception as e:
                    logger.error(f"Failed to distill hypothesis {h.id}: {e}")
        return flushed

    def reset_graph(self) -> None:
        """Clear ephemeral state for retry. Hypotheses survive."""
        self.graph.clear()
        self.invariant_detector.clear()
        self._prev_state_hash = None
        self._prev_grid_2d = None
