"""
MC-020 Smoke Test — risk and escalation state rendering helpers.

Tests:
1. Risk tier metadata mapping
2. Crusty decision metadata mapping
3. Board badges prioritize blocked + DJ-needed visibility
4. Badge details include rationale/question context
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from server import _risk_tier_meta, _crusty_decision_meta, _board_state_badges

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


print("=== MC-020 Smoke Tests ===\n")

print("Test 1: Risk tier metadata")
risk = _risk_tier_meta("tier3_dj_required")
check("tier3 label is DJ Required", risk["label"] == "Tier 3 · DJ Required")
check("tier3 short label is compact", risk["short"] == "T3 DJ")
check("tier3 classes mention rose tone", "rose" in risk["classes"])

print("\nTest 2: Crusty decision metadata")
decision = _crusty_decision_meta("approve_with_guardrails")
check("guardrails label is expanded", decision["label"] == "Approve w/ Guardrails")
check("guardrails short label is compact", decision["short"] == "Guardrails")
check("guardrails classes mention cyan tone", "cyan" in decision["classes"])

print("\nTest 3: Board badges")
task = {
    "column": "in_progress",
    "phase": "blocked",
    "waiting_on": "dj_review",
    "dj_decision_required": True,
    "dj_decision_question": "Should we ship this externally?",
    "risk_tier": "tier3_dj_required",
    "risk_reason": "External blast radius",
    "crusty_decision": "elevate_to_dj",
    "crusty_rationale": "Needs explicit DJ call",
}
badges = _board_state_badges(task)
check("blocked badge appears first", badges[0]["short"] == "Blocked")
check("DJ needed badge present", any(b["short"] == "DJ Needed" for b in badges))
check("risk tier badge present", any(b["short"] == "T3 DJ" for b in badges))
check("decision badge present", any(b["short"] == "Elevate" for b in badges))

print("\nTest 4: Badge details")
dj_badge = next(b for b in badges if b["short"] == "DJ Needed")
decision_badge = next(b for b in badges if b["short"] == "Elevate")
check("DJ badge carries the decision question", "ship this externally" in dj_badge["detail"])
check("decision badge carries rationale", "explicit DJ call" in decision_badge["detail"])

print(f"\n=== Results: {passed} passed, {failed} failed ===")
sys.exit(0 if failed == 0 else 1)
