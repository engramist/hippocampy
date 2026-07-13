# HippoCampy Plugin

HippoCampy adds durable memory to Claude, Codex, and Gemini clients. The plugin ships shared MCP wiring, hooks, and process skills so the agent can recall prior decisions, keep project context across sessions, and surface relevant lessons without maintaining a separate per-client setup tree.

## Engine Setup

This plugin is only the agent-side integration layer. Install and start the engine first:

```bash
pip install hippocampy
campy start
campy setup
```

That installs the daemon-backed memory engine, starts the background process, and exposes the MCP endpoint at `http://127.0.0.1:7799/mcp`.

## Install By Platform

### Claude Code / Claude Desktop

Use the plugin folder directly:

```bash
claude plugin install /path/to/hippocampy/plugin
```

Or in Claude Desktop Cowork:

1. Open Claude Desktop → switch to Cowork tab
2. Click "Customize" in the left sidebar
3. Upload this plugin folder

### Codex

Install from the plugin directory:

```bash
codex plugin install /path/to/hippocampy/plugin
```

For the git-backed marketplace flow prepared in this repo:

```bash
codex plugin marketplace add engramist/hippocampy
codex plugin install hippocampy
```

### Gemini CLI

Link the local extension:

```bash
gemini extensions link /path/to/hippocampy/plugin
```

Or install from the repository URL once published through Gemini's gallery flow:

```bash
gemini extensions install https://github.com/engramist/hippocampy
```

## Included Tools

- **notify_turn** — forward conversation turns to the Brain
- **current_truth** — recall past decisions and context
- **branch_quest** — create a side quest for tangents
- **set_quest** — explicitly set the active project
- **context_status** — check context window health
- **get_open_loops** — review tentative knowledge
- **diff_since** — see what changed since last session
- **analogical_search** — find cross-project patterns
- **explore_graph** — navigate the knowledge graph
- **complete_quest** — mark a project as done
- **ingest_document** — feed documents to the Brain

## Included Skills

- **brief** — load compact project context at the start of a task or handoff
- **campy-diagnose** — debug failures and regressions with a disciplined diagnosis loop
- **campy-grill** — stress-test a plan against the codebase and its decisions
- **campy-handoff** — compress active context for another agent or a later session
- **campy-improve-architecture** — find refactoring seams and testability improvements
- **campy-tdd** — drive changes through red-green-refactor loops
- **learn** — capture a new lesson or reusable procedure into Campy memory
- **memory-awareness** — explain what Campy captures automatically and when recall is appropriate
- **quest-management** — manage project quests, branches, and workstreams
- **recall** — query durable memory before answering architecture or history questions
- **session-start** — load memory context at the beginning of a new session
- **status** — inspect daemon health and context-window state

## Full Docs

- Main documentation: https://github.com/engramist/hippocampy/tree/main/docs
- Architecture: https://github.com/engramist/hippocampy/blob/main/docs/ARCHITECTURE.md
- Installation guide: https://github.com/engramist/hippocampy/blob/main/README.md

## Verify

After installing, ask your agent what Campy tools and skills are available. If the plugin loads but memory does not respond, check the engine first:

```bash
campy status
```
