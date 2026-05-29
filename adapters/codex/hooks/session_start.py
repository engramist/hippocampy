#!/usr/bin/env python3
"""Codex CLI SessionStart hook — injects Campy memory context.

Codex sends JSON on stdin with session metadata.
Output plain text to stdout — Codex adds it as system context.
"""
import json
import subprocess
import sys
import shutil


def main():
    # Read JSON payload from stdin (Codex provides session metadata)
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        payload = {}

    # Find campy CLI
    campy_cmd = shutil.which("campy")
    if not campy_cmd:
        campy_cmd = None  # will use python -m fallback

    # Check daemon health
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:7799/health", method="GET")
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        print("Note: Campy memory daemon is not running. Start with: campy start")
        return

    # Get memory context for session start
    try:
        cmd = [campy_cmd, "decide", "new session starting", "--format=prompt"] if campy_cmd else [
            sys.executable, "-m", "campy.cli.main", "decide", "new session starting", "--format=prompt"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        context = result.stdout.strip()
    except Exception:
        context = ""

    if context:
        print(context)
    else:
        print("Campy memory is available. Use memory_decision to check what the Brain knows before starting work.")


if __name__ == "__main__":
    main()
