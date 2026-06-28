#!/usr/bin/env bash
# Claude Code SessionStart hook — injects Campy memory context
# Installed by: campy install-plugin (B255) or adapters/claude_code/setup.py
#
# This hook runs at the start of every Claude Code session.
# It queries the Campy daemon for relevant context and outputs
# it as system prompt text that Claude Code injects into the conversation.

set -euo pipefail

# B290: Inject resume line from CONTEXT.md ## Current Work section.
# Fast path — no daemon required, reads a plain file.
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
CONTEXT_FILE="$REPO_ROOT/CONTEXT.md"
if [ -f "$CONTEXT_FILE" ]; then
    RESUME=$(grep -A 3 "^## Current Work" "$CONTEXT_FILE" 2>/dev/null \
      | grep "^\*\*Resume:\*\*" | sed 's/\*\*Resume:\*\* //')
    if [ -n "$RESUME" ]; then
        # Validate branch still exists (BSD-compatible — no grep -P)
        BRANCH=$(echo "$RESUME" | sed -n 's/.*branch: \([^ ·)]*\).*/\1/p')
        if [ -n "$BRANCH" ] && ! git branch --list "$BRANCH" 2>/dev/null | grep -q "$BRANCH"; then
            RESUME="$RESUME (note: branch $BRANCH no longer exists — may have been merged)"
        fi
        echo "[Campy] $RESUME"
    fi
fi

# Check if campy CLI is available
if ! command -v campy &>/dev/null; then
    # Try the Python module path
    CAMPY_CMD="python3 -m campy.cli.main"
else
    CAMPY_CMD="campy"
fi

# Check if daemon is running (quick health check)
if ! curl -sf http://127.0.0.1:7799/health >/dev/null 2>&1; then
    # Daemon not running — output a minimal reminder
    echo "Note: Campy memory daemon is not running. Start with: campy start"
    exit 0
fi

# Get memory context for session start
# The --format=prompt flag outputs bare text suitable for prompt injection
CONTEXT=$($CAMPY_CMD decide "new session starting" --format=prompt 2>/dev/null || true)

if [ -n "$CONTEXT" ]; then
    echo "$CONTEXT"
else
    echo "Campy memory is available. Use memory_decision to check what the Brain knows before starting work."
fi
