#!/usr/bin/env python3
"""Shared SessionStart hook wrapper for Campy plugin integrations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from campy_hook import DEFAULT_SESSION_MESSAGE, check_daemon_health, get_session_context


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

    context = get_session_context() or DEFAULT_SESSION_MESSAGE
    _emit(context, mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())