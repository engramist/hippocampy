"""
MC-027 Smoke Test — operational last-mile enforcement.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from server import (
    _apply_workflow_signal,
    _block_for_last_mile_gap,
    _last_mile_gaps,
)

passed = 0
failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


print("=== MC-027 Last-Mile Tests ===\n")

print("Test 1: active cards require next event + visible result")
task = {
    "id": "MC-027-A",
    "column": "in_progress",
    "phase": "implementation",
    "waiting_on": "repo_patch",
    "next_event": None,
    "on_success": None,
}
gaps = _last_mile_gaps(task)
check("missing next event flagged", "missing_last_mile_next_event" in gaps)
check("missing visible result flagged", "missing_visible_result" in gaps)

print("\nTest 2: blocked cards need named blocker")
task = {
    "id": "MC-027-B",
    "column": "in_progress",
    "phase": "blocked",
    "waiting_on": "unknown",
    "next_event": "figure_it_out",
    "visible_result": "discord post is visibly live",
}
gaps = _last_mile_gaps(task)
check("generic blocker flagged", "missing_named_blocker" in gaps)

print("\nTest 3: repair state is explicit and actionable")
task = {
    "id": "MC-027-C",
    "column": "in_progress",
    "phase": "implementation",
    "waiting_on": None,
    "next_event": None,
    "on_success": None,
    "notes": "",
}
_block_for_last_mile_gap(task, ["missing_last_mile_next_event"], "2026-03-23T16:00:00Z")
check("phase becomes blocked", task["phase"] == "blocked")
check("waiting_on names exact repair", task["waiting_on"] == "missing_last_mile_next_event")
check("next_event names repair action", task["next_event"] == "name_last_mile_next_event")

print("\nTest 4: older cards can complete via on_success fallback")
task = {
    "id": "MC-027-D",
    "column": "in_progress",
    "phase": "running",
    "waiting_on": "worker_completed",
    "next_event": "worker_completed",
    "on_success": "visible Discord post lands in ship-log",
}
_apply_workflow_signal(task, "worker_completed", detail="commit landed")
check("completion still works with on_success fallback", task["phase"] == "completed")
check("visible_result backfilled", task.get("visible_result") == "visible Discord post lands in ship-log")

print(f"\n=== Results: {passed} passed, {failed} failed ===")
sys.exit(0 if failed == 0 else 1)
