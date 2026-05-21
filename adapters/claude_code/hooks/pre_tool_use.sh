#!/usr/bin/env bash
# Claude Code PreToolUse hook — reminds about memory before architecture changes
#
# This hook fires before Read/Edit/Write tool calls.
# Claude Code passes the tool name and arguments as environment variables:
#   CLAUDE_TOOL_NAME — the tool being called (Read, Edit, Write, etc.)
#   CLAUDE_TOOL_INPUT — JSON string of tool arguments
#
# Only outputs a reminder for architecture-related file operations.

set -euo pipefail

TOOL_NAME="${CLAUDE_TOOL_NAME:-}"
TOOL_INPUT="${CLAUDE_TOOL_INPUT:-}"

# Only trigger for file-modifying tools
case "$TOOL_NAME" in
    Edit|Write)
        # Check if the file path matches architecture patterns
        if echo "$TOOL_INPUT" | grep -qiE '"file_path".*\b(architecture|ARCHITECTURE|design|schema|config)\b'; then
            echo "Reminder: Before modifying architecture files, check current_truth for existing constraints and decisions."
        fi
        ;;
    *)
        # No output for other tools (no-op)
        ;;
esac
