#!/usr/bin/env python3
"""Shared PreToolUse hook wrapper for Campy plugin integrations."""

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
        return {}


def _content_from(value) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value or {})


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
    tool_name = payload.get("tool_name") or payload.get("functionCall", {}).get("name") or os.environ.get("CLAUDE_TOOL_NAME", "")
    tool_input = payload.get("tool_input", payload.get("functionCall", {}).get("args", {}))
    if not payload and os.environ.get("CLAUDE_TOOL_INPUT"):
        tool_input = os.environ.get("CLAUDE_TOOL_INPUT", "")

    content = _content_from(tool_input)
    if not content:
        _emit("", mode)
        return 0

    manifest = load_manifest()
    matches = match_triggers(manifest, "PreToolUse", tool_name, content)
    _emit(format_context_snippets(matches), mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())