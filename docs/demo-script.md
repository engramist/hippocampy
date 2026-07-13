# Demo Script — Cross-Agent Handoff

30-second storyboard for the README demo GIF. Records the core wedge: hitting a token
limit in one coding agent and picking up exactly where you left off in another, with
zero manual context-passing.

## Recording setup

- Two terminal panes side by side: left = Claude Code, right = Codex (or Gemini CLI /
  VS Code Copilot — any second MCP-capable agent works).
- Both panes have Campy installed and registered (`campy setup` already run).
- Working in a repo with an active Campy session (a few turns of real work already
  captured, so there's something to resume).

## The four beats

**1. Claude Code — mid-task, token limit hits**
Show a normal working session: implementing a feature, a few tool calls, then the
context-limit message appears. The session ends abruptly, mid-task.

**2. Switch — open Codex in the right pane**
No copy-pasting a summary. No re-explaining. Just start a new session in the second
agent, in the same repo.

**3. Codex session start — the resume line appears**
The very first thing printed, before any user message, is Campy's injected resume line
— something like:

```
[Campy] Working on B29x (branch: feat/x · abc1234). Next: wire the new tool into
TOOL_HANDLERS. Last active: 2026-07-13 14:02 via claude_code.
```

This comes from `CONTEXT.md`'s `## Current Work` section, written on every turn by the
first agent — no query, no daemon round-trip, just a file read at session start.

**4. Work continues**
Ask Codex to continue the task. It picks up immediately, correctly — no "what were we
doing?" turn wasted. End on this line landing.

## What the viewer should walk away thinking

"I switched agents and it just knew." Not "I asked it to remember" — it already
remembered, before being asked.
