#!/usr/bin/env bash
# Claude Code PostToolUse hook wrapper.
#
# B318 fail-open: bounded by `timeout 2` (~HOOK_TIMEOUT 1.0s + overhead —
# see the timeout table in campy/brain_transport.py; keep these two in
# sync). This hook makes no daemon calls itself, but it is time-boxed
# defensively and always exits 0 so a stalled environment can never block
# the agent's tool call. No `set -e`/`exec` here on purpose — we need to
# reach the trailing `exit 0` even if `timeout` reports non-zero.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
timeout 2 python3 "$SCRIPT_DIR/post_tool_use_wrapper.py" --plain
exit 0
