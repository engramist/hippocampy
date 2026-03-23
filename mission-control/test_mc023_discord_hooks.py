"""
MC-023 Smoke Test — Discord operating model hook previews.

Tests:
1. Thread heuristic defaults
2. Anchor plan generation for active cards
3. Blocker routing preview
4. Completion post preview
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from server import _discord_thread_needed, _discord_hook_plan, _discord_config_status, DISCORD_CHANNELS

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


print("=== MC-023 Smoke Tests ===\n")

print("Test 1: Thread heuristic")
impl_task = {
    "id": "MC-023",
    "title": "Implement Discord hooks",
    "priority": "high",
    "card_type": "implementation",
    "phase": "implementation",
}
check("implementation cards default to thread-needed", _discord_thread_needed(impl_task) is True)
check("explicit override can disable thread", _discord_thread_needed({**impl_task, "discord_thread_needed": False}) is False)

print("\nTest 2: Anchor plan generation")
active_task = {
    **impl_task,
    "column": "in_progress",
    "agent": "Gemini",
    "notes": "Build first Discord automation slice.",
    "next_event": "wire previews",
}
actions = _discord_hook_plan(active_task)
anchor = next(a for a in actions if a["kind"] == "anchor")
check("anchor goes to mission-control", anchor["channel"] == DISCORD_CHANNELS["anchor"])
check("anchor defaults to create without stored message id", anchor["mode"] == "create")
check("anchor suggests thread", anchor["thread_needed"] is True)

print("\nTest 3: Blocker routing preview")
blocked_task = {
    **active_task,
    "phase": "blocked",
    "waiting_on": "dj_decision",
    "next_check_at": "2026-03-23T19:30:00+00:00",
    "on_failure": "work stalls until decision lands",
}
blocked_actions = _discord_hook_plan(blocked_task)
blocker = next(a for a in blocked_actions if a["kind"] == "blocker")
check("blocker routes to blocked-decisions", blocker["channel"] == DISCORD_CHANNELS["blocked"])
check("blocker body includes waiting_on", "dj_decision" in blocker["body"])

print("\nTest 4: Completion preview")
completed_task = {
    **active_task,
    "column": "completed",
    "phase": "completed",
    "spec_path": "plans/MC-021-discord-operating-model.md",
    "on_success": "Discord can mirror completion safely",
    "discord_anchor_message_id": "msg-123",
}
completed_actions = _discord_hook_plan(completed_task, signal="worker_completed")
completion = next(a for a in completed_actions if a["kind"] == "completion")
anchor_reply = next(a for a in completed_actions if a["kind"] == "anchor_reply")
check("completion routes to ship-log", completion["channel"] == DISCORD_CHANNELS["shiplog"])
check("completion body includes artifact path", "plans/MC-021-discord-operating-model.md" in completion["body"])
check("completion adds anchor reply when anchor exists", anchor_reply["mode"] == "reply")

print("\nTest 5: Config status names the first missing live-write gate")
config = _discord_config_status()
check("config exposes first_missing", "first_missing" in config)
check("config exposes ready_for_live_execute", "ready_for_live_execute" in config)
if config["missing"]:
    check("first_missing matches first missing entry", config["first_missing"] == config["missing"][0])
else:
    check("first_missing is None when nothing missing", config["first_missing"] is None)

print(f"\n=== Results: {passed} passed, {failed} failed ===")
sys.exit(0 if failed == 0 else 1)
