"""
Hardening tests — rate limit detection, atomic writes, notes capping, card_type.
"""

import json
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from server import (
    _is_rate_limit_error,
    _retry_time_from_error,
    _cap_signal_notes,
    _append_task_note,
    _apply_workflow_signal,
    _board_state_badges,
    MAX_SIGNAL_NOTES,
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


print("=== Hardening Tests ===\n")

# --- Test 1: _is_rate_limit_error ---
print("Test 1: Rate limit error detection")
check("detects '429' in message", _is_rate_limit_error("HTTP 429 Too Many Requests"))
check("detects 'rate limit' in message", _is_rate_limit_error("Error: rate limit exceeded"))
check("detects 'quota' in message", _is_rate_limit_error("Quota exceeded for model"))
check("detects 'throttle' in message", _is_rate_limit_error("Request throttled"))
check("rejects normal 401 error", not _is_rate_limit_error("401 Unauthorized"))
check("rejects empty string", not _is_rate_limit_error(""))
check("rejects None", not _is_rate_limit_error(None))

# --- Test 2: _retry_time_from_error ---
print("\nTest 2: Retry time extraction")
check("extracts ISO timestamp", _retry_time_from_error("retry after 2026-03-23T10:00:00Z") == "2026-03-23T10:00:00Z")
check("uses fallback when no timestamp found", _retry_time_from_error("some error", fallback_at="2026-03-24T00:00:00Z") == "2026-03-24T00:00:00Z")
check("returns None with no match and no fallback", _retry_time_from_error("some error") is None)
check("extracts epoch seconds", _retry_time_from_error("reset at 1711234567") is not None)

# --- Test 3: rate_limited signal handling ---
print("\nTest 3: rate_limited signal in _apply_workflow_signal")
task = {"id": "test-1", "column": "in_progress", "phase": "running", "notes": ""}
_apply_workflow_signal(task, "rate_limited", detail="429 too many requests")
check("sets phase to blocked", task["phase"] == "blocked")
check("sets waiting_on to rate_limit_reset", task["waiting_on"] == "rate_limit_reset")
check("sets next_event to retry_after_reset", task["next_event"] == "retry_after_reset")
check("appends signal note", "rate_limited" in (task.get("notes") or ""))

# --- Test 4: _cap_signal_notes ---
print("\nTest 4: Signal notes capping")
task = {"notes": "Base description of card"}
for i in range(25):
    _append_task_note(task, f"Signal worker_progress @ {i}: audit pass #{i}")
check("has 26 parts before capping", len(task["notes"].split(" | ")) == 26)

_cap_signal_notes(task)
parts = task["notes"].split(" | ")
check(f"capped to base + {MAX_SIGNAL_NOTES} signal notes", len(parts) == 1 + MAX_SIGNAL_NOTES)
check("base note preserved", parts[0] == "Base description of card")
check("keeps most recent signals", "audit pass #24" in parts[-1])
check("drops oldest signals", "audit pass #0" not in task["notes"])

# --- Test 5: loop card notes don't grow unbounded ---
print("\nTest 5: Loop card type in _cap_signal_notes")
task_no_signals = {"notes": "Just a base note with no signals"}
_cap_signal_notes(task_no_signals)
check("no-signal notes unchanged", task_no_signals["notes"] == "Just a base note with no signals")

task_empty = {"notes": ""}
_cap_signal_notes(task_empty)
check("empty notes unchanged", task_empty["notes"] == "")

# --- Test 6: _is_rate_limit_error edge cases ---
print("\nTest 6: Rate limit edge cases")
check("detects 'tokens per min'", _is_rate_limit_error("Exceeded tokens per min limit"))
check("case insensitive", _is_rate_limit_error("RATE LIMIT exceeded"))
check("detects 'Too Many Requests'", _is_rate_limit_error("Error: Too Many Requests"))

# --- Test 7: board badges include persistent operational state ---
print("\nTest 7: Persistent state badge rendering")
badges = _board_state_badges({
    "column": "in_progress",
    "phase": "running",
    "persistent_state": "operational",
    "persistent_state_reason": "long-lived board audit loop",
})
persistent_badges = [b for b in badges if b.get("short") == "Ops Loop"]
check("adds persistent-state badge", len(persistent_badges) == 1)
check("persistent badge carries reason detail", persistent_badges[0].get("detail") == "long-lived board audit loop")

print(f"\n=== Results: {passed} passed, {failed} failed ===")
sys.exit(0 if failed == 0 else 1)
