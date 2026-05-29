#!/usr/bin/env bash
# Claude Code PostToolUse hook wrapper.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/post_tool_use_wrapper.py" --plain
