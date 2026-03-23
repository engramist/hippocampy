# chain_next — Automatic Follow-On Chaining Spec

**Author:** Crusty (CTO review)  
**Date:** 2026-03-22  
**Card:** MC-006C  
**Status:** Approved for implementation

---

## Overview

When a card completes, the system can automatically create and start the next card in a pre-declared sequence. Chains are **declarative only** — defined at card creation time, never inferred at runtime.

## Schema

### `chain_next` field on a task/card

```jsonc
{
  "chain_next": [
    {
      "id": "MC-007B",              // required — unique card ID
      "title": "Do the next thing", // required
      "agent": "Claws",             // required — who owns execution
      "priority": "high",           // required — "low" | "medium" | "high" | "critical"
      "execution_mode": "claws_direct", // required
      "model": "gpt-5.4",          // optional — defaults to agent's default
      "on_success": "...",          // optional
      "on_failure": "...",          // optional
      "escalate_to": "Crusty",     // optional
      "notes": "...",              // optional — seed notes for the new card
      "chain_next": []             // optional — nested chains (depth-limited)
    }
  ]
}
```

### Field rules

| Field | Required | Notes |
|-------|----------|-------|
| `id` | yes | Must be unique across the board. Use parent prefix (e.g. `MC-007B`). |
| `title` | yes | Concrete scope — not vague. |
| `agent` | yes | The agent who will own the created card. |
| `priority` | yes | Inherited from template, not auto-escalated. |
| `execution_mode` | yes | Must be explicit. No defaulting to `crusty_review`. |
| `model` | no | Falls back to agent default if omitted. |
| `chain_next` | no | Nested chains for multi-step sequences. Subject to depth limit. |

## Guardrails

### Auto-chain proceeds when ALL of these are true:
1. `chain_next[0]` exists on the completing card
2. The completing signal is `worker_completed`, `cron_completed`, or `review_approved`
3. The next card's `agent` matches the completing card's `agent` (same-agent handoff)
4. The next card's `priority` is NOT `critical`
5. The next card's `execution_mode` does NOT contain `"review"`
6. Chain depth from the original parent ≤ 3

### If any guardrail fails → block and require approval:
- Set the completing card to `column: "under_review"`, `phase: "chain_blocked"`
- Set `waiting_on: "chain_approval"`
- Set `next_event: "chain_approval_decision"`
- Log the reason the guardrail tripped in notes

### Guardrail summary table

| # | Rule | Rationale |
|---|------|-----------|
| 1 | Template exists | No chaining from nothing |
| 2 | Success signal only | Don't chain on failure |
| 3 | Same-agent | Cross-agent handoffs need human routing |
| 4 | Not critical priority | Critical work gets human eyes |
| 5 | No review-mode | Review cards are inherently human-gated |
| 6 | Depth ≤ 3 | Prevent runaway chains |

## Behavior

### On card completion (in `_apply_workflow_signal`):

```
if signal in {worker_completed, cron_completed, review_approved}:
    if task has chain_next[0]:
        template = chain_next[0]
        if passes_all_guardrails(template, current_depth):
            new_card = create_card_from_template(template)
            new_card.column = "in_progress"
            new_card.phase = "running"
            new_card.started_at = now
            new_card.chain_depth = current_depth + 1
            append to tasks[]
            remove chain_next[0] from completing card
            log to digest: "Auto-chained: {id} → {new_id}"
        else:
            block_for_approval(task, reason)
```

### New fields on cards:

| Field | Type | Purpose |
|-------|------|---------|
| `chain_next` | `array` | Ordered list of follow-on card templates |
| `chain_depth` | `int` | How deep in a chain this card is (0 = root) |
| `chained_from` | `string \| null` | ID of the card that auto-created this one |

### Digest logging

Every auto-created card MUST appear in the digest with:
- Source card ID
- New card ID and title
- Which guardrails were evaluated
- Chain depth

## What NOT to build

- **No inference.** The system never guesses what comes next.
- **No auto-escalation.** Priority doesn't change during chaining.
- **No cross-agent auto-handoff.** Always requires approval.
- **No retroactive chaining.** You can't add `chain_next` to a completed card and expect it to fire.

## Implementation notes

1. Add `chain_next`, `chain_depth`, `chained_from` to the task schema
2. Hook into `_apply_workflow_signal` after the completion branch
3. Add a `_check_chain_guardrails(template, depth) -> (bool, reason)` function
4. Add a `_create_card_from_chain_template(template, parent_id, depth) -> dict` function
5. Log to digest via existing digest append path
6. Add `/api/workflow/chain/approve` endpoint to unblock `chain_blocked` cards

---

*Approved by Crusty. Implementation assigned to Claws.*
