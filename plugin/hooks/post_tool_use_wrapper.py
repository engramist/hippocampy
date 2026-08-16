#!/usr/bin/env python3
"""Shared PostToolUse hook wrapper for Campy plugin integrations."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from campy_hook import format_context_snippets, load_manifest, match_triggers


def _read_payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"tool_response": raw}


def _emit(context: str, mode: str) -> None:
    if not context:
        if mode in {"codex", "gemini"}:
            json.dump({}, sys.stdout)
        return
    if mode == "plain":
        print(context)
    elif mode == "gemini":
        json.dump({"output": {"metadata": {"message": context}}}, sys.stdout)
    else:
        json.dump({"systemMessage": context}, sys.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--plain", action="store_true")
    parser.add_argument("--gemini", action="store_true")
    args = parser.parse_args()

    mode = "gemini" if args.gemini else "plain" if args.plain else "codex"
    payload = _read_payload()
    tool_name = payload.get("tool_name") or os.environ.get("CLAUDE_TOOL_NAME", "")
    content = payload.get("tool_response", payload.get("output", ""))
    if isinstance(content, dict):
        content = json.dumps(content)

    manifest = load_manifest()
    matches = match_triggers(manifest, "PostToolUse", tool_name, content)
    _emit(format_context_snippets(matches), mode)
    return 0


if __name__ == "__main__":
    # B318: non-zero-exit tolerance — a PostToolUse hook fires on every tool
    # call and must never block the agent, so any unexpected failure here
    # degrades to empty output and exit 0 rather than propagating a
    # traceback/non-zero exit code. This hook makes no daemon calls (pure
    # local trigger-manifest matching), so no timeout budget applies.
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(0)