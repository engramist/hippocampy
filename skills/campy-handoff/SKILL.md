---
name: campy-handoff
description: Graph-backed session handoff. Use when passing work to another agent session, ending a long session, or when context is getting too large. Extends /handoff with persistent graph storage.
---

# Campy Handoff

Hand off your current session state to Campy's graph for pickup by another session.

## When to Use

- Your context window is getting large (approaching compaction)
- You need to spawn a sub-agent for a specific task
- You're ending a session and want the next one to pick up seamlessly
- You're switching between agent tools (Claude Code → Codex, etc.)

## Process

### Sending a Handoff

1. Summarize the current state:
   - What was the goal?
   - What has been done?
   - What remains?
   - Key decisions made and why
   - Blockers or open questions

2. Call `register_plan` with:
   - goal: the handoff summary
   - steps: remaining work items
   - Include metadata: `{handoff: true, source_session: <session_id>}`

3. If you have Matt's /handoff skill available, run it too — it creates a
   complementary /tmp markdown file for immediate use.

4. Report the plan_id to the user so the receiving session can reference it.

### Receiving a Handoff

1. Call `compile_context` with:
   - query: "handoff state for [project/task description]"
   - This will surface the most recent handoff plan and related context.

2. Or call `recall_plans` with:
   - query: describe what you're picking up
   - This returns plans with handoff metadata.

3. Read CONTEXT.md for domain terminology.

4. Confirm understanding with the user before proceeding.
