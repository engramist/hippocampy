---
name: campy-handoff
description: Campy-enhanced handoff that writes a transfer note and persists it to Campy's graph. Use this over generic handoff variants when you want cross-session retrieval via compile_context.
argument-hint: "What will the next session be used for?"
---

# Handoff

Write a handoff document and persist it to Campy's graph so the next session can pick up seamlessly.

Process adapted from Matt Pocock's skills (mattpocock/skills), enhanced with graph persistence.

## When to Use

- Your context window is getting large (approaching compaction)
- You need to spawn a sub-agent for a specific task
- You're ending a session and want the next one to pick up seamlessly
- You're switching between agent tools (Claude Code → Codex, etc.)

## Sending a Handoff

### 1. Summarize state

Capture these in a compact handoff document:
- What was the goal?
- What has been done?
- What remains?
- Key decisions made and why
- Blockers or open questions

### 2. Write handoff document to temp directory

Save the handoff doc as a markdown file in the OS temp directory — not the workspace. Include a "suggested skills" section recommending skills the next session should invoke.

Do not duplicate content already captured in other artifacts (PRDs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.

Redact any sensitive information (API keys, passwords, PII).

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.

### 3. Persist to Campy's graph

Call `register_plan` with:
- goal: the handoff summary
- steps: remaining work items
- Include metadata: `{"handoff": true, "source_session": "<session_id>"}`

This enables cross-machine handoff — the receiving session retrieves it from the graph, not the local filesystem.

### 4. Report to user

Give the user both:
- The /tmp file path (for immediate local use)
- The `plan_id` from register_plan (for graph-based retrieval)

## Receiving a Handoff

When picking up work from a previous session:

1. Call `compile_context(query="handoff for <task description>")` — this surfaces the most recent handoff plan and related context from the graph.
2. Or call `recall_plans(query=<what you're picking up>)` — returns plans with handoff metadata.
3. Read CONTEXT.md for domain terminology.
4. Confirm understanding with the user before proceeding.
