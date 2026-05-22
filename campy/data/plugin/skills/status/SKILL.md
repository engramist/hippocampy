# Checking Brain Status

## Context health

**ALWAYS check context health when the conversation is getting long:**

```
context_status(session_id="<session>")
```

This returns token usage, loaded node count, and whether a bloat warning is active. If utilization is high (>75%), suggest the user start a fresh conversation.

## Open loops

**Periodically call `get_open_loops()` to surface unresolved items:**

```
get_open_loops()
```

This returns items the Brain captured with low confidence. Present these to the user as "things the Brain noticed but isn't sure about" and ask if they want to confirm or dismiss each one.

## What changed since last time

**When starting a new conversation about an existing project, you MUST call `diff_since`:**

```
diff_since(since_iso="<ISO timestamp>")
```

This returns nodes created, updated, or deprecated since the previous session — useful for catching up on changes made in other conversations or by other team members.

## Cross-project insights

Search for relevant patterns across all projects:

```
analogical_search(query="<what you're looking for>")
```

This finds similar decisions, constraints, and patterns from other Quests — useful when starting something new that resembles past work.

## Token Budget Guidance

When using `compile_context`, specify an appropriate token budget based on your context window:

| Agent Context Size | Recommended Budget | What You Get |
|---|---|---|
| 4K-8K tokens | `token_budget=4000` | Exact facts + top 3 semantic results |
| 32K-128K tokens | `token_budget=32000` | Full semantic + graph + tabular summaries |
| 200K+ tokens | `token_budget=100000` | Everything including raw tabular data |

```
compile_context(query="<topic>", token_budget=32000, agent_type="claude_code")
```

## Bundle Truncation Awareness

When a compiled bundle exceeds the token budget, the compiler truncates lower-priority sections. If you see `"truncated": true` in a bundle response:
- The most important facts are preserved (exact constraints always survive)
- Tabular data and summaries may be compressed or omitted
- Request a larger budget if you need the full picture
- Consider narrowing your query for more focused results

