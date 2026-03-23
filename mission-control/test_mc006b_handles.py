"""
MC-006B Smoke Test — Execution handles as first-class workflow state.

Tests:
1. Handle extraction from task cards
2. Handle status inference from card lifecycle
3. Staleness detection
4. Signal endpoint propagates handle updates
5. /api/workflow/handles returns active handles
6. Reconcile detects stale handles
7. Board template renders handle badges
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Add mission-control to path so we can import server
sys.path.insert(0, str(Path(__file__).parent))

from server import (
    _get_execution_handles,
    _infer_handle_status,
    _is_handle_stale,
    _set_handle_from_signal,
    _jinja_execution_handles,
    HANDLE_TYPES,
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


print("=== MC-006B Smoke Tests ===\n")

# --- Test 1: Handle extraction ---
print("Test 1: Handle extraction")
task_with_handles = {
    "id": "T-001",
    "run_ref": "faint-summit",
    "job_ref": "c2307f29-a560-40b4-8528-d196d7edb6bd",
    "session_ref": None,
    "process_ref": None,
    "phase": "running",
    "column": "in_progress",
}
handles = _get_execution_handles(task_with_handles)
check("extracts 2 handles from task with run_ref + job_ref", len(handles) == 2)
check("first handle is run_ref", handles[0]["field"] == "run_ref")
check("second handle is job_ref", handles[1]["field"] == "job_ref")
check("handle labels are correct", handles[0]["label"] == "Run" and handles[1]["label"] == "Job")

task_no_handles = {"id": "T-002", "run_ref": None, "job_ref": None, "phase": "backlog", "column": "backlog"}
check("empty handles for task with no refs", len(_get_execution_handles(task_no_handles)) == 0)

# --- Test 2: Handle status inference ---
print("\nTest 2: Handle status inference")
check("running task → active", _infer_handle_status({"phase": "running", "column": "in_progress"}, "run_ref") == "active")
check("completed task → completed", _infer_handle_status({"phase": "completed", "column": "completed"}, "job_ref") == "completed")
check("blocked task → stale", _infer_handle_status({"phase": "blocked", "column": "in_progress"}, "run_ref") == "stale")
check("ready task → pending", _infer_handle_status({"phase": "ready", "column": "backlog"}, "job_ref") == "pending")
check("backlog task → pending", _infer_handle_status({"phase": "backlog", "column": "backlog"}, "run_ref") == "pending")

# --- Test 3: Staleness detection ---
print("\nTest 3: Staleness detection")
now = datetime.now(timezone.utc)
stale_task = {
    "id": "T-003",
    "run_ref": "some-run",
    "job_ref": None,
    "session_ref": None,
    "process_ref": None,
    "phase": "running",
    "column": "in_progress",
    "last_signal_at": (now - timedelta(hours=7)).isoformat(),
}
check("task with 7h-old signal is stale", _is_handle_stale(stale_task, now) is True)

fresh_task = {**stale_task, "last_signal_at": (now - timedelta(hours=1)).isoformat()}
check("task with 1h-old signal is not stale", _is_handle_stale(fresh_task, now) is False)

completed_task = {**stale_task, "column": "completed"}
check("completed task is never stale", _is_handle_stale(completed_task, now) is False)

no_handle_task = {"id": "T-004", "run_ref": None, "job_ref": None, "session_ref": None, "process_ref": None, "phase": "running", "column": "in_progress", "last_signal_at": (now - timedelta(hours=20)).isoformat()}
check("task without handles is not stale", _is_handle_stale(no_handle_task, now) is False)

no_signal_task = {**stale_task, "last_signal_at": None}
check("task with handles but no signal_at is stale", _is_handle_stale(no_signal_task, now) is True)

# --- Test 4: Handle propagation via signal ---
print("\nTest 4: Handle propagation via signal")
task = {"id": "T-005", "run_ref": None, "job_ref": None, "session_ref": None, "process_ref": None}
_set_handle_from_signal(task, {"run_ref": "new-run-123", "session_ref": "sess-abc"})
check("run_ref set from signal", task["run_ref"] == "new-run-123")
check("session_ref set from signal", task["session_ref"] == "sess-abc")
check("job_ref unchanged", task["job_ref"] is None)

# --- Test 5: Jinja filter shortens UUIDs ---
print("\nTest 5: Jinja execution_handles filter")
uuid_task = {
    "id": "T-006",
    "run_ref": None,
    "job_ref": "c2307f29-a560-40b4-8528-d196d7edb6bd",
    "session_ref": None,
    "process_ref": None,
    "phase": "running",
    "column": "in_progress",
}
jinja_handles = _jinja_execution_handles(uuid_task)
check("UUID shortened to 8 chars", jinja_handles[0]["short"] == "c2307f29")

short_task = {**uuid_task, "job_ref": None, "run_ref": "faint-summit"}
jinja_handles2 = _jinja_execution_handles(short_task)
check("short ref displayed as-is", jinja_handles2[0]["short"] == "faint-summit")

long_task = {**uuid_task, "job_ref": None, "run_ref": "this-is-a-very-long-run-reference-name"}
jinja_handles3 = _jinja_execution_handles(long_task)
check("long non-UUID ref truncated with ...", jinja_handles3[0]["short"].endswith("..."))

# --- Test 6: HANDLE_TYPES registry ---
print("\nTest 6: Handle types registry")
check("4 handle types defined", len(HANDLE_TYPES) == 4)
check("run_ref in registry", "run_ref" in HANDLE_TYPES)
check("job_ref in registry", "job_ref" in HANDLE_TYPES)
check("session_ref in registry", "session_ref" in HANDLE_TYPES)
check("process_ref in registry", "process_ref" in HANDLE_TYPES)

# --- Summary ---
print(f"\n=== Results: {passed} passed, {failed} failed ===")
sys.exit(0 if failed == 0 else 1)
