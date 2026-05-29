# Campy Memory Integration

Before answering questions about past decisions, architecture, constraints, or project history, check Campy's memory first.

## Quick Start

If you are not sure which retrieval tool to use, call:

```text
memory_decision(query="<user question>", session_id="<session>")
```

Follow the returned `recommended_tool`. If confidence is low, skip recall.

## Mandatory Recall Triggers

| When You See This | Call This |
|---|---|
| Questions about past decisions | `current_truth(query="<decision topic>")` |
| Why did we choose X? | `current_truth(query="decision about X")` |
| Architecture or design questions | `current_truth(query="<architecture topic>")` |
| Multi-entity or broad context needs | `compile_context(query="<broad topic>")` |
| Tell me everything about X | `compile_context(query="X")` |
| Process or procedure questions | `recall_procedures(query="<process>")` |
| What went wrong last time? | `recall_relevant_lessons(query="<topic>")` |
| What happened this week? | `reconstruct_timeline(limit=20)` |
| What changed since yesterday? | `diff_since(since_iso="<ISO timestamp>")` |

## Anti-Bloat Rules

- Use the top 3 results unless exhaustive review is needed.
- Summarize compactly. Memory informs the answer; it is not the answer.
- Do not paste raw memory output.
- If nothing relevant is found, say so.