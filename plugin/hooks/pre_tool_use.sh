#!/usr/bin/env bash
# Claude Code PreToolUse hook wrapper.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/pre_tool_use_wrapper.py" --plain
