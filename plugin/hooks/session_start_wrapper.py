#!/usr/bin/env python3
"""Shared SessionStart hook wrapper for Campy plugin integrations."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from campy_hook import DEFAULT_SESSION_MESSAGE, check_daemon_health

# B318: session start / context injection budget — see the timeout table in
# campy/brain_transport.py (CONTEXT_TIMEOUT). This hook fires once per
# session so some latency is tolerable, but campy_hook.get_session_context()
# bounds its subprocess at 10s, well over budget; that number belongs to
# campy_hook.py (outside this card's file list), so the SessionStart hook
# reimplements the same call here with the correct bound instead.
_CONTEXT_TIMEOUT = 3.0


def _bounded_session_context() -> str:
    """Fetch session-start prompt context, bounded by _CONTEXT_TIMEOUT.

    Fail-open: any failure (missing CLI, timeout, non-zero exit) degrades to
    an empty string rather than raising or blocking the SessionStart hook.
    """
    campy_cmd = shutil.which("campy")
    command = (
        [campy_cmd, "decide", "new session starting", "--format=prompt"]
        if campy_cmd
        else [sys.executable, "-m", "campy.cli.main", "decide", "new session starting", "--format=prompt"]
    )
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=_CONTEXT_TIMEOUT
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _emit(message: str, mode: str) -> None:
    if mode == "gemini":
        json.dump({"output": {"metadata": {"message": message}}}, sys.stdout)
    else:
        print(message)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--plain", action="store_true")
    parser.add_argument("--gemini", action="store_true")
    args = parser.parse_args()

    mode = "gemini" if args.gemini else "plain" if args.plain else "codex"
    if not check_daemon_health():
        _emit("Note: Campy memory daemon is not running. Start with: campy start", mode)
        return 0

    context = _bounded_session_context() or DEFAULT_SESSION_MESSAGE
    _emit(context, mode)
    return 0


if __name__ == "__main__":
    # B318: non-zero-exit tolerance — a SessionStart hook must never block
    # the agent, so any unexpected failure degrades to a plain fallback
    # message and exit 0 rather than propagating a traceback/exit code.
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        print(DEFAULT_SESSION_MESSAGE)
        raise SystemExit(0)