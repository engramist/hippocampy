"""
Causal Reasoning Benchmark Tasks: AMA-Bench and MemoryArena.

Tasks requiring multi-step causal chains and interdependent constraints.
SideQuests advantage: maintains constraint consistency across steps via memory retrieval.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


__all__ = [
    "CausalTask",
    "AmaBenchTask",
    "MemoryArenaTask",
    "generate_ama_bench_tasks",
    "generate_memory_arena_tasks",
]


@dataclass
class CausalTask:
    """Base class for causal reasoning tasks."""
    task_id: str
    category: str
    description: str
    initial_state: dict
    constraints: List[str]
    causal_steps: List[dict]  # List of {step_num, condition, action, expected_state_change}
    expected_final_state: dict
    expected_solution: str

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "category": self.category,
            "description": self.description,
            "initial_state": self.initial_state,
            "constraints": self.constraints,
            "causal_steps": self.causal_steps,
            "expected_final_state": self.expected_final_state,
            "expected_solution": self.expected_solution,
        }


@dataclass
class AmaBenchTask(CausalTask):
    """AMA-Bench: Arithmetic reasoning with shared constraints across steps."""
    arithmetic_operations: List[dict] = None  # List of operations with constraints

    def __post_init__(self):
        if self.arithmetic_operations is None:
            self.arithmetic_operations = []


@dataclass
class MemoryArenaTask(CausalTask):
    """MemoryArena: Spatial/abstract state with interdependent updates."""
    state_variables: dict = None  # Named state variables and their interdependencies
    action_sequence: List[str] = None  # Sequence of actions to perform

    def __post_init__(self):
        if self.state_variables is None:
            self.state_variables = {}
        if self.action_sequence is None:
            self.action_sequence = []


def generate_ama_bench_tasks(num_tasks: int = 10, seed: int = 42) -> List[AmaBenchTask]:
    """
    Generate AMA-Bench tasks: multi-step arithmetic with shared constraints.

    Example: "If X + Y = 20 and X > Y, find X when Y = 7"
    Constraint: "All values must be positive integers"
    Causal chain: Y=7 → X must be positive and > 7 → X + Y = 20 → X = 13
    """
    random.seed(seed)
    tasks = []

    for i in range(num_tasks):
        # Difficulty varies from simple (1 constraint) to complex (3+ constraints)
        difficulty = (i % 3) + 1
        num_constraints = difficulty

        # Generate initial values and constraints
        a = random.randint(1, 20)
        b = random.randint(1, 20)
        target_sum = a + b

        constraints = [
            "All values must be positive integers",
            f"First value must be less than {target_sum}",
        ]
        if difficulty >= 2:
            constraints.append(f"First value must be greater than {b - 5}")
        if difficulty >= 3:
            constraints.append(f"Sum of values must equal {target_sum}")

        causal_steps = [
            {
                "step_num": 1,
                "condition": f"Given: Y = {b}",
                "action": "Apply constraint: Y must be positive",
                "expected_state_change": {"Y": b},
            },
            {
                "step_num": 2,
                "condition": "Goal: X + Y = ?",
                "action": f"Apply constraint: sum must equal {target_sum}",
                "expected_state_change": {"target": target_sum},
            },
            {
                "step_num": 3,
                "condition": f"Solve: X = {target_sum} - {b}",
                "action": "Verify against all constraints",
                "expected_state_change": {"X": a},
            },
        ]

        task = AmaBenchTask(
            task_id=f"ama_bench_{i:03d}",
            category="arithmetic_reasoning",
            description=f"Solve: If Y = {b} and X + Y = {target_sum}, find X. Constraints: {', '.join(constraints[:2])}",
            initial_state={"Y": b},
            constraints=constraints,
            causal_steps=causal_steps,
            expected_final_state={"X": a, "Y": b, "sum": target_sum},
            expected_solution=str(a),
            arithmetic_operations=[
                {
                    "operands": [target_sum, b],
                    "operator": "subtract",
                    "expected_result": a,
                    "constraint_dependent": True,
                }
            ],
        )
        tasks.append(task)

    return tasks


def generate_memory_arena_tasks(num_tasks: int = 10, seed: int = 42) -> List[MemoryArenaTask]:
    """
    Generate MemoryArena tasks: spatial/abstract state with interdependent updates.

    Example: "Move object A from Box1 to Box3. Constraint: Box1 has capacity 2."
    State: {box1_items=2, box2_items=1, box3_items=0, ...}
    Action sequence: [remove_A_from_box1, place_A_in_box3, verify_capacities]
    """
    random.seed(seed)
    tasks = []

    for i in range(num_tasks):
        difficulty = (i % 3) + 1
        num_objects = 2 + difficulty
        num_boxes = 3 + difficulty

        # State variables: box capacities and current contents
        boxes = {f"box_{j}": {"capacity": random.randint(2, 5), "items": []} for j in range(num_boxes)}
        objects = [f"obj_{k}" for k in range(num_objects)]

        # Place initial objects
        for obj in objects[:-1]:
            target_box = random.choice(list(boxes.keys()))
            boxes[target_box]["items"].append(obj)

        # Constraints: capacity, ordering, dependencies
        constraints = [
            f"Each box has a capacity limit",
            f"Cannot exceed {num_boxes} items across all boxes",
        ]
        if difficulty >= 2:
            constraints.append("Object A must be in a box with capacity >= 3")
        if difficulty >= 3:
            constraints.append("If B is in box_0, then C must be in box_1")

        # Action sequence: move objects while respecting constraints
        action_sequence = [f"move_obj_{num_objects-1}_to_box_0"]
        if difficulty >= 2:
            action_sequence.append(f"verify_constraint_A_capacity")
        if difficulty >= 3:
            action_sequence.append(f"verify_constraint_B_C_dependency")

        # Build causal steps
        causal_steps = []
        for step_num, action in enumerate(action_sequence, 1):
            causal_steps.append(
                {
                    "step_num": step_num,
                    "condition": f"Current state: {num_objects} objects in {num_boxes} boxes",
                    "action": action,
                    "expected_state_change": {
                        "items_moved": step_num,
                        "constraints_checked": step_num,
                    },
                }
            )

        # Final state: object should be in target box
        expected_final = {
            "object_location": f"obj_{num_objects-1}_in_box_0",
            "constraints_satisfied": difficulty,
        }

        task = MemoryArenaTask(
            task_id=f"memory_arena_{i:03d}",
            category="spatial_reasoning",
            description=f"Manage {num_objects} objects across {num_boxes} boxes with constraints",
            initial_state={
                "num_boxes": num_boxes,
                "num_objects": num_objects,
                "boxes": boxes,
            },
            constraints=constraints,
            causal_steps=causal_steps,
            expected_final_state=expected_final,
            expected_solution=f"obj_{num_objects-1}_in_box_0",
            state_variables={
                "box_contents": {box_id: len(data["items"]) for box_id, data in boxes.items()},
                "capacity_used": {box_id: len(data["items"]) / data["capacity"] for box_id, data in boxes.items()},
            },
            action_sequence=action_sequence,
        )
        tasks.append(task)

    return tasks
