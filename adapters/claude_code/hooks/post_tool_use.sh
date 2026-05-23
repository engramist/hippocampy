#!/usr/bin/env bash
# Claude Code PostToolUse hook — Campy Error Pattern Matching (Phase 2)
#
# Reads the trigger manifest and matches tool output against error patterns.
# When a match is found, injects the relevant lesson/procedure as context.
#
# Environment variables from Claude Code:
#   CLAUDE_TOOL_NAME — the tool that just ran
#
# Tool output is read from stdin.

set -euo pipefail

TOOL_NAME="${CLAUDE_TOOL_NAME:-}"
MANIFEST="${CAMPY_TRIGGER_MANIFEST:-$HOME/.campy/triggers/manifest.json}"

# Fast exit if no manifest exists
[ -f "$MANIFEST" ] || exit 0

# Read tool output from stdin
TOOL_OUTPUT="$(cat)"

# Fast exit if no output to match against
[ -n "$TOOL_OUTPUT" ] || exit 0

# Use Python for reliable JSON parsing + regex matching
python3 - "$TOOL_NAME" "$TOOL_OUTPUT" "$MANIFEST" <<'PYEOF'
import json, re, sys, os

tool_name = sys.argv[1]
tool_output = sys.argv[2]
manifest_path = sys.argv[3]

try:
    with open(manifest_path) as f:
        manifest = json.load(f)
except (OSError, json.JSONDecodeError):
    sys.exit(0)

cwd = os.getcwd()
matched = []

for trigger in manifest.get("triggers", []):
    # Only PostToolUse triggers
    if trigger.get("hook_type") != "PostToolUse":
        continue
    # Filter by tool (empty = match all tools)
    trigger_tool = trigger.get("tool", "")
    if trigger_tool and trigger_tool != tool_name:
        continue
    # Filter by project scope (empty = match all projects)
    scope = trigger.get("project_scope", "")
    if scope and not cwd.startswith(scope):
        continue
    # Match pattern against tool output
    pattern = trigger.get("pattern", "")
    if not pattern:
        continue
    try:
        if re.search(pattern, tool_output, re.IGNORECASE):
            matched.append(trigger)
    except re.error:
        continue

# Cap at 3 matches to protect context window budget
for t in matched[:3]:
    name = t.get("name", "Memory")
    snippet = t.get("context_snippet", "")
    if snippet:
        print(f"[Campy Memory — {name}]")
        print(snippet)
        print()
PYEOF
