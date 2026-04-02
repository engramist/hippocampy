"""ARC Solve Engine — goal-directed strategy from game archetype classification.

Five cognitive components:
  ArchetypeClassifier   — What kind of game is this? (centroid-style classification)
  ObjectRoleMapper      — What role does each object play?
  VictoryHypothesizer   — What does winning look like? (inverted pyramid)
  DissonanceDetector    — Is our model wrong? (negative valence encoding)
  PlanChunker           — How do we get there? (BFS + register_plan)
"""

from __future__ import annotations
import logging
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from agents.arc3.prompts import VICTORY_HYPOTHESIS_TEMPLATE

logger = logging.getLogger(__name__)


# ── Enumerations ──────────────────────────────────────────────────────

class GameArchetype(str, Enum):
    RACE     = "race"      # linear path, reach goal first
    SPACE    = "space"     # territorial, open grid positioning
    CHASE    = "chase"     # pursuer/flee dynamic
    DISPLACE = "displace"  # remove targets from board
    UNKNOWN  = "unknown"


class RoleType(str, Enum):
    PLAYER      = "player"
    ENEMY       = "enemy"
    GOAL        = "goal"
    WALL        = "wall"
    COLLECTIBLE = "collectible"
    EXIT        = "exit"
    DECORATION  = "decoration"
    UNKNOWN     = "unknown"


class VictoryType(str, Enum):
    REACH_GOAL       = "reach_goal"
    COLLECT_ALL      = "collect_all"
    SURVIVE          = "survive"
    SCORE_THRESHOLD  = "score_threshold"
    ELIMINATE        = "eliminate"
    UNKNOWN          = "unknown"


# ── Data Structures ───────────────────────────────────────────────────

@dataclass
class ObjectRole:
    color_id: int
    role: RoleType = RoleType.UNKNOWN
    confidence: float = 0.5
    evidence_steps: List[int] = field(default_factory=list)
    estimated_position: Optional[Dict[str, float]] = None  # {"row": r, "col": c}


@dataclass
class VictoryCondition:
    condition_type: VictoryType = VictoryType.UNKNOWN
    description: str = ""
    target_color_id: Optional[int] = None   # which object to reach/collect/eliminate
    confidence: float = 0.0
    evidence_steps: List[int] = field(default_factory=list)
    source: str = "unknown"                  # "recall_plans" | "llm" | "lesson"


@dataclass
class PlanChunk:
    description: str
    estimated_actions: List[str] = field(default_factory=list)   # e.g. ["ACTION1","ACTION1","ACTION2"]
    progress_score: float = 0.0             # 0.0–1.0, increases as chunk executes
    steps_executed: int = 0
    success_condition: str = ""
    source: str = "bfs"                     # "bfs" | "directional" | "llm"
    graduation_score: float = 0.0
    graduation_reason: str = ""
    graduation_components: Dict[str, float] = field(default_factory=dict)
    plan_id: Optional[str] = None           # SideQuests plan_id for this chunk


@dataclass
class ChunkLedgerEntry:
    """B124: Track chunk lifecycle for prompt visibility and exploration prevention."""
    description: str
    status: str  # "pending" | "active" | "completed" | "failed"
    steps_used: int
    outcome_summary: str


@dataclass
class SolveContext:
    archetype: GameArchetype = GameArchetype.UNKNOWN
    archetype_confidence: float = 0.0
    object_roles: Dict[int, ObjectRole] = field(default_factory=dict)
    victory_condition: Optional[VictoryCondition] = None
    active_chunk: Optional[PlanChunk] = None
    dissonance_detected: bool = False
    dissonance_reason: str = ""
    strategy_summary: str = ""
    chunk_ledger: List["ChunkLedgerEntry"] = field(default_factory=list)


# ── Archetype Classifier ──────────────────────────────────────────────

class ArchetypeClassifier:
    """Classifies game archetype from hypothesis context + analogical_search.

    Algorithm:
      1. Extract signals from hypothesis_context (moving object count, convergence,
         reward pattern, HUD presence).
      2. Score each archetype against signals.
      3. Call analogical_search to find structurally similar past games.
      4. Past game archetype labels vote (weight: 0.4 algorithmic, 0.6 analogy).
      5. Lock when composite confidence > LOCK_THRESHOLD.
    """

    LOCK_THRESHOLD: float = 0.65
    MIN_OBSERVATIONS: int = 5              # don't classify before seeing 5 frames
    CONSISTENCY_BONUS: float = 0.04       # per-step bonus when same archetype wins consecutively

    def __init__(self) -> None:
        self._observation_count: int = 0
        self._signal_history: List[Dict[str, Any]] = []
        self._consecutive_best: GameArchetype = GameArchetype.UNKNOWN
        self._consecutive_count: int = 0

    def _extract_signals(self, hypothesis_context: Dict[str, Any]) -> Dict[str, Any]:
        """Pull archetype-relevant signals from HypothesisManager output."""
        action_facts = hypothesis_context.get("action_facts", [])
        # Count how many actions show deterministic single-object movement
        directional_facts = [f for f in action_facts
                             if f.get("fact_type") == "deterministic_effect"]
        # Check for convergence: do any two distinct moving regions approach each other?
        transitions = hypothesis_context.get("last_transition_effect") or {}
        has_hud = bool(hypothesis_context.get("hud_rows"))
        reward_trend = sum(
            1 for f in action_facts if (f.get("value_status") or "") == "valuable"
        )
        path_hypotheses = hypothesis_context.get("path_hypotheses", [])
        return {
            "directional_actions": len(directional_facts),
            "has_hud": has_hud,
            "reward_trend": reward_trend,
            "path_hypotheses_count": len(path_hypotheses),
            "pixels_changed": transitions.get("pixels_changed", 0),
            "loop_detected": bool(hypothesis_context.get("loop_detected")),
        }

    def _score_archetypes(self, signals: Dict[str, Any]) -> Dict[GameArchetype, float]:
        """Heuristic scoring of each archetype from signals."""
        scores: Dict[GameArchetype, float] = {a: 0.0 for a in GameArchetype}
        d = signals["directional_actions"]
        hud = signals["has_hud"]
        reward = signals["reward_trend"]

        # RACE: few directional actions, HUD (energy/score bar), monotonic reward
        if hud and d >= 1 and reward >= 1:
            scores[GameArchetype.RACE] += 0.5
        # CHASE: multiple directional actions, varying reward, no strong single path
        if d >= 2 and signals["path_hypotheses_count"] == 0:
            scores[GameArchetype.CHASE] += 0.4
        # DISPLACE: reward correlates with pixel removal (pixels_changed drops over time)
        if reward >= 2 and signals["pixels_changed"] < 20:
            scores[GameArchetype.DISPLACE] += 0.35
        # SPACE: many path hypotheses, variable reward
        if signals["path_hypotheses_count"] >= 2:
            scores[GameArchetype.SPACE] += 0.45
        return scores

    def update(
        self,
        hypothesis_context: Dict[str, Any],
    ) -> tuple[GameArchetype, float]:
        """Update archetype estimate from latest hypothesis context.

        Returns (archetype, confidence). Does NOT call SideQuests — caller must
        supply analogy_votes from analogical_search results.
        """
        self._observation_count += 1
        if self._observation_count < self.MIN_OBSERVATIONS:
            return GameArchetype.UNKNOWN, 0.0

        signals = self._extract_signals(hypothesis_context)
        self._signal_history.append(signals)

        scores = self._score_archetypes(signals)
        best = max(scores, key=lambda a: scores[a])
        best_score = scores[best]
        if best_score < 0.3:
            self._consecutive_best = GameArchetype.UNKNOWN
            self._consecutive_count = 0
            return GameArchetype.UNKNOWN, best_score

        # Temporal consistency boost: repeated same winner builds conviction
        if best == self._consecutive_best:
            self._consecutive_count += 1
        else:
            self._consecutive_best = best
            self._consecutive_count = 1
        boosted = min(best_score + self.CONSISTENCY_BONUS * (self._consecutive_count - 1), 0.95)
        return best, boosted

    def apply_analogy_votes(
        self,
        archetype: GameArchetype,
        confidence: float,
        analogy_results: List[Dict[str, Any]],
    ) -> tuple[GameArchetype, float]:
        """Blend analogy votes into the archetype estimate (weight 0.6 analogy)."""
        if not analogy_results:
            return archetype, confidence

        vote_scores: Dict[str, float] = {}
        for result in analogy_results[:5]:
            # Analogical results include text_raw; parse archetype tag if present
            text = (result.get("text_raw") or "").lower()
            for a in GameArchetype:
                if a.value in text and a != GameArchetype.UNKNOWN:
                    vote_scores[a.value] = vote_scores.get(a.value, 0.0) + result.get("similarity", 0.5)

        if not vote_scores:
            return archetype, confidence

        best_vote = max(vote_scores, key=lambda k: vote_scores[k])
        vote_conf = min(vote_scores[best_vote] / len(analogy_results), 0.9)

        # Blend: 0.4 algorithmic + 0.6 analogical
        blended = 0.4 * confidence
        if best_vote == archetype.value:
            blended += 0.6 * vote_conf
        else:
            # Disagreement: cap confidence
            blended = min(blended, 0.5)
            if vote_conf > confidence:
                try:
                    return GameArchetype(best_vote), blended
                except ValueError:
                    return archetype, blended

        return archetype, min(blended, 0.95)


# ── Object Role Mapper ────────────────────────────────────────────────

def _compute_centroids(grid: List[List[int]]) -> Dict[int, Dict[str, float]]:
    """Return per-color centroid and bounds from a grid."""
    from collections import defaultdict

    pixels: Dict[int, List[tuple[int, int]]] = defaultdict(list)
    for r, row in enumerate(grid or []):
        for c, value in enumerate(row or []):
            pixels[value].append((r, c))

    centroids: Dict[int, Dict[str, float]] = {}
    for color_id, points in pixels.items():
        if not points:
            continue
        rows = [point[0] for point in points]
        cols = [point[1] for point in points]
        centroids[color_id] = {
            "row": sum(rows) / len(rows),
            "col": sum(cols) / len(cols),
            "count": float(len(points)),
            "row_start": float(min(rows)),
            "row_end": float(max(rows)),
            "col_start": float(min(cols)),
            "col_end": float(max(cols)),
        }
    return centroids


def _trend_direction_from_fact(action_facts: List[Dict[str, Any]], action_id: Optional[str]) -> Optional[str]:
    if not action_id:
        return None
    fact = next((item for item in action_facts if item.get("action") == action_id), None)
    if not fact:
        return None
    trend = fact.get("trend") or {}
    direction = str(trend.get("direction") or "").lower()
    if direction:
        return direction
    description = str(fact.get("description") or "").lower()
    if "leftward drift" in description or "drift left" in description or "moves left" in description:
        return "left"
    if "rightward drift" in description or "drift right" in description or "moves right" in description:
        return "right"
    if "upward drift" in description or "drift up" in description or "moves up" in description:
        return "up"
    if "downward drift" in description or "drift down" in description or "moves down" in description:
        return "down"
    return None


def _direction_vector(direction: Optional[str]) -> Optional[tuple[float, float]]:
    if direction == "left":
        return (0.0, -1.0)
    if direction == "right":
        return (0.0, 1.0)
    if direction == "up":
        return (-1.0, 0.0)
    if direction == "down":
        return (1.0, 0.0)
    return None


def _value_in_range(value: float, minimum: float, maximum: float) -> bool:
    return minimum <= value <= maximum


class ObjectRoleMapper:
    """Assigns semantic roles to color groups from transitions + invariants.

    Uses evidence fusion:
      - invariant/static row coverage and motion stability for WALL
      - centroid motion that matches inferred operator effects for PLAYER
      - small, stationary, non-background objects for GOAL
      - optional reward/changed-center fallback when the frame lacks richer geometry
    """

    PLAYER_MIN_MATCHES: int = 2
    PLAYER_MIN_MATCH_RATE: float = 0.6
    WALL_MIN_STATIONARY_STEPS: int = 2
    WALL_MIN_OBSERVED_COUNT: int = 2
    WALL_MIN_EXTENT_SPAN: float = 1.0
    GOAL_MAX_COUNT_FRACTION: float = 0.02
    GOAL_MIN_STATIONARY_STEPS: int = 1
    GOAL_MIN_SCORE: float = 0.55
    BACKGROUND_COLOR: int = 0
    EPSILON: float = 0.35

    def __init__(self) -> None:
        self._prev_centroids: Dict[int, Dict[str, float]] = {}
        self._movement_evidence: Dict[int, List[Dict[str, Any]]] = {}
        self._local_activity_evidence: Dict[int, List[Dict[str, Any]]] = {}
        self._stationary_steps: Dict[int, int] = {}
        self._centroid_history: Dict[int, List[Dict[str, float]]] = {}

    def _color_only_in_rows(
        self,
        grid: List[List[int]],
        color_id: int,
        allowed_rows: set[int],
    ) -> bool:
        if not grid or not allowed_rows:
            return False
        seen = False
        for row_idx, row in enumerate(grid):
            for value in row:
                if value != color_id:
                    continue
                seen = True
                if row_idx not in allowed_rows:
                    return False
        return seen

    def _directional_match(
        self,
        delta_row: float,
        delta_col: float,
        direction: Optional[str],
    ) -> bool:
        vec = _direction_vector(direction)
        if vec is None:
            return False
        dr, dc = vec
        if dr != 0.0 and delta_row * dr <= self.EPSILON:
            return False
        if dc != 0.0 and delta_col * dc <= self.EPSILON:
            return False
        return abs(delta_row) > self.EPSILON or abs(delta_col) > self.EPSILON

    def _near_changed_center(
        self,
        centroid: Dict[str, float],
        changed_center: Dict[str, Any] | None,
    ) -> bool:
        if not centroid or not changed_center:
            return False
        row = float(changed_center.get("row", centroid.get("row", 0.0)))
        col = float(changed_center.get("col", centroid.get("col", 0.0)))
        return abs(centroid["row"] - row) <= 1.5 and abs(centroid["col"] - col) <= 1.5

    def _changed_bbox_center(
        self,
        changed_region: Dict[str, Any],
    ) -> Dict[str, float] | None:
        row_range = changed_region.get("row_range")
        col_range = changed_region.get("col_range")
        if not row_range or not col_range:
            return None
        return {
            "row": float(row_range[0] + row_range[1]) / 2.0,
            "col": float(col_range[0] + col_range[1]) / 2.0,
        }

    def _in_changed_bbox(
        self,
        centroid: Dict[str, float],
        changed_region: Dict[str, Any],
        padding: float = 1.5,
    ) -> bool:
        row_range = changed_region.get("row_range")
        col_range = changed_region.get("col_range")
        if not row_range or not col_range:
            return False
        return (
            _value_in_range(float(centroid["row"]), float(row_range[0]) - padding, float(row_range[1]) + padding)
            and _value_in_range(float(centroid["col"]), float(col_range[0]) - padding, float(col_range[1]) + padding)
        )

    def _has_active_evidence(self, color_id: int) -> bool:
        """Return True when a color has participated in a real transition signal."""
        for evidence in self._movement_evidence.get(color_id, []):
            if (
                evidence.get("moved")
                or evidence.get("in_changed_bbox")
                or evidence.get("near_changed_center")
                or evidence.get("matches_direction")
            ):
                return True
        for evidence in self._local_activity_evidence.get(color_id, []):
            if (
                evidence.get("moved")
                or evidence.get("in_changed_bbox")
                or evidence.get("near_changed_center")
                or evidence.get("matches_direction")
            ):
                return True
        return False

    def _has_wall_geometry(self, centroid: Dict[str, float]) -> bool:
        row_span = float(centroid.get("row_end", centroid["row"])) - float(centroid.get("row_start", centroid["row"]))
        col_span = float(centroid.get("col_end", centroid["col"])) - float(centroid.get("col_start", centroid["col"]))
        return row_span >= self.WALL_MIN_EXTENT_SPAN or col_span >= self.WALL_MIN_EXTENT_SPAN

    def _goal_candidate_score(
        self,
        color_id: int,
        centroid: Dict[str, float],
        stationary_steps: int,
        changed_region: Dict[str, Any],
        changed_center: Dict[str, Any],
        player_pos: Dict[str, float] | None,
        prev_player_pos: Dict[str, float] | None,
        total_pixels: int,
        history_len: int,
        pixels_changed: float,
    ) -> float:
        count_fraction = float(centroid.get("count", 0.0)) / float(total_pixels)
        in_changed_bbox = self._in_changed_bbox(centroid, changed_region)
        near_changed_center = self._near_changed_center(centroid, changed_center)

        score = 0.0
        if count_fraction <= 0.02:
            score += 0.30
        elif count_fraction <= 0.05:
            score += 0.22
        elif count_fraction <= 0.08:
            score += 0.12

        if stationary_steps >= 2:
            score += 0.25
        elif stationary_steps >= 1:
            score += 0.15

        if in_changed_bbox:
            score += 0.20
        if near_changed_center:
            score += 0.15
        if pixels_changed > 0.0 and stationary_steps >= 1:
            score += 0.10

        if player_pos:
            distance = abs(float(centroid["row"]) - float(player_pos.get("row", 0.0))) + abs(
                float(centroid["col"]) - float(player_pos.get("col", 0.0))
            )
            if distance <= 3.0:
                score += 0.12
            elif distance <= 6.0:
                score += 0.08
            elif distance <= 10.0:
                score += 0.04
            if prev_player_pos:
                prev_distance = abs(float(centroid["row"]) - float(prev_player_pos.get("row", 0.0))) + abs(
                    float(centroid["col"]) - float(prev_player_pos.get("col", 0.0))
                )
                delta = prev_distance - distance
                if delta >= 1.0:
                    score += 0.15
                elif delta >= 0.5:
                    score += 0.08

        if history_len >= 2:
            score += 0.05
        if history_len >= 3 and stationary_steps >= 2:
            score += 0.05
        return score

    def update(
        self,
        hypothesis_context: Dict[str, Any],
        observation: Dict[str, Any],
        step: int,
    ) -> Dict[int, ObjectRole]:
        """Return updated object role map from current frame evidence."""
        roles: Dict[int, ObjectRole] = {}
        colors = observation.get("colors") or []
        grid = observation.get("grid") or []
        static_rows = set(hypothesis_context.get("static_rows") or [])
        hud_rows = set(hypothesis_context.get("hud_rows") or [])
        last_effect = hypothesis_context.get("last_transition_effect") or {}
        changed_region = last_effect.get("changed_region") or {}
        changed_center = last_effect.get("changed_center") or self._changed_bbox_center(changed_region) or {}
        reward = float(last_effect.get("meaningful_change_score", 0.0))
        pixels_changed = float(last_effect.get("pixels_changed", 0.0))
        action_taken = last_effect.get("action")
        action_facts = hypothesis_context.get("action_facts") or []
        inferred_direction = _trend_direction_from_fact(action_facts, action_taken)
        direction_vector = _direction_vector(inferred_direction)

        curr_centroids = _compute_centroids(grid) if grid else {}
        total_pixels = sum(int(v.get("count", 0)) for v in curr_centroids.values()) or 1

        for color_info in colors:
            color_id = color_info["value"] if isinstance(color_info, dict) else color_info
            roles[color_id] = ObjectRole(color_id=color_id, evidence_steps=[step])

        # Fallback for sparse observations without a grid payload.
        if not curr_centroids:
            for color_id, role in roles.items():
                if static_rows and not changed_region:
                    role.role = RoleType.WALL
                    role.confidence = 0.7
                elif changed_center and reward > 0.3:
                    role.role = RoleType.PLAYER
                    role.confidence = 0.75
                    role.estimated_position = changed_center
            return roles

        for color_id, centroid in curr_centroids.items():
            prev = self._prev_centroids.get(color_id)
            if prev is not None:
                delta_row = centroid["row"] - prev["row"]
                delta_col = centroid["col"] - prev["col"]
                count_delta = int(centroid["count"] - prev.get("count", 0.0))
                moved = abs(delta_row) > self.EPSILON or abs(delta_col) > self.EPSILON
                if moved:
                    self._stationary_steps[color_id] = 0
                else:
                    self._stationary_steps[color_id] = self._stationary_steps.get(color_id, 0) + 1
                in_changed_bbox = self._in_changed_bbox(centroid, changed_region)
                near_center = self._near_changed_center(centroid, changed_center)
                evidence = {
                    "step": step,
                    "action": action_taken,
                    "delta_row": round(delta_row, 2),
                    "delta_col": round(delta_col, 2),
                    "count_delta": count_delta,
                    "moved": moved,
                    "in_changed_region": near_center,
                    "in_changed_bbox": in_changed_bbox,
                    "direction": inferred_direction,
                    "matches_direction": False,
                }
                if direction_vector is not None:
                    evidence["matches_direction"] = self._directional_match(
                        delta_row,
                        delta_col,
                        inferred_direction,
                    )
                self._movement_evidence.setdefault(color_id, []).append(evidence)
                local_activity = {
                    "step": step,
                    "action": action_taken,
                    "count_delta": count_delta,
                    "in_changed_bbox": in_changed_bbox,
                    "near_changed_center": near_center,
                    "matches_direction": evidence["matches_direction"],
                    "moved": moved,
                }
                self._local_activity_evidence.setdefault(color_id, []).append(local_activity)
            else:
                self._stationary_steps.setdefault(color_id, 0)
            self._centroid_history.setdefault(color_id, []).append(centroid)

        # WALL detection: require multiple independent signals on real grids.
        for color_id, role in roles.items():
            centroid = curr_centroids.get(color_id)
            if centroid is None or color_id == self.BACKGROUND_COLOR:
                continue
            coverage_static = self._color_only_in_rows(grid, color_id, static_rows)
            coverage_hud = self._color_only_in_rows(grid, color_id, hud_rows)
            stationary_steps = self._stationary_steps.get(color_id, 0)
            history = self._centroid_history.get(color_id, [])
            count = int(centroid.get("count", 0.0))
            active_evidence = self._has_active_evidence(color_id)
            structural_signal = count >= self.WALL_MIN_OBSERVED_COUNT and self._has_wall_geometry(centroid)
            coverage_signal = coverage_static or coverage_hud
            persistence_signal = stationary_steps >= self.WALL_MIN_STATIONARY_STEPS
            drift = 0.0
            if len(history) >= 2:
                drift = sum(
                    abs(curr["row"] - prev["row"]) + abs(curr["col"] - prev["col"])
                    for prev, curr in zip(history[:-1], history[1:])
                )

            # On a real grid, wall labels need coverage + persistence + shape evidence.
            if grid:
                if active_evidence:
                    continue
                if coverage_signal and persistence_signal and structural_signal and drift <= 0.5:
                    role.role = RoleType.WALL
                    role.confidence = 0.72 if coverage_static else 0.68
                    continue
                if coverage_signal and structural_signal and stationary_steps >= (self.WALL_MIN_STATIONARY_STEPS + 1) and drift <= 0.35:
                    role.role = RoleType.WALL
                    role.confidence = 0.7 if coverage_static else 0.66
                    continue
                continue

            if coverage_static or (coverage_hud and stationary_steps >= 1):
                role.role = RoleType.WALL
                role.confidence = 0.7 if coverage_static else 0.65
                continue
            if stationary_steps >= self.WALL_MIN_STATIONARY_STEPS and drift <= 0.5:
                role.role = RoleType.WALL
                role.confidence = 0.68

        # PLAYER detection: consistent motion evidence matching inferred operator trend.
        best_player_id: Optional[int] = None
        best_player_score = 0.0
        for color_id, evidence in self._movement_evidence.items():
            if color_id not in roles:
                continue
            if roles[color_id].role == RoleType.WALL or color_id == self.BACKGROUND_COLOR:
                continue
            moved_events = [item for item in evidence if item.get("moved")]
            if not moved_events:
                continue
            match_rate = sum(1 for item in moved_events if item.get("matches_direction")) / len(moved_events)
            motion_rate = len(moved_events) / len(evidence)
            changed_region_rate = sum(1 for item in evidence if item.get("in_changed_region")) / len(evidence)
            reward_bonus = 0.15 if reward > 0.3 else 0.0
            score = (0.45 * match_rate) + (0.30 * motion_rate) + (0.15 * changed_region_rate) + reward_bonus
            if len(moved_events) >= self.PLAYER_MIN_MATCHES and score >= self.PLAYER_MIN_MATCH_RATE:
                if score > best_player_score:
                    best_player_score = score
                    best_player_id = color_id

        # Local changed-region fallback: prefer a small active color when the transition
        # only moves a tiny frontier and whole-color centroids stay too stable to score well.
        for color_id, evidence in self._local_activity_evidence.items():
            if color_id not in roles:
                continue
            if roles[color_id].role == RoleType.WALL or color_id == self.BACKGROUND_COLOR:
                continue
            centroid = curr_centroids.get(color_id)
            if centroid is None:
                continue
            count_fraction = float(centroid.get("count", 0.0)) / float(total_pixels)
            if count_fraction > 0.08:
                continue
            bbox_hits = sum(1 for item in evidence if item.get("in_changed_bbox"))
            center_hits = sum(1 for item in evidence if item.get("near_changed_center"))
            count_changes = sum(1 for item in evidence if item.get("count_delta", 0) != 0)
            directional_hits = sum(1 for item in evidence if item.get("matches_direction"))
            moved_hits = sum(1 for item in evidence if item.get("moved"))
            if bbox_hits == 0 and center_hits == 0:
                continue
            activity_score = (
                0.30 * min(bbox_hits / max(len(evidence), 1), 1.0)
                + 0.25 * min(center_hits / max(len(evidence), 1), 1.0)
                + 0.20 * min(count_changes / max(len(evidence), 1), 1.0)
                + 0.15 * min(moved_hits / max(len(evidence), 1), 1.0)
                + 0.10 * min(directional_hits / max(len(evidence), 1), 1.0)
            )
            if count_fraction <= 0.02:
                activity_score += 0.10
            if bbox_hits >= 2 and (moved_hits >= 2 or count_changes >= 1) and activity_score > best_player_score:
                best_player_score = activity_score
                best_player_id = color_id

        if best_player_id is None and changed_center and reward > 0.3:
            for color_id, centroid in curr_centroids.items():
                if color_id not in roles or color_id == self.BACKGROUND_COLOR:
                    continue
                if roles[color_id].role == RoleType.WALL:
                    continue
                if self._near_changed_center(centroid, changed_center):
                    best_player_id = color_id
                    best_player_score = 0.75
                    break

        if best_player_id is None:
            # Generic movement fallback: if a single color is the most mobile and not wall-like,
            # treat it as the likely controlled object.
            mobility_scores: List[tuple[float, int]] = []
            for color_id, evidence in self._movement_evidence.items():
                if color_id not in roles or roles[color_id].role == RoleType.WALL:
                    continue
                moved_events = sum(1 for item in evidence if item.get("moved"))
                if moved_events >= 2:
                    mobility_scores.append((moved_events / len(evidence), color_id))
            if mobility_scores:
                mobility_scores.sort(reverse=True)
                top_score, top_color = mobility_scores[0]
                if top_score >= 0.6:
                    best_player_id = top_color
                    best_player_score = top_score

        if best_player_id is not None and best_player_id in roles:
            role = roles[best_player_id]
            role.role = RoleType.PLAYER
            role.confidence = min(0.6 + best_player_score * 0.3, 0.95)
            centroid = curr_centroids.get(best_player_id)
            if centroid:
                role.estimated_position = {"row": centroid["row"], "col": centroid["col"]}

        player_role = next((r for r in roles.values() if r.role == RoleType.PLAYER), None)
        player_pos = player_role.estimated_position if player_role else None
        prev_player_pos: Dict[str, float] | None = None
        if best_player_id is not None:
            prev_player_centroid = self._prev_centroids.get(best_player_id)
            if prev_player_centroid:
                prev_player_pos = {
                    "row": prev_player_centroid["row"],
                    "col": prev_player_centroid["col"],
                }

        # GOAL detection: small, persistent, non-background, and shaped by transition evidence.
        best_goal_id: Optional[int] = None
        best_goal_score = 0.0
        for color_id, role in roles.items():
            if role.role != RoleType.UNKNOWN:
                continue
            centroid = curr_centroids.get(color_id)
            if centroid is None or color_id == self.BACKGROUND_COLOR:
                continue
            stationary_steps = self._stationary_steps.get(color_id, 0)
            in_hud = self._color_only_in_rows(grid, color_id, hud_rows)
            in_static = self._color_only_in_rows(grid, color_id, static_rows)
            if in_hud or in_static:
                continue
            score = self._goal_candidate_score(
                color_id=color_id,
                centroid=centroid,
                stationary_steps=stationary_steps,
                changed_region=changed_region,
                changed_center=changed_center,
                player_pos=player_pos,
                prev_player_pos=prev_player_pos,
                total_pixels=total_pixels,
                history_len=len(self._centroid_history.get(color_id, [])),
                pixels_changed=pixels_changed,
            )
            if score >= self.GOAL_MIN_SCORE and score > best_goal_score:
                best_goal_score = score
                best_goal_id = color_id

        if best_goal_id is not None and best_goal_id in roles:
            goal_role = roles[best_goal_id]
            goal_role.role = RoleType.GOAL
            goal_role.confidence = min(0.5 + best_goal_score * 0.4, 0.95)
            centroid = curr_centroids.get(best_goal_id)
            if centroid:
                goal_role.estimated_position = {"row": centroid["row"], "col": centroid["col"]}

        # Enrich evidence trails.
        for color_id, role in roles.items():
            if role.role == RoleType.UNKNOWN:
                continue
            role.evidence_steps = sorted(set(role.evidence_steps + [step]))

        self._prev_centroids = curr_centroids
        return roles

    def seed_bootstrap_roles(self, observation: Dict[str, Any]) -> Dict[int, ObjectRole]:
        """B119: Initial entity discovery from step 0 frame.
        PLAYER: smallest moving color (heuristic: smallest non-zero color).
        GOAL: color furthest from player (heuristic: color closest to exit/bottom-right).
        """
        roles: Dict[int, ObjectRole] = {}
        colors = observation.get("colors") or []
        if not colors:
            return roles

        # Filter out background (0)
        non_bg = [c for c in colors if (c.get("value") if isinstance(c, dict) else c) != 0]
        if not non_bg:
            return roles

        # Sort by pixel count ascending
        sorted_by_size = sorted(non_bg, key=lambda c: c.get("count") if isinstance(c, dict) else 0)
        
        # Player candidate: the smallest object (often the character)
        player_color_item = sorted_by_size[0]
        p_id = player_color_item.get("value") if isinstance(player_color_item, dict) else player_color_item
        roles[p_id] = ObjectRole(
            color_id=p_id,
            role=RoleType.PLAYER,
            confidence=0.45,  # Low confidence bootstrap
            evidence_steps=[0]
        )

        # Goal candidate: if there are other colors, pick one as a candidate
        if len(sorted_by_size) > 1:
            goal_color_item = sorted_by_size[-1]
            g_id = goal_color_item.get("value") if isinstance(goal_color_item, dict) else goal_color_item
            if g_id != p_id:
                roles[g_id] = ObjectRole(
                    color_id=g_id,
                    role=RoleType.GOAL,
                    confidence=0.35,
                    evidence_steps=[0]
                )

        return roles

    def seed_bootstrap_roles(self, observation: Dict[str, Any]) -> Dict[int, ObjectRole]:
        """B119: Initial entity discovery from step 0 frame.
        PLAYER: smallest moving color (heuristic: smallest non-zero color).
        GOAL: color furthest from player (heuristic: color closest to exit/bottom-right).
        """
        roles: Dict[int, ObjectRole] = {}
        colors = observation.get("colors") or []
        if not colors:
            return roles

        # Filter out background (0)
        non_bg = [c for c in colors if (c.get("value") if isinstance(c, dict) else c) != 0]
        if not non_bg:
            return roles

        # Sort by pixel count ascending
        sorted_by_size = sorted(non_bg, key=lambda c: c.get("count") if isinstance(c, dict) else 0)
        
        # Player candidate: the smallest object (often the character)
        player_color_item = sorted_by_size[0]
        p_id = player_color_item.get("value") if isinstance(player_color_item, dict) else player_color_item
        roles[p_id] = ObjectRole(
            color_id=p_id,
            role=RoleType.PLAYER,
            confidence=0.45,  # Low confidence bootstrap
            evidence_steps=[0]
        )

        # Goal candidate: if there are other colors, pick one as a candidate
        if len(sorted_by_size) > 1:
            goal_color_item = sorted_by_size[-1]
            g_id = goal_color_item.get("value") if isinstance(goal_color_item, dict) else goal_color_item
            if g_id != p_id:
                roles[g_id] = ObjectRole(
                    color_id=g_id,
                    role=RoleType.GOAL,
                    confidence=0.35,
                    evidence_steps=[0]
                )

        return roles


# ── Victory Hypothesizer ──────────────────────────────────────────────

class VictoryHypothesizer:
    """Identifies the win condition using recall_plans + recall_lessons + one LLM call.

    Called once when archetype confidence > CALL_THRESHOLD.
    Re-called only when DissonanceDetector fires.
    """

    CALL_THRESHOLD: float = 0.65
    PROMPT_TEMPLATE = VICTORY_HYPOTHESIS_TEMPLATE  # B122: Imported from prompts module

    async def hypothesize(
        self,
        archetype: GameArchetype,
        object_roles: Dict[int, ObjectRole],
        brain_client: Any,
        llm_client: Any,
        session_id: str,
        task_id: str,
        reward_history: List[float],
        dissonance_reason: str = "",
        past_plans: Optional[List[Dict[str, Any]]] = None,
        lessons: Optional[List[Dict[str, Any]]] = None,
    ) -> VictoryCondition:
        """Synthesize the victory condition from retrieved evidence and an LLM call.

        The solve engine is responsible for fetching `past_plans` and `lessons`.
        If they are omitted, we fall back to direct retrieval for compatibility.
        """

        # 1. Recall similar past plans if the caller did not already fetch them.
        if past_plans is None:
            goal_query = f"{archetype.value} game win condition solve puzzle"
            recall = await brain_client.recall_plans(
                goal_query=goal_query,
                session_id=session_id,
                min_valence=0.2,
                limit=3,
            )
            past_plans = recall.get("plans", [])

        # Check if a past plan gives us a high-confidence victory condition directly
        for plan in past_plans:
            if plan.get("valence", 0.0) > 0.75:
                return VictoryCondition(
                    condition_type=VictoryType.UNKNOWN,  # will be refined by LLM
                    description=plan.get("goal", ""),
                    confidence=0.6,
                    source="recall_plans",
                )

        # 2. Recall game-specific lessons if the caller did not already fetch them.
        if lessons is None:
            lessons_result = await brain_client.recall_relevant_lessons(
                query=f"ARC game {archetype.value} win condition",
                limit=3,
            )
            lessons = lessons_result.get("lessons", [])

        # 3. LLM call
        object_roles_text = "\n".join(
            f"  color_id={r.color_id}: {r.role.value} (confidence={r.confidence:.2f})"
            for r in object_roles.values()
            if r.role != RoleType.UNKNOWN
        ) or "  No roles identified yet."

        past_plans_text = "\n".join(
            f"  - {p.get('goal', '')}" for p in past_plans[:3]
        ) or "  No past plans found."

        lessons_text = "\n".join(
            f"  - {l.get('text', '')}" for l in lessons[:3]
        ) or "  No lessons found."

        reward_summary = (
            f"Last 5 rewards: {reward_history[-5:]}"
            if reward_history else "No reward history."
        )
        if dissonance_reason:
            reward_summary += f" DISSONANCE: {dissonance_reason}"

        prompt = self.PROMPT_TEMPLATE.format(
            archetype=archetype.value,
            object_roles=object_roles_text,
            past_plans=past_plans_text,
            lessons=lessons_text,
            reward_summary=reward_summary,
        )

        try:
            response = await llm_client.achat([{"role": "user", "content": prompt}])
            text = response.strip()
            # Strip markdown fences if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text.strip())
            return VictoryCondition(
                condition_type=VictoryType(data.get("condition_type", "unknown")),
                description=data.get("description", ""),
                target_color_id=data.get("target_color_id"),
                confidence=float(data.get("confidence", 0.5)),
                source="llm",
            )
        except Exception as exc:
            logger.warning("VictoryHypothesizer LLM call failed: %s", exc)
            return VictoryCondition(
                condition_type=VictoryType.UNKNOWN,
                description="Victory condition unknown",
                confidence=0.1,
                source="error",
            )


# ── Dissonance Detector ───────────────────────────────────────────────

class DissonanceDetector:
    """Monitors plan chunk progress. Fires report_outcome(negative) on stall.

    Dissonance conditions:
      - Zero meaningful-change steps >= STALL_THRESHOLD while executing a chunk
      - reward_trend is flat/negative for >= REWARD_STALL_THRESHOLD steps
      - Active chunk exceeded MAX_CHUNK_STEPS without progress_score increase
    """

    STALL_THRESHOLD: int = 6
    REWARD_STALL_THRESHOLD: int = 8
    MAX_CHUNK_STEPS: int = 15

    def __init__(self) -> None:
        self._zero_progress_streak: int = 0
        self._chunk_steps: int = 0

    def update(
        self,
        hypothesis_context: Dict[str, Any],
        active_chunk: Optional[PlanChunk],
        step: int,
    ) -> tuple[bool, str]:
        """Return (should_replan, reason). Pure algorithmic — no async."""
        if active_chunk is None:
            self._zero_progress_streak = 0
            self._chunk_steps = 0
            return False, ""

        self._chunk_steps += 1
        last_effect = hypothesis_context.get("last_transition_effect") or {}
        score = float(last_effect.get("meaningful_change_score", 0.0))

        if score < 0.15:
            self._zero_progress_streak += 1
        else:
            self._zero_progress_streak = 0
            self._chunk_steps = 0  # B109: meaningful change resets chunk step counter

        if self._zero_progress_streak >= self.STALL_THRESHOLD:
            return True, f"no meaningful change for {self._zero_progress_streak} steps"

        if self._chunk_steps >= self.MAX_CHUNK_STEPS and active_chunk.progress_score < 0.2:
            return True, f"chunk exceeded {self.MAX_CHUNK_STEPS} steps with low progress"

        # B109: If chunk is exhausted but didn't reach success, trigger replan
        if not active_chunk.estimated_actions and active_chunk.progress_score < 0.5:
            return True, "chunk actions exhausted without significant progress"

        return False, ""

    def reset_chunk(self) -> None:
        """Call when a new chunk starts."""
        self._zero_progress_streak = 0
        self._chunk_steps = 0


# ── Plan Chunker ──────────────────────────────────────────────────────

class PlanChunker:
    """Decomposes the victory condition into executable macro-action chunks.

    Primary path: BFS on in-memory StateGraph (free, exact, O(V+E)).
    Fallback path: directional chunk toward estimated goal position.
    SolveEngine owns plan registration; this class only returns the next chunk.
    """

    DIRECTIONAL_PLAYER_CONFIDENCE: float = 0.65
    DIRECTIONAL_GOAL_CONFIDENCE: float = 0.55
    MIN_TESTED_ACTIONS_FOR_DIRECTIONAL: int = 3
    GRADUATION_THRESHOLD: float = 0.72
    MIN_EXPLORATION_COMPLETENESS: float = 0.60

    def _graduation_assessment(
        self,
        player_role: Optional[ObjectRole],
        goal_role: Optional[ObjectRole],
        hypothesis_context: Optional[Dict[str, Any]],
        available_actions: List[str],
    ) -> Dict[str, Any]:
        context = hypothesis_context or {}
        action_coverage = context.get("action_coverage") or {}
        available_total = max(len(available_actions), 1)
        tested_count = int(action_coverage.get("tested_count", 0))
        untested_count = int(action_coverage.get("untested_count", max(available_total - tested_count, 0)))
        coverage_ratio = min(tested_count / available_total, 1.0)

        player_conf = float(player_role.confidence if player_role else 0.0)
        goal_conf = float(goal_role.confidence if goal_role else 0.0)
        player_known = 1.0 if player_role and player_role.estimated_position else 0.0
        goal_known = 1.0 if goal_role and goal_role.estimated_position else 0.0
        positions_known = 1.0 if player_known and goal_known else 0.0

        action_facts = context.get("action_facts") or []
        path_hypotheses = context.get("path_hypotheses") or []

        deterministic_facts = sum(1 for fact in action_facts if fact.get("fact_type") == "deterministic_effect")
        valuable_facts = sum(
            1
            for fact in action_facts
            if fact.get("fact_type") == "deterministic_effect" and fact.get("value_status") == "valuable"
        )
        path_signal = sum(
            1
            for hyp in path_hypotheses
            if hyp.get("value_status") in {"valuable", "tentative"}
        )
        evidence_score = min(
            0.20 * min(deterministic_facts, 3)
            + 0.12 * min(valuable_facts, 3)
            + 0.10 * min(path_signal, 3)
            + (0.10 if action_coverage.get("initial_exploration_complete") else 0.0),
            1.0,
        )

        contradiction_penalty = 0.0
        if context.get("loop_detected"):
            contradiction_penalty += 0.25
        if action_coverage.get("top_two_low_value"):
            contradiction_penalty += 0.10
        if untested_count > 0 and not action_coverage.get("initial_exploration_complete"):
            contradiction_penalty += 0.05

        player_score = min(player_conf / max(self.DIRECTIONAL_PLAYER_CONFIDENCE, 1e-6), 1.0)
        goal_score = min(goal_conf / max(self.DIRECTIONAL_GOAL_CONFIDENCE, 1e-6), 1.0)
        coverage_score = min(coverage_ratio / max(self.MIN_EXPLORATION_COMPLETENESS, 1e-6), 1.0)

        score = (
            0.30 * player_score
            + 0.25 * goal_score
            + 0.15 * positions_known
            + 0.15 * coverage_score
            + 0.15 * evidence_score
            - contradiction_penalty
        )
        score = max(0.0, min(score, 1.0))

        ready = (
            player_role is not None
            and goal_role is not None
            and player_conf >= self.DIRECTIONAL_PLAYER_CONFIDENCE
            and goal_conf >= self.DIRECTIONAL_GOAL_CONFIDENCE
            and positions_known > 0.0
            and (action_coverage.get("initial_exploration_complete") or coverage_ratio >= self.MIN_EXPLORATION_COMPLETENESS)
            and not action_coverage.get("top_two_low_value")
            and not context.get("loop_detected")
            and score >= self.GRADUATION_THRESHOLD
        )

        components = {
            "player_score": round(player_score, 3),
            "goal_score": round(goal_score, 3),
            "positions_known": round(positions_known, 3),
            "coverage_ratio": round(coverage_ratio, 3),
            "coverage_score": round(coverage_score, 3),
            "evidence_score": round(evidence_score, 3),
            "contradiction_penalty": round(contradiction_penalty, 3),
            "tested_count": float(tested_count),
            "untested_count": float(untested_count),
        }
        if ready:
            reason = (
                f"graduate directional: score={score:.2f} >= {self.GRADUATION_THRESHOLD:.2f}; "
                f"player={player_conf:.2f}, goal={goal_conf:.2f}, coverage={coverage_ratio:.2f}, "
                f"evidence={evidence_score:.2f}, penalty={contradiction_penalty:.2f}"
            )
        else:
            blockers: List[str] = []
            if player_role is None:
                blockers.append("missing player role")
            elif player_conf < self.DIRECTIONAL_PLAYER_CONFIDENCE:
                blockers.append(f"player confidence {player_conf:.2f} < {self.DIRECTIONAL_PLAYER_CONFIDENCE:.2f}")
            if goal_role is None:
                blockers.append("missing goal role")
            elif goal_conf < self.DIRECTIONAL_GOAL_CONFIDENCE:
                blockers.append(f"goal confidence {goal_conf:.2f} < {self.DIRECTIONAL_GOAL_CONFIDENCE:.2f}")
            if not positions_known:
                blockers.append("player/goal positions not both known")
            if coverage_ratio < self.MIN_EXPLORATION_COMPLETENESS and not action_coverage.get("initial_exploration_complete"):
                blockers.append(f"coverage {coverage_ratio:.2f} < {self.MIN_EXPLORATION_COMPLETENESS:.2f}")
            if action_coverage.get("top_two_low_value"):
                blockers.append("top actions are low_value")
            if context.get("loop_detected"):
                blockers.append("loop detected")
            if not blockers:
                blockers.append("score below threshold")
            reason = (
                f"stay explore: score={score:.2f} < {self.GRADUATION_THRESHOLD:.2f}; "
                f"player={player_conf:.2f}, goal={goal_conf:.2f}, coverage={coverage_ratio:.2f}, "
                f"evidence={evidence_score:.2f}, penalty={contradiction_penalty:.2f}; "
                + "; ".join(blockers)
            )

        return {
            "ready": ready,
            "score": score,
            "reason": reason,
            "components": components,
        }

    def generate_chunk(
        self,
        victory_condition: VictoryCondition,
        object_roles: Dict[int, ObjectRole],
        state_graph: Any,       # StateGraph from hypothesis.py
        current_hash: str,
        available_actions: List[str],
        step: int,
        hypothesis_context: Optional[Dict[str, Any]] = None,
    ) -> PlanChunk:
        """Generate the next plan chunk. Pure logic only; no SideQuests calls."""

        # 1. Try BFS if we have a known goal state
        player_role = next(
            (r for r in object_roles.values() if r.role == RoleType.PLAYER), None
        )
        goal_role = next(
            (r for r in object_roles.values()
             if r.role in (RoleType.GOAL, RoleType.EXIT)), None
        )

        if goal_role and hasattr(state_graph, "find_path"):
            # Attempt BFS toward any state where goal object has changed
            # (approximate: we search for transitions that produced reward)
            high_reward_states = [
                t.to_hash for transitions in state_graph.edges.values()
                for t in transitions if t.reward_signal > 0.5
            ]
            for target_hash in high_reward_states:
                path = state_graph.find_path(current_hash, target_hash)
                if path:
                    actions = [t.action for t in path]
                    graduation_reason = "bfs path found to known reward state"
                    return PlanChunk(
                        description=f"Navigate via known path to reward state ({len(actions)} steps)",
                        estimated_actions=actions,
                        success_condition="reach high-reward state",
                        source="bfs",
                        graduation_score=1.0,
                        graduation_reason=graduation_reason,
                        graduation_components={"bfs_path_found": 1.0, "path_length": float(len(actions))},
                    )

        # 2. Directional fallback: infer movement direction toward goal
        graduation = self._graduation_assessment(
            player_role,
            goal_role,
            hypothesis_context,
            available_actions,
        )
        if graduation["ready"]:
            p_pos = player_role.estimated_position or {}
            g_pos = goal_role.estimated_position or {}
            directions = []
            if p_pos and g_pos:
                dr = g_pos.get("row", 0) - p_pos.get("row", 0)
                dc = g_pos.get("col", 0) - p_pos.get("col", 0)
                if dr > 0:
                    directions.extend(["ACTION2"] * min(abs(int(dr)), 5))
                elif dr < 0:
                    directions.extend(["ACTION1"] * min(abs(int(dr)), 5))
                if dc > 0:
                    directions.extend(["ACTION4"] * min(abs(int(dc)), 5))
                elif dc < 0:
                    directions.extend(["ACTION3"] * min(abs(int(dc)), 5))

            if directions:
                dist = abs(dr) + abs(dc)
                return PlanChunk(
                    description=f"Move {victory_condition.condition_type.value} toward goal (dist={dist})",
                    estimated_actions=directions[:8],
                    success_condition="reduce distance to goal object",
                    source="directional",
                    graduation_score=float(graduation["score"]),
                    graduation_reason=str(graduation["reason"]),
                    graduation_components=dict(graduation["components"]),
                )

        # 3. Exploration fallback: try unexplored actions
        if hasattr(state_graph, "get_unexplored_actions"):
            unexplored = state_graph.get_unexplored_actions(current_hash, available_actions)
        else:
            unexplored = []
        action = unexplored[0] if unexplored else (available_actions[0] if available_actions else "ACTION1")
        return PlanChunk(
            description="Explore: try unexplored action to gather more information",
            estimated_actions=[action],
            success_condition="observe new state",
            source="explore",
            graduation_score=float(graduation["score"]),
            graduation_reason=str(graduation["reason"]),
            graduation_components=dict(graduation["components"]),
        )


class DecisionGuard:
    """B115: Pre-execution guard that blocks or revises bad ARC moves."""

    def critique_action(
        self,
        action_id: str,
        available_actions: List[str],
        hypothesis_context: Dict[str, Any],
        active_chunk: Optional[PlanChunk],
        step_history: List[dict],
    ) -> Dict[str, Any]:
        """Inspect action against loop history, chunks, and facts.
        Returns: {
            "status": "approved" | "blocked" | "warned",
            "reason": str,
            "suggested_action": Optional[str]
        }
        """
        if action_id not in available_actions:
            return {
                "status": "blocked",
                "reason": f"Action {action_id} not available in current state.",
                "suggested_action": available_actions[0] if available_actions else None,
            }

        # 1. Loop Check: Avoid repeating moves that produced NO_CHANGE repeatedly
        if step_history:
            recent_no_reward = [
                s for s in step_history[-3:]
                if s.get("action_id") == action_id and s.get("reward") == 0.0
            ]
            if len(recent_no_reward) >= 2:
                return {
                    "status": "warned",
                    "reason": f"Action {action_id} failed to produce reward in {len(recent_no_reward)} recent attempts.",
                    "suggested_action": None,
                }

        # 2. Chunk Alignment Check:
        if (
            active_chunk 
            and active_chunk.source in ("bfs", "directional")
            and active_chunk.estimated_actions
        ):
            chunk_action = active_chunk.estimated_actions[0]
            if action_id != chunk_action and chunk_action in available_actions:
                return {
                    "status": "warned",
                    "reason": f"Action {action_id} deviates from guidance-grade {active_chunk.source} chunk: {active_chunk.description}.",
                    "suggested_action": chunk_action,
                }

        # 3. Locked Evidence Check:
        facts = hypothesis_context.get("action_facts", [])
        fact = next((f for f in facts if f.get("action") == action_id), None)
        if fact and fact.get("value_status") == "harmful":
            return {
                "status": "blocked",
                "reason": f"Action {action_id} is marked as harmful: {fact.get('description')}",
                "suggested_action": None,
            }

        return {"status": "approved", "reason": "No guard violations detected.", "suggested_action": None}


# ── Solve Engine ──────────────────────────────────────────────────────

class SolveEngine:
    """Top-level controller. Called by orchestrator between hypothesize() and plan().

    Owns: ArchetypeClassifier, ObjectRoleMapper, VictoryHypothesizer,
          DissonanceDetector, PlanChunker, DecisionGuard.
    Consumes: hypothesis_context (from HypothesisManager.observe()),
              brain_client, llm_client.
    Produces: SolveContext.
    """

    def __init__(self, brain_client: Any, llm_client: Any, session_id: str) -> None:
        self.brain = brain_client
        self.llm = llm_client
        self.session_id = session_id

        self.archetype_classifier = ArchetypeClassifier()
        self.role_mapper = ObjectRoleMapper()
        self.victory_hypothesizer = VictoryHypothesizer()
        self.dissonance_detector = DissonanceDetector()
        self.plan_chunker = PlanChunker()
        self.decision_guard = DecisionGuard()

        self._archetype: GameArchetype = GameArchetype.UNKNOWN
        self._archetype_confidence: float = 0.0
        self._archetype_locked: bool = False
        self._object_roles: Dict[int, ObjectRole] = {}
        self._victory_condition: Optional[VictoryCondition] = None
        self._active_chunk: Optional[PlanChunk] = None
        self._chunk_history: List[PlanChunk] = []
        self._chunk_ledger: List[ChunkLedgerEntry] = []
        self._solve_plan_id: Optional[str] = None
        self._reward_history: List[float] = []
        self._role_resolution_notes: List[str] = []

    def _add_chunk_to_ledger_as_active(self, chunk: PlanChunk) -> None:
        """B124: Mark a chunk as active in the ledger."""
        entry = ChunkLedgerEntry(
            description=chunk.description,
            status="active",
            steps_used=0,
            outcome_summary=""
        )
        self._chunk_ledger.append(entry)
        # Note: don't prune here; prune only when transitioning to final state (completed/failed)

    def _mark_chunk_completed(self, chunk: PlanChunk) -> None:
        """B124: Mark chunk as completed with progress summary."""
        if self._chunk_ledger:
            # Find the most recent entry for this chunk
            for entry in reversed(self._chunk_ledger):
                if entry.description == chunk.description and entry.status == "active":
                    entry.status = "completed"
                    entry.steps_used = chunk.steps_executed
                    entry.outcome_summary = f"progress={chunk.progress_score:.2f}"
                    break
        self._prune_chunk_ledger()

    def _mark_chunk_failed(self, chunk: PlanChunk, reason: str) -> None:
        """B124: Mark chunk as failed with reason."""
        if self._chunk_ledger:
            # Find the most recent entry for this chunk
            for entry in reversed(self._chunk_ledger):
                if entry.description == chunk.description and entry.status == "active":
                    entry.status = "failed"
                    entry.steps_used = chunk.steps_executed
                    entry.outcome_summary = reason
                    break
        self._prune_chunk_ledger()

    def _prune_chunk_ledger(self) -> None:
        """B124: Keep ledger to 8 entries, removing oldest completed entries first."""
        if len(self._chunk_ledger) <= 8:
            return
        # Keep all non-completed entries and the newest completed entries
        completed = [e for e in self._chunk_ledger if e.status == "completed"]
        non_completed = [e for e in self._chunk_ledger if e.status != "completed"]

        # Keep the newest completed entries up to 8 total
        to_keep_completed = max(0, 8 - len(non_completed))
        if to_keep_completed < len(completed):
            completed = completed[-to_keep_completed:]

        self._chunk_ledger = non_completed + completed

    async def solve(
        self,
        observation: Dict[str, Any],
        hypothesis_context: Dict[str, Any],
        step: int,
        state_graph: Any,           # StateGraph instance from HypothesisManager
        current_state_hash: str,
    ) -> SolveContext:
        """Run one solve step. Returns SolveContext for orchestrator."""

        # Track reward history
        reward = float((hypothesis_context.get("last_transition_effect") or {}).get(
            "reward_signal", 0.0
        ))
        self._reward_history.append(reward)

        # 1. Archetype classification (algorithmic first)
        if not self._archetype_locked:
            archetype, confidence = self.archetype_classifier.update(hypothesis_context)

            # Call analogical_search for analogy votes (once per 10 steps after first lock candidate)
            if confidence >= 0.35 and step % 10 == 5:
                task_id = observation.get("task_id", "")
                analogy_query = f"ARC game {archetype.value} grid puzzle solve"
                try:
                    analogy_results = await self.brain.analogical_search(
                        query=analogy_query,
                        current_quest_id=task_id,
                        limit=5,
                        min_similarity=0.30,
                    )
                    archetype, confidence = self.archetype_classifier.apply_analogy_votes(
                        archetype, confidence, analogy_results.get("results", [])
                    )
                except Exception as exc:
                    logger.warning("analogical_search failed: %s", exc)

            self._archetype = archetype
            self._archetype_confidence = confidence
            if confidence >= ArchetypeClassifier.LOCK_THRESHOLD:
                self._archetype_locked = True
                logger.info("Archetype locked: %s (confidence=%.2f)", archetype.value, confidence)

        # 2. Object role mapping (runs every step, lightweight)
        new_roles = self.role_mapper.update(hypothesis_context, observation, step)
        self._role_resolution_notes.extend(self._merge_persistent_roles(new_roles, step))
        if len(self._role_resolution_notes) > 6:
            self._role_resolution_notes = self._role_resolution_notes[-6:]

        # 3. Victory condition hypothesis (LLM call, sticky)
        should_replan, dissonance_reason = self.dissonance_detector.update(
            hypothesis_context, self._active_chunk, step
        )

        need_victory_hypothesis = (
            self._victory_condition is None
            and self._archetype_confidence >= VictoryHypothesizer.CALL_THRESHOLD
        ) or (
            should_replan
            and (self._victory_condition is None or self._victory_condition.confidence < 0.5)
        )

        if need_victory_hypothesis:
            goal_query = f"{self._archetype.value} game win condition solve puzzle"
            try:
                recall = await self.brain.recall_plans(
                    goal_query=goal_query,
                    session_id=self.session_id,
                    min_valence=0.2,
                    limit=3,
                )
                past_plans = recall.get("plans", [])
            except Exception as exc:
                logger.warning("recall_plans failed: %s", exc)
                past_plans = []

            try:
                lessons_result = await self.brain.recall_relevant_lessons(
                    query=f"ARC game {self._archetype.value} win condition",
                    limit=3,
                )
                lessons = lessons_result.get("lessons", [])
            except Exception as exc:
                logger.warning("recall_relevant_lessons failed: %s", exc)
                lessons = []

            self._victory_condition = await self.victory_hypothesizer.hypothesize(
                archetype=self._archetype,
                object_roles=self._object_roles,
                brain_client=self.brain,
                llm_client=self.llm,
                session_id=self.session_id,
                task_id=observation.get("task_id", ""),
                reward_history=self._reward_history,
                dissonance_reason=dissonance_reason if should_replan else "",
                past_plans=past_plans,
                lessons=lessons,
            )

        # 4. Register one top-level solve plan once the victory hypothesis exists.
        if self._victory_condition is not None and self._solve_plan_id is None:
            await self._register_solve_plan(observation)

        # 5. Dissonance handling: report negative outcome + reset chunk
        if should_replan and self._active_chunk and self._active_chunk.plan_id:
            try:
                await self.brain.report_outcome(
                    plan_id=self._active_chunk.plan_id,
                    outcome=f"Chunk stalled: {dissonance_reason}",
                    valence=-0.6,
                    session_id=self.session_id,
                    valence_source="dissonance_detector",
                )
            except Exception as exc:
                logger.warning("report_outcome failed: %s", exc)
            # B124: Mark chunk as failed due to dissonance
            self._mark_chunk_failed(self._active_chunk, f"dissonance: {dissonance_reason}")
            self._active_chunk = None
            self.dissonance_detector.reset_chunk()

        # 6. Plan chunking: generate or continue active chunk
        available_actions = observation.get("available_actions") or [
            f"ACTION{i}" for i in range(1, 8)
        ]
        if self._active_chunk and self._active_chunk.estimated_actions:
            # B112: Align stale detection with orchestrator gate
            # BFS is strict: if the next action is blocked, the path is invalid.
            # Directional/Explore are looser: skip blocked actions if possible.
            first_action = self._active_chunk.estimated_actions[0]
            is_stale = False
            if self._active_chunk.source == "bfs":
                if first_action not in available_actions:
                    is_stale = True
            else:
                if not any(a in available_actions for a in self._active_chunk.estimated_actions):
                    is_stale = True

            if is_stale:
                logger.info(
                    "Discarding stale %s chunk: next action %s not in %s",
                    self._active_chunk.source,
                    first_action,
                    available_actions,
                )
                # B124: Mark chunk as failed due to staleness
                self._mark_chunk_failed(self._active_chunk, "stale: next action unavailable")
                self._active_chunk = None
                self.dissonance_detector.reset_chunk()

        # B113: Ensure directional chunks stay actionable by replenishing them
        # if they run low on steps. This avoids "empty shell" summaries.
        if self._active_chunk:
            is_exhausted = not self._active_chunk.estimated_actions
            is_running_low = (
                self._active_chunk.source == "directional"
                and len(self._active_chunk.estimated_actions) < 2
            )
            if is_exhausted or is_running_low:
                logger.info(
                    "Clearing %s chunk (%s) to allow replenishment",
                    self._active_chunk.source,
                    "exhausted" if is_exhausted else "running low",
                )
                # B124: Mark chunk as completed or failed based on progress
                reason = "exhausted" if is_exhausted else "running low"
                if self._active_chunk.progress_score > 0.3:
                    self._mark_chunk_completed(self._active_chunk)
                else:
                    self._mark_chunk_failed(self._active_chunk, reason)
                self._active_chunk = None
                # Note: we don't reset_chunk() here because replenishment isn't dissonance.

        if self._active_chunk is None and self._victory_condition is not None:
            self._active_chunk = self.plan_chunker.generate_chunk(
                victory_condition=self._victory_condition,
                object_roles=self._object_roles,
                state_graph=state_graph,
                current_hash=current_state_hash,
                available_actions=available_actions,
                step=step,
                hypothesis_context=hypothesis_context,
            )
            if self._active_chunk:
                self._chunk_history.append(self._active_chunk)
                # B124: Add chunk to ledger as active
                self._add_chunk_to_ledger_as_active(self._active_chunk)
                # B109: Register chunk as a Plan in SideQuests
                await self._register_chunk_plan(self._active_chunk)
            self.dissonance_detector.reset_chunk()

        # 7. Update chunk progress score and consume action
        if self._active_chunk:
            if reward > 0.3:
                self._active_chunk.progress_score = min(
                    self._active_chunk.progress_score + reward * 0.2, 1.0
                )
            self._active_chunk.steps_executed += 1
            # B109: Action consumption happens in the orchestrator via _enforce_action_policy,
            # but we track execution count here.

        # Build strategy summary for prompt
        strategy = self._build_strategy_summary()

        return SolveContext(
            archetype=self._archetype,
            archetype_confidence=self._archetype_confidence,
            object_roles=dict(self._object_roles),
            victory_condition=self._victory_condition,
            active_chunk=self._active_chunk,
            dissonance_detected=should_replan,
            dissonance_reason=dissonance_reason,
            strategy_summary=strategy,
            chunk_ledger=list(self._chunk_ledger),
        )

    async def _register_chunk_plan(self, chunk: PlanChunk) -> None:
        """B109: Register an active chunk as a plan in SideQuests."""
        try:
            plan_payload = await self.brain.register_plan(
                goal=chunk.description,
                steps=chunk.estimated_actions or ["Execute strategy toward goal"],
                session_id=self.session_id,
            )
            chunk.plan_id = plan_payload.get("plan_id")
            logger.info("Chunk plan registered: %s (%s)", chunk.plan_id, chunk.description)
        except Exception as exc:
            logger.warning("register_chunk_plan failed: %s", exc)

    def peek_action_consequences(self, action_id: str, hypothesis_context: dict) -> dict:
        """B114: Local sandbox check. How does this action align with known facts?"""
        facts = hypothesis_context.get("action_facts", [])
        fact = next((f for f in facts if f.get("action") == action_id), None)
        
        chunk = self._active_chunk
        chunk_match = False
        if chunk and chunk.estimated_actions and chunk.estimated_actions[0] == action_id:
            chunk_match = True
            
        return {
            "action_id": action_id,
            "has_fact": fact is not None,
            "fact_summary": fact.get("description", "no prior evidence") if fact else "none",
            "matches_active_chunk": chunk_match,
            "chunk_description": chunk.description if chunk else "none",
        }

    def critique_action(
        self,
        action_id: str,
        available_actions: List[str],
        hypothesis_context: dict,
        step_history: List[dict],
    ) -> dict:
        """B115: Expose decision guard to orchestrator."""
        return self.decision_guard.critique_action(
            action_id=action_id,
            available_actions=available_actions,
            hypothesis_context=hypothesis_context,
            active_chunk=self._active_chunk,
            step_history=step_history,
        )

    def _build_strategy_summary(self) -> str:
        parts = [f"ARCHETYPE: {self._archetype.value} (conf={self._archetype_confidence:.2f})"]
        if self._victory_condition:
            vc = self._victory_condition
            parts.append(f"GOAL: {vc.condition_type.value} — {vc.description} (conf={vc.confidence:.2f})")
        primary_player = next((color_id for color_id, role in self._object_roles.items() if role.role == RoleType.PLAYER), None)
        primary_goal = next((color_id for color_id, role in self._object_roles.items() if role.role in (RoleType.GOAL, RoleType.EXIT)), None)
        parts.append(
            "PRIMARY ROLES: "
            f"player={primary_player if primary_player is not None else 'none'}, "
            f"goal={primary_goal if primary_goal is not None else 'none'}"
        )
        if self._solve_plan_id:
            parts.append(f"PLAN: {self._solve_plan_id}")
        if self._active_chunk:
            ch = self._active_chunk
            parts.append(
                f"CHUNK: {ch.description} [{ch.source}] progress={ch.progress_score:.2f}"
            )
            if ch.graduation_reason:
                parts.append(
                    f"GRADUATION: {ch.graduation_reason} (score={ch.graduation_score:.2f})"
                )
        if self._role_resolution_notes:
            parts.append("ROLE RESOLUTION: " + " | ".join(self._role_resolution_notes[-3:]))
        if self._chunk_history:
            parts.append(f"CHUNKS: {len(self._chunk_history)}")
        return " | ".join(parts)

    def reset_for_retry(self) -> None:
        """Reset ephemeral state. Preserve archetype and victory condition."""
        self._active_chunk = None
        self._chunk_history = []
        self._solve_plan_id = None
        self.dissonance_detector.reset_chunk()
        self.dissonance_detector._zero_progress_streak = 0
        self._role_resolution_notes = []

    def _merge_persistent_roles(self, new_roles: Dict[int, ObjectRole], step: int) -> List[str]:
        """Merge step-level roles into the persistent role map with conflict handling."""
        notes: List[str] = []

        for color_id, new_role in new_roles.items():
            existing = self._object_roles.get(color_id)
            if existing is None:
                self._object_roles[color_id] = new_role
                continue

            if existing.role == new_role.role:
                if new_role.confidence >= existing.confidence:
                    new_role.evidence_steps = sorted(set((existing.evidence_steps or []) + (new_role.evidence_steps or []) + [step]))
                    if existing.estimated_position and not new_role.estimated_position:
                        new_role.estimated_position = existing.estimated_position
                    self._object_roles[color_id] = new_role
                else:
                    existing.evidence_steps = sorted(set((existing.evidence_steps or []) + (new_role.evidence_steps or []) + [step]))
                    if not existing.estimated_position and new_role.estimated_position:
                        existing.estimated_position = new_role.estimated_position
                continue

            if existing.role == RoleType.PLAYER and new_role.role == RoleType.GOAL:
                existing.evidence_steps = sorted(set((existing.evidence_steps or []) + (new_role.evidence_steps or []) + [step]))
                notes.append(
                    f"step {step}: kept player at color_{color_id}; rejected goal flip (conf={new_role.confidence:.2f})"
                )
                continue

            if existing.role == RoleType.GOAL and new_role.role == RoleType.PLAYER:
                new_role.evidence_steps = sorted(set((existing.evidence_steps or []) + (new_role.evidence_steps or []) + [step]))
                self._object_roles[color_id] = new_role
                notes.append(
                    f"step {step}: promoted player at color_{color_id}; demoted conflicting goal"
                )
                continue

            if new_role.confidence > existing.confidence:
                self._object_roles[color_id] = new_role
                notes.append(
                    f"step {step}: replaced {existing.role.value} with {new_role.role.value} at color_{color_id}"
                )
            else:
                existing.evidence_steps = sorted(set((existing.evidence_steps or []) + (new_role.evidence_steps or []) + [step]))
                notes.append(
                    f"step {step}: preserved {existing.role.value} at color_{color_id}; ignored {new_role.role.value}"
                )

        notes.extend(self._demote_extra_primaries(RoleType.PLAYER, step))
        notes.extend(self._demote_extra_primaries(RoleType.GOAL, step))
        return notes

    def _demote_extra_primaries(self, role_type: RoleType, step: int) -> List[str]:
        notes: List[str] = []
        candidates = [
            (color_id, role)
            for color_id, role in self._object_roles.items()
            if role.role == role_type
        ]
        if len(candidates) <= 1:
            return notes

        primary_color, primary_role = max(
            candidates,
            key=lambda item: (
                float(item[1].confidence),
                len(item[1].evidence_steps or []),
                -int(item[0]),
            ),
        )
        for color_id, role in candidates:
            if color_id == primary_color:
                continue
            role.role = RoleType.DECORATION
            role.evidence_steps = sorted(set((role.evidence_steps or []) + [step]))
            notes.append(
                f"step {step}: demoted stale {role_type.value} at color_{color_id}; primary remains color_{primary_color}"
            )
        if primary_role.role != role_type:
            primary_role.role = role_type
        return notes

    async def _register_solve_plan(self, observation: Dict[str, Any]) -> None:
        goal = f"Solve ARC task {observation.get('dataset_id', '')}:{observation.get('task_id', '')}"
        steps = [
            "Infer archetype from board dynamics",
            "Map object roles from transition evidence",
            "Hypothesize victory condition",
            "Execute and revise chunked solve path",
        ]
        try:
            plan_payload = await self.brain.register_plan(
                goal=goal,
                steps=steps,
                session_id=self.session_id,
            )
            self._solve_plan_id = plan_payload.get("plan_id")
            logger.info("Solve plan registered: %s", self._solve_plan_id)
        except Exception as exc:
            logger.warning("register_plan failed for solve plan: %s", exc)
