---
name: campy-learn
description: Teach Campy a new pattern, procedure, or lesson. Use after resolving a tricky issue, discovering a recurring pattern, establishing a new procedure, or when the user says "remember this" or "learn this."
---

# Campy Learn

Encode a new piece of knowledge into Campy's graph.

## When to Use

- You just resolved a tricky bug and want to remember the fix
- You discovered a recurring pattern (errors, workflows, timing)
- The user established a new procedure they want remembered
- The user explicitly says "remember this" or "don't forget"

## Process

1. Ask the user (or determine from context):
   - **What happened?** The situation or problem.
   - **What was the solution?** The fix, procedure, or decision.
   - **What triggers this?** When should this knowledge surface again?
     (error message, action pattern, time interval, domain area)

2. Determine the knowledge type:
   - **Lesson** — something learned from experience
     Call `upsert_lesson` with:
     - lesson_text: the lesson content
     - lesson_type: one of mistake|edge-case|optimization|architecture-principle
     - tags: relevant keywords

   - **Procedure** — a step-by-step process
     Call `register_plan` with:
     - goal: what the procedure achieves
     - steps: ordered list of steps
     - Include metadata: `{"procedure": true, "trigger": "<pattern>"}`

   - **Decision** — an architectural or design choice
     This is captured automatically by passive ingestion.
     Just make sure the decision is clearly stated in the conversation.

3. Confirm with the user that the knowledge was stored.

4. If the user specified a trigger pattern (e.g., "remind me when I run docker"),
   note it in the plan/lesson metadata. This metadata is inert now but will be
   consumed by the trigger manifest compiler in Phase 2 (Associative Hooks).

## Trigger Metadata Format (Phase 2 readiness)

When storing a Procedure or Lesson with a trigger, include in metadata:
```json
{
  "trigger": {
    "pattern": "regex pattern to match",
    "hook_type": "PreToolUse or PostToolUse",
    "tool": "Bash or Edit or Write",
    "project_scope": "optional project path"
  }
}
```
