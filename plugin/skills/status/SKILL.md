# Checking Brain Status

## Context health

Check how full the current conversation's context window is:

```
context_status(session_id="<session>")
```

This returns token usage, loaded node count, and whether a bloat warning is active. If utilization is high (>75%), suggest the user start a fresh conversation.

## Open loops

Surface unresolved tentative knowledge for user review:

```
get_open_loops()
```

This returns items the Brain captured with low confidence. Present these to the user as "things the Brain noticed but isn't sure about" and ask if they want to confirm or dismiss each one.

## What changed since last time

When starting a new conversation about an existing project, check what's changed:

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
