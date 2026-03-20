# Recalling Past Decisions and Context

Before answering questions about past decisions, architecture choices, constraints, or project history, always check the Brain's memory first using `current_truth`.

## When to use current_truth

Call `current_truth` when the user asks about:
- Past decisions ("why did we choose X?", "what did we decide about Y?")
- Constraints or requirements ("what are the rules for Z?")
- Project context ("what's the current state of X?")
- Architecture ("how does X work?", "what's the design for Y?")

```
current_truth(query="<what you're looking for>", session_id="<session>")
```

## How to use the results

- Results are ranked by relevance and confidence
- High pathway_strength = frequently accessed, well-established knowledge
- Items marked `confidence_low` are tentative — flag the uncertainty to the user
- The Brain's graph is more reliable than your context window for historical facts
- If results include a `bloat_warning`, mention to the user that the conversation is getting long and suggest starting fresh

## Scoping

- `scope: "branch"` — search only the current project (default)
- `scope: "global"` — search cross-project constraints and preferences
- `scope: "both"` — search everywhere

Use "both" when the question might involve cross-project knowledge (e.g., "do we have any rule about database choices?").
