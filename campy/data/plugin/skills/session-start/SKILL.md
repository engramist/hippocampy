# Session Start — Memory Recall Protocol

**This skill fires at the START of every conversation.** Before doing any work, you MUST follow this 4-step protocol to load context from the Brain.

## Step 1: Ask the Brain What to Recall

Call `memory_decision` with the user's first message to get routing advice:

```
memory_decision(query="<user's first message or topic>", session_id="<session>")
```

The Brain returns:
- `recommended_tool`: which recall tool to call next
- `reasoning`: why this tool was chosen
- `confidence`: how confident the routing is

## Step 2: Call the Recommended Tool

Based on `recommended_tool` from Step 1:

| Recommendation | Action |
|---|---|
| `current_truth` | `current_truth(query="<topic>", session_id="<session>")` |
| `compile_context` | `compile_context(query="<topic>", token_budget=32000, agent_type="<your type>")` |
| `recall_procedures` | `recall_procedures(query="<process topic>")` |
| `recall_relevant_lessons` | `recall_relevant_lessons(query="<topic>")` |
| `recall_plans` | `recall_plans(query="<plan topic>")` |
| `none` | Skip to Step 3 (Brain has no relevant context) |

**ALWAYS call the recommended tool.** Do not skip this step.

## Step 3: Check for Recent Changes

If you are continuing work on an existing project or quest, call `diff_since` to see what changed since the last session:

```
diff_since(since_iso="<last session ISO timestamp>")
```

If you don't know the last session timestamp, use a reasonable default (e.g., 24 hours ago):

```python
from datetime import datetime, timedelta
since = (datetime.utcnow() - timedelta(hours=24)).isoformat() + "Z"
```

## Step 4: Surface Findings Before Working

**BEFORE starting any work**, present what the Brain knows to the user:

- Summarize key facts, constraints, and decisions relevant to their request
- Mention any recent changes from `diff_since`
- Flag any low-confidence or contradictory information
- If the Brain returned nothing relevant, say so: "I checked the Brain's memory and didn't find existing context on this topic."

**The user should never wonder if you checked memory.** Make it visible that you did.

## Example Flow

User: "Let's work on the authentication refactor"

1. `memory_decision(query="authentication refactor")` → `recommended_tool: "compile_context"`
2. `compile_context(query="authentication refactor", token_budget=32000)` → returns bundle with constraints, decisions, related entities
3. `diff_since(since_iso="2026-05-19T00:00:00Z")` → 3 nodes changed since yesterday
4. "Based on the Brain's memory: we decided to use JWT with rotating refresh tokens (high confidence). The auth module was last modified yesterday — 3 changes including a new rate-limiting constraint. There's a low-confidence note about session storage that we should clarify..."
