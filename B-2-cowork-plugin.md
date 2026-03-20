# B-2 — SideQuests Brain Cowork Plugin

## Overview

Package SideQuests Brain as a Claude Desktop / Cowork plugin using the official Anthropic plugin format. One plugin covers both regular Claude Desktop (MCP tools) and Cowork mode (tools + skills + commands). Replaces the original `.mcpb` bundle approach — the plugin format is simpler (just files, no build step) and natively supported.

**Target user:** DJ's wife (ChatGPT → Claude Desktop convert). Must be installable in under 60 seconds.

## Plugin Format Reference

From `github.com/anthropics/knowledge-work-plugins`:

```
plugin-name/
├── .claude-plugin/plugin.json   # Manifest (name, version, description, author)
├── .mcp.json                    # MCP server connections
├── skills/                      # Domain knowledge Claude draws on automatically
│   └── skill-name/
│       └── SKILL.md             # Markdown skill definition
└── README.md
```

- **Skills** are markdown files Claude reads automatically when relevant
- **`.mcp.json`** uses the same format as Claude Code's `.mcp.json`
- **No build step** — file-based, ready to use immediately
- Install: user uploads the folder via Cowork "Customize" → "Browse plugins" or `claude plugins add`

## Architecture Decisions

1. **MCP transport: SSE (not stdio)** — The plugin's `.mcp.json` points to `http://127.0.0.1:7799/sse` (the SSE endpoint from B3). This avoids needing the user to know the Python venv path or adapter script location. The Brain Daemon must be running (handled by launchd from `sidequests install`).

2. **Skills encode the onboarding prompt** — Instead of injecting system prompt fragments at runtime, the plugin's skills teach Claude when to call each tool. This is the Cowork-native way to do what our Layer 1 / Layer 2 instruction model does for stdio adapters.

3. **Plugin lives in-repo at `plugin/`** — Not a separate repo. Built from the same source tree. The installer can copy/symlink this directory for local installation.

4. **Installer updated** — `_register_claude_desktop()` in `install.py` should copy the plugin directory to the Claude Desktop plugins location (or print clear instructions).

## File Structure

```
plugin/
├── .claude-plugin/
│   └── plugin.json
├── .mcp.json
├── skills/
│   ├── memory-awareness/
│   │   └── SKILL.md
│   ├── recall/
│   │   └── SKILL.md
│   ├── quest-management/
│   │   └── SKILL.md
│   └── status/
│       └── SKILL.md
└── README.md
```

## Implementation — Phase by Phase

### Phase 1: Plugin manifest and MCP config

**File: `plugin/.claude-plugin/plugin.json`** (NEW)

```json
{
  "name": "sidequests-brain",
  "version": "0.1.0",
  "description": "AI memory that learns from every conversation. Automatically captures decisions, constraints, and plans — then recalls them when you need them. Works across Claude Desktop, Claude Code, Codex, and ChatGPT.",
  "author": {
    "name": "SideQuests"
  }
}
```

**File: `plugin/.mcp.json`** (NEW)

```json
{
  "mcpServers": {
    "sidequests-brain": {
      "type": "http",
      "url": "http://127.0.0.1:7799/sse"
    }
  }
}
```

This connects to the B3 SSE endpoint. The Brain Daemon must be running for tools to work.

### Phase 2: Skills

Each skill is a `SKILL.md` markdown file in its own directory under `skills/`. Claude reads these automatically when the context is relevant.

**File: `plugin/skills/memory-awareness/SKILL.md`** (NEW)

```markdown
# SideQuests Brain — Automatic Memory

SideQuests Brain is always listening to your conversations and automatically capturing important information:

- **Decisions** — choices you've made ("we chose PostgreSQL over MySQL")
- **Constraints** — rules and requirements ("API responses must be under 200ms")
- **Plans** — future actions ("next step is to migrate the auth system")
- **Concepts** — tools, people, projects, and ideas you discuss

You don't need to tell the Brain what to remember — it uses selective attention to pick up meaningful signal from conversation noise. Think of it like a colleague who's always taking notes in the background.

## How to help the Brain

After every response you give, call `notify_turn` with your full response text. This is how the Brain sees your output. Never skip it — the response is always instant and never blocks you.

```
notify_turn(role="assistant", content="<your full response>", session_id="<session>")
```

This is your one automatic duty. The Brain handles everything else.

## What the Brain captures automatically

The Brain's selective attention fires on specific patterns:
- Decision language: "we decided", "we chose", "we agreed"
- Constraint language: "never", "must", "always", "required"
- Plan language: "we will", "next step", "plan to"
- References to known concepts already in memory

Most conversation is background noise — only meaningful patterns get stored.

## Confidence levels

Not everything the Brain captures is certain. Low-confidence items are stored as tentative knowledge. If you retrieve something marked as uncertain, tell the user — don't present tentative memory as confirmed fact.
```

**File: `plugin/skills/recall/SKILL.md`** (NEW)

```markdown
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
```

**File: `plugin/skills/quest-management/SKILL.md`** (NEW)

```markdown
# Quest Management

SideQuests organizes knowledge into Quests — focused contexts for projects or workstreams.

## Main Quests

A Main Quest is automatically created for each project context. For developers, this maps to a git repository. For non-dev users, the Brain uses semantic routing to figure out which Quest a conversation belongs to.

## Side Quests

When a conversation shifts to a distinct tangent worth tracking separately, offer to create a Side Quest:

```
branch_quest(name="<tangent name>", description="<what this is about>")
```

**Important:** Always offer this — never create a Side Quest without the user's agreement. Say something like: "This seems like a separate topic from what we've been discussing. Want me to branch this into its own Side Quest so we can track it separately?"

## Completing Quests

When a project or workstream wraps up, mark it complete:

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
```

**File: `plugin/skills/status/SKILL.md`** (NEW)

```markdown
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
diff_since(since_session_id="<previous session id>")
```

This returns nodes created, updated, or deprecated since the previous session — useful for catching up on changes made in other conversations or by other team members.

## Cross-project insights

Search for relevant patterns across all projects:

```
analogical_search(query="<what you're looking for>")
```

This finds similar decisions, constraints, and patterns from other Quests — useful when starting something new that resembles past work.
```

### Phase 3: README

**File: `plugin/README.md`** (NEW)

```markdown
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
```

### Phase 4: Update installer

**File: `sidequests/cli/install.py`** — modify `_register_claude_desktop()`

The installer should now reference the plugin for Claude Desktop users:

```python
def _register_claude_desktop(self) -> bool:
    """Register Claude Desktop via plugin directory."""
    plugin_dir = PROJECT_ROOT / "plugin"
    if not plugin_dir.exists():
        click.echo("    [!] Plugin directory not found at plugin/")
        return False

    click.echo("    [ok] Claude Desktop — SideQuests plugin ready")
    click.echo("")
    click.echo("    To install the plugin:")
    click.echo(f"      1. Open Claude Desktop → Cowork tab")
    click.echo(f"      2. Click 'Customize' → upload plugin folder:")
    click.echo(f"         {plugin_dir}")
    click.echo(f"      3. Or via CLI: claude plugins add {plugin_dir}")
    click.echo("")
    return True
```

Also keep the existing `_merge_mcp_config` approach as a fallback for users who don't use Cowork — both paths should work.

### Phase 5: Tests

**File: `tests/test_plugin.py`** (NEW)

```python
"""
Tests for B2 Cowork Plugin structure and content.

Validates the plugin directory structure, manifest schema, MCP config,
and skill file presence — ensuring the plugin is installable.
"""

import json
import pytest
from pathlib import Path

PLUGIN_DIR = Path(__file__).parent.parent / "plugin"


def test_plugin_directory_exists():
    """Plugin directory exists at repo root."""
    assert PLUGIN_DIR.exists(), f"Plugin directory not found at {PLUGIN_DIR}"
    assert PLUGIN_DIR.is_dir()


def test_plugin_manifest_exists():
    """plugin.json manifest exists."""
    manifest = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
    assert manifest.exists(), "Missing .claude-plugin/plugin.json"


def test_plugin_manifest_valid_json():
    """plugin.json is valid JSON with required fields."""
    manifest = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
    data = json.loads(manifest.read_text())
    assert "name" in data
    assert "version" in data
    assert "description" in data
    assert data["name"] == "sidequests-brain"


def test_plugin_manifest_has_author():
    """plugin.json has author field."""
    manifest = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
    data = json.loads(manifest.read_text())
    assert "author" in data
    assert "name" in data["author"]


def test_mcp_json_exists():
    """.mcp.json exists in plugin root."""
    mcp = PLUGIN_DIR / ".mcp.json"
    assert mcp.exists(), "Missing .mcp.json"


def test_mcp_json_valid():
    """.mcp.json is valid JSON with sidequests-brain server."""
    mcp = PLUGIN_DIR / ".mcp.json"
    data = json.loads(mcp.read_text())
    assert "mcpServers" in data
    assert "sidequests-brain" in data["mcpServers"]
    server = data["mcpServers"]["sidequests-brain"]
    assert "url" in server
    assert "127.0.0.1" in server["url"]
    assert "7799" in server["url"]


def test_mcp_json_uses_sse_endpoint():
    """.mcp.json points to the SSE endpoint."""
    mcp = PLUGIN_DIR / ".mcp.json"
    data = json.loads(mcp.read_text())
    url = data["mcpServers"]["sidequests-brain"]["url"]
    assert url.endswith("/sse"), f"Expected SSE endpoint, got {url}"


def test_skills_directory_exists():
    """skills/ directory exists."""
    skills = PLUGIN_DIR / "skills"
    assert skills.exists()
    assert skills.is_dir()


EXPECTED_SKILLS = [
    "memory-awareness",
    "recall",
    "quest-management",
    "status",
]


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_skill_directory_exists(skill_name):
    """Each expected skill has a directory."""
    skill_dir = PLUGIN_DIR / "skills" / skill_name
    assert skill_dir.exists(), f"Missing skill directory: {skill_name}"


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_skill_has_skill_md(skill_name):
    """Each skill directory contains SKILL.md."""
    skill_file = PLUGIN_DIR / "skills" / skill_name / "SKILL.md"
    assert skill_file.exists(), f"Missing SKILL.md in {skill_name}"


@pytest.mark.parametrize("skill_name", EXPECTED_SKILLS)
def test_skill_md_not_empty(skill_name):
    """Each SKILL.md has meaningful content (>100 chars)."""
    skill_file = PLUGIN_DIR / "skills" / skill_name / "SKILL.md"
    content = skill_file.read_text()
    assert len(content) > 100, f"SKILL.md in {skill_name} is too short ({len(content)} chars)"


def test_skill_memory_awareness_mentions_notify_turn():
    """memory-awareness skill teaches Claude about notify_turn."""
    content = (PLUGIN_DIR / "skills" / "memory-awareness" / "SKILL.md").read_text()
    assert "notify_turn" in content


def test_skill_recall_mentions_current_truth():
    """recall skill teaches Claude about current_truth."""
    content = (PLUGIN_DIR / "skills" / "recall" / "SKILL.md").read_text()
    assert "current_truth" in content


def test_skill_quest_management_mentions_branch_quest():
    """quest-management skill teaches Claude about branch_quest."""
    content = (PLUGIN_DIR / "skills" / "quest-management" / "SKILL.md").read_text()
    assert "branch_quest" in content


def test_skill_status_mentions_context_status():
    """status skill teaches Claude about context_status."""
    content = (PLUGIN_DIR / "skills" / "status" / "SKILL.md").read_text()
    assert "context_status" in content


def test_readme_exists():
    """README.md exists in plugin root."""
    readme = PLUGIN_DIR / "README.md"
    assert readme.exists()


def test_readme_mentions_install():
    """README has installation instructions."""
    content = (PLUGIN_DIR / "README.md").read_text()
    assert "install" in content.lower()
    assert "sidequests" in content.lower()
```

## Files to Create

| File | Description |
|------|-------------|
| `plugin/.claude-plugin/plugin.json` | Plugin manifest |
| `plugin/.mcp.json` | MCP server config (SSE endpoint) |
| `plugin/skills/memory-awareness/SKILL.md` | How the Brain captures knowledge |
| `plugin/skills/recall/SKILL.md` | When/how to call current_truth |
| `plugin/skills/quest-management/SKILL.md` | Quest lifecycle management |
| `plugin/skills/status/SKILL.md` | Context health and open loops |
| `plugin/README.md` | Installation and usage guide |
| `tests/test_plugin.py` | Plugin structure validation tests |

## Files to Modify

| File | Change |
|------|--------|
| `sidequests/cli/install.py` | Update `_register_claude_desktop()` to reference plugin |

## Files to Read First

| File | Why |
|------|-----|
| `web/server.py` | Verify SSE endpoint URL (lines 619-655) |
| `mcp_engine/tool_schemas.py` | Tool names and descriptions for skill accuracy |
| `sidequests/cli/install.py` | Current `_register_claude_desktop()` implementation |
| `adapters/claude_desktop/adapter.py` | Current stub (stays as-is) |

## Verification

1. `python3 -m pytest tests/test_plugin.py -v` — all plugin structure tests pass
2. `python3 -m pytest tests/ -v` — full suite, 0 failures
3. `plugin/.claude-plugin/plugin.json` is valid JSON
4. `plugin/.mcp.json` points to `http://127.0.0.1:7799/sse`
5. All 4 skill SKILL.md files mention their primary tool
6. README has clear installation instructions
