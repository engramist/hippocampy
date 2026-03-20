# SideQuests Brain Plugin

AI memory that learns from every conversation. Automatically captures decisions, constraints, and plans — then recalls them when you need them.

## Prerequisites

The SideQuests Brain Daemon must be running. Install it first:

```bash
pip install sidequests-brain
sidequests install
```

This sets up the memory engine, starts the background daemon, and configures the SSE endpoint at `http://127.0.0.1:7799/sse`.

## Install the Plugin

### Option A: Claude Cowork UI
1. Open Claude Desktop → switch to Cowork tab
2. Click "Customize" in the left sidebar
3. Upload this plugin folder

### Option B: Claude CLI
```bash
claude plugins add /path/to/sidequests-brain/plugin
```

## What You Get

### Tools (available in both Claude Desktop and Cowork)
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

### Skills (Cowork only)
- **memory-awareness** — how the Brain captures knowledge automatically
- **recall** — when and how to check memory before answering
- **quest-management** — organizing projects and side quests
- **status** — monitoring context health and reviewing open loops

## Verify

After installing, ask Claude: "What tools do you have from SideQuests?"
Claude should list the tools above. If not, ensure the Brain Daemon is running: `sidequests status`
