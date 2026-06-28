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

# B290: WorkArtifact — auto-capture when agent writes/edits a *.md file.
# CLAUDE_TOOL_NAME is set by Claude Code for every PostToolUse call.
if [ "${CLAUDE_TOOL_NAME:-}" = "Write" ] || [ "${CLAUDE_TOOL_NAME:-}" = "Edit" ]; then
    # Extract file path from tool output (last line often contains the path)
    FILE_PATH=$(echo "$TOOL_OUTPUT" | grep -o '[^ ]*\.md' | head -1)
    if [ -n "$FILE_PATH" ] && [ -f "$FILE_PATH" ]; then
        # Extract title (first # heading) and summary (first non-heading line > 20 chars)
        TITLE=$(grep -m1 "^# " "$FILE_PATH" 2>/dev/null | sed 's/^# //')
        SUMMARY=$(grep -v "^#" "$FILE_PATH" 2>/dev/null | grep -v "^$" | awk 'length > 20 {print; exit}' | cut -c1-120)
        # Infer session from env (Claude Code sets CLAUDE_SESSION_ID)
        SESSION="${CLAUDE_SESSION_ID:-unknown}"

        python3 - "$FILE_PATH" "$TITLE" "$SUMMARY" "$SESSION" <<'ARTIFACT_EOF'
import sys, json, os
try:
    from campy.brain_transport import call_brain
    import asyncio
    file_path, title, summary, session_id = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    # Make path repo-relative
    try:
        import subprocess
        repo_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL, timeout=3
        ).decode().strip()
        if file_path.startswith("/"):
            rel = os.path.relpath(file_path, repo_root)
        else:
            rel = file_path
    except Exception:
        rel = file_path
    params = {
        "file_path": rel,
        "title": title,
        "summary": summary,
        "session_id": session_id,
        "agent_source": "claude_code",
    }
    asyncio.run(call_brain("register_artifact", params, timeout=3.0))
except Exception:
    pass  # Never block the agent
ARTIFACT_EOF
    fi
fi
