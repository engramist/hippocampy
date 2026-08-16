#!/usr/bin/env bash
# Claude Code SessionStart hook wrapper.
#
# B318 fail-open: bounded by `timeout 4` (~CONTEXT_TIMEOUT 3.0s + overhead —
# see the timeout table in campy/brain_transport.py; keep these two in
# sync). Always exits 0 so a stalled daemon can never block session start.
# No `set -e`/`exec` here on purpose — we need to reach the trailing
# `exit 0` even if `timeout` reports non-zero.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
timeout 4 python3 "$SCRIPT_DIR/session_start_wrapper.py" --plain
exit 0
