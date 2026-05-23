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
   pass the trigger metadata in the `trigger` parameter of `upsert_lesson`.
   The trigger manifest is recompiled every sweep cycle (~5 minutes).
   After creation, the user can verify with `campy trigger list`.

## Trigger Metadata

When storing a Lesson with a trigger, pass the `trigger` parameter:

```json
{
  "trigger": {
    "pattern": "regex pattern to match tool input/output",
    "hook_type": "PreToolUse or PostToolUse",
    "tool": "Bash or Edit or Write (empty for all)",
    "project_scope": "optional project path (empty for all)"
  }
}
```

Example — remember that docker requires OD env vars:
```json
{
  "text": "OD docker containers require OAUTH_TOKEN and CLUSTER_ENV vars",
  "lesson_type": "edge-case",
  "trigger": {
    "pattern": "docker run|docker build|docker compose",
    "hook_type": "PreToolUse",
    "tool": "Bash"
  }
}
```

The manifest compiler picks this up on the next sweep and the
PreToolUse hook will inject the lesson text before any matching
Bash command runs.
