#!/usr/bin/env python3
"""Codex CLI PostToolUse hook — Campy Error Pattern Matching.

Codex sends JSON on stdin: {tool_name, tool_input, tool_response, ...}
Output JSON to stdout: {systemMessage: "..."} or {} for no-op.
"""
import json
import os
import re
import sys


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        json.dump({}, sys.stdout)
        return

    tool_name = payload.get("tool_name", "")
    tool_response = str(payload.get("tool_response", ""))

    manifest_path = os.environ.get(
        "CAMPY_TRIGGER_MANIFEST",
        os.path.expanduser("~/.campy/triggers/manifest.json"),
    )

    if not os.path.isfile(manifest_path) or not tool_response:
        json.dump({}, sys.stdout)
        return

    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError):
        json.dump({}, sys.stdout)
        return

    cwd = os.getcwd()
    matched = []

    for trigger in manifest.get("triggers", []):
        if trigger.get("hook_type") != "PostToolUse":
            continue
        trigger_tool = trigger.get("tool", "")
        if trigger_tool and trigger_tool != tool_name:
            continue
        scope = trigger.get("project_scope", "")
        if scope and not cwd.startswith(scope):
            continue
        pattern = trigger.get("pattern", "")
        if not pattern:
            continue
        try:
            if re.search(pattern, tool_response, re.IGNORECASE):
                matched.append(trigger)
        except re.error:
            continue

    if not matched:
        json.dump({}, sys.stdout)
        return

    # Cap at 3 matches
    snippets = []
    for t in matched[:3]:
        name = t.get("name", "Memory")
        snippet = t.get("context_snippet", "")
        if snippet:
            snippets.append(f"[Campy Memory — {name}]\n{snippet}")

    if snippets:
        json.dump({"systemMessage": "\n\n".join(snippets)}, sys.stdout)
    else:
        json.dump({}, sys.stdout)


if __name__ == "__main__":
    main()
