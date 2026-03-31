#!/usr/bin/env python3
"""Quick test to verify ABTaskResult captures final_state and final_observation."""

from dataclasses import asdict
from benchmarks.ab_harness import ABTaskResult, ABVariant

# Test 1: Create ABTaskResult with final_state and final_observation
result = ABTaskResult(
    task_id="test_001",
    variant=ABVariant.SIDEQUESTS,
    correct=True,
    steps=5,
    tokens_input=100,
    tokens_output=200,
    final_state="WIN",
    final_observation={"grid": [[[1, 2], [3, 4]]], "state": "WIN"}
)

print("✓ ABTaskResult created with final_state and final_observation")

# Test 2: Convert to dict
result_dict = asdict(result)
print(f"✓ asdict() successful")
print(f"  Keys in result_dict: {list(result_dict.keys())}")

# Test 3: Check if fields are present
assert "final_state" in result_dict, "final_state not in result_dict!"
assert "final_observation" in result_dict, "final_observation not in result_dict!"
assert result_dict["final_state"] == "WIN", f"final_state = {result_dict['final_state']}, expected 'WIN'"
assert result_dict["final_observation"]["state"] == "WIN", "final_observation.state not preserved"

print(f"✓ final_state captured: {result_dict['final_state']}")
print(f"✓ final_observation captured: {result_dict['final_observation']}")
print("\n✅ All tests passed! Final state capturing works correctly.")
