# Quest Management

SideQuests organizes knowledge into Quests — focused contexts for projects or workstreams.

## Main Quests

A Main Quest is automatically created for each project context. For developers, this maps to a git repository. For non-dev users, the Brain uses semantic routing to figure out which Quest a conversation belongs to.

## Side Quests

When a conversation shifts to a distinct tangent worth tracking separately, **ALWAYS offer to create a Side Quest:**

```
branch_quest(name="<tangent name>", purpose="<what this is about>")
```

**Important:** Always offer this — never create a Side Quest without the user's agreement. Say something like: "This seems like a separate topic from what we've been discussing. Want me to branch this into its own Side Quest so we can track it separately?"

## Completing Quests

**When a project wraps up, you MUST call `complete_quest`:**

```
complete_quest(quest_id="<quest_id>")
```

Completed quests are excluded from active search results but remain available for cross-quest learning — the Brain can surface relevant patterns from past projects when you start something similar.

## Setting the Quest explicitly

If the Brain routes a conversation to the wrong Quest, or you want to start a specific project context:

```
set_quest(session_id="<session>", quest_name="<project name>")
```

This overrides automatic routing and locks the session to the named Quest.

## Switching Context with Memory

When switching to a different quest or returning to a project after time away, ALWAYS call `diff_since` to see what changed:

```
diff_since(since_iso="<last session timestamp>")
```

This shows nodes created, updated, or deprecated since your last visit — crucial for catching up on changes made in other conversations or by other agents.

If you don't know the last session timestamp, use `reconstruct_timeline` to see recent activity:

```
reconstruct_timeline(quest_id="<quest>", limit=20)
```

