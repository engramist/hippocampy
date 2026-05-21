# Recalling Past Decisions and Context

Before answering questions about past decisions, architecture choices, constraints, or project history, ALWAYS check the Brain's memory first.

## Tool Reference

| Tool | When to Use |
|---|---|
| `current_truth` | Single-topic recall: "why did we choose X?", "what's the constraint on Y?" |
| `compile_context` | Multi-entity queries: "tell me everything about the auth system", broad context needs |
| `memory_decision` | Not sure which tool? Call this first — it recommends the right retrieval tool |
| `recall_procedures` | "How do we deploy?", "What's the process for X?" — procedural knowledge |
| `recall_relevant_lessons` | "What went wrong last time?", "Any lessons about X?" — past outcomes |
| `reconstruct_timeline` | "What happened this week?", "When did we decide X?" — temporal queries |
| `analogical_search` | "Have we done something like this before?" — cross-project patterns |
| `explore_graph` | Browse entity connections: "What's related to X?" |
| `diff_since` | "What changed since yesterday?" — recent changes |

## When to Use current_truth

Call `current_truth` when the user asks about:
- Past decisions ("why did we choose X?", "what did we decide about Y?")
- Constraints or requirements ("what are the rules for Z?")
- Project context ("what's the current state of X?")
- Architecture ("how does X work?", "what's the design for Y?")

```
current_truth(query="<what you're looking for>", session_id="<session>")
```

## When to Use compile_context

Call `compile_context` for broad or multi-entity queries:
- "Tell me everything about the payment system"
- "What do I need to know before changing the auth module?"
- Starting work on a component you haven't touched recently

```
compile_context(query="<broad query>", token_budget=32000, agent_type="claude_code")
```

## When to Use memory_decision

Call `memory_decision` when you're not sure which tool to use:

```
memory_decision(query="<user's question>", session_id="<session>")
```

It returns a `recommended_tool` field telling you exactly which tool to call next.

## Scoping

- `scope: "branch"` — search only the current project (default)
- `scope: "global"` — search cross-project constraints and preferences
- `scope: "both"` — search everywhere

## How to Use Results

- Results are ranked by relevance and confidence
- High pathway_strength = frequently accessed, well-established knowledge
- Items marked `confidence_low` are tentative — flag the uncertainty to the user
- The Brain's graph is more reliable than your context window for historical facts
- If results include a `bloat_warning`, mention to the user that the conversation is getting long

