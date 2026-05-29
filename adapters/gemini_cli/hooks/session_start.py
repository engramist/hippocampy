#!/usr/bin/env python3
"""Gemini CLI SessionStart hook — injects Campy memory context.

Gemini sends JSON on stdin with session metadata.
Output JSON to stdout: {"output": {"metadata": {"message": "..."}}} or {} for no-op.
All debug/error output MUST go to stderr.
"""
import json
import subprocess
import sys
import shutil


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        payload = {}

    # Find campy CLI
    campy_cmd = shutil.which("campy")

    # Check daemon health
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:7799/health", method="GET")
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        print("Note: Campy daemon not running", file=sys.stderr)
        json.dump({"output": {"metadata": {"message": "Note: Campy memory daemon is not running. Start with: campy start"}}}, sys.stdout)
        return

    # Get memory context for session start
    try:
        cmd = [campy_cmd, "decide", "new session starting", "--format=prompt"] if campy_cmd else [
            sys.executable, "-m", "campy.cli.main", "decide", "new session starting", "--format=prompt"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        context = result.stdout.strip()
    except Exception as e:
        print(f"Campy decide failed: {e}", file=sys.stderr)
        context = ""

    if context:
        json.dump({"output": {"metadata": {"message": context}}}, sys.stdout)
    else:
        json.dump({"output": {"metadata": {"message": "Campy memory is available. Use memory_decision to check what the Brain knows before starting work."}}}, sys.stdout)


if __name__ == "__main__":
    main()
