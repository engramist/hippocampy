#!/usr/bin/env python3
"""Shared SessionEnd hook wrapper for Campy plugin integrations (B440).

Confirmed via Claude Code's official Hooks Reference (code.claude.com/
docs/en/hooks.md, 2026-09-22): SessionEnd is a real, documented hook
event, distinct from a self-hosted runner's separate `post-session`
lifecycle hook. Stdin payload includes `session_id` and `cwd`, matching
the shape PreToolUse/PostToolUse already read via _read_payload().

Writes a handoff markdown file (HANDOFF.md, at the project root --
`cwd` from the hook payload) via `campy handoff`, so a developer
switching to a different model for their next session has it ready
without needing to remember to generate it manually. Deliberately a
separate file from CONTEXT.md: CONTEXT.md's "## Current Work" section
(B290/work_summary.py) is a different, narrower, continuously-updated
resume line; HANDOFF.md is the richer, on-demand artifact CLI users
already get via `campy handoff --out HANDOFF.md`, so writing to the
same path here keeps both entry points consistent.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from campy_hook import check_daemon_health

# Session end is a one-shot event, not per-tool-call, so a more generous
# budget than PreToolUse/PostToolUse's near-zero tolerance is fine -- but
# this must still never block the actual session exit, hence the fail-open
# wrapper around main() below and a hard subprocess timeout here.
_HANDOFF_TIMEOUT = 10.0


def _read_payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _generate_handoff(session_id: str, cwd: str) -> bool:
    """Write HANDOFF.md at `cwd` via `campy handoff`. Fail-open: any
    failure (missing CLI, daemon down, timeout) is silently swallowed --
    a SessionEnd hook must never block session exit or raise. Returns
    True only on a confirmed successful write."""
    if not cwd:
        return False
    out_path = str(Path(cwd) / "HANDOFF.md")
    campy_cmd = shutil.which("campy")
    base = [campy_cmd] if campy_cmd else [sys.executable, "-m", "campy.cli.main"]
    command = base + ["handoff", "--out", out_path]
    if session_id:
        command += ["--session-id", session_id]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=_HANDOFF_TIMEOUT
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    except Exception:
        return False
    return result.returncode == 0


def main() -> int:
    if not check_daemon_health():
        return 0

    payload = _read_payload()
    session_id = payload.get("session_id", "")
    cwd = payload.get("cwd", "")

    _generate_handoff(session_id, cwd)
    return 0


if __name__ == "__main__":
    # B318 convention (same as every other hook wrapper in this
    # directory): a hook must never block or fail the event it's
    # attached to, so any unexpected failure degrades to a silent no-op
    # and exit 0 rather than propagating a traceback/non-zero exit code.
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(0)
