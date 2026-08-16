"""
adapters/claude_code/hook_user_turn.py — UserPromptSubmit Hook

Called by Claude Code's UserPromptSubmit hook on every user message.
Receives hook payload on stdin, forwards user turn to Brain Daemon socket.
Zero LLM involvement — truly passive for user turns.

Claude Code hook payload (stdin, JSON):
  {"session_id": "...", "prompt": "user message text", ...}

Registered in ~/.claude/settings.json by `campy setup`:
  "UserPromptSubmit": [{"matcher": "", "hooks": [{"type": "command",
    "command": "python /path/to/hook_user_turn.py"}]}]
"""

import asyncio
import json
import sys
import uuid
from pathlib import Path
from campy.brain_transport import CAPTURE_TIMEOUT, call_brain_soft
from campy.paths import get_daemon_socket_path, runtime_dir

OFFLINE_QUEUE = runtime_dir() / "offline_queue.jsonl"


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)  # silently skip malformed hook calls

    session_id = payload.get("session_id", str(uuid.uuid4()))
    content    = payload.get("prompt", "")

    if not content.strip():
        sys.exit(0)

    import os
    import subprocess

    repo_root = ""
    git_branch = "main"
    try:
        repo_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL, timeout=3,
        ).decode().strip()
        git_branch = subprocess.check_output(
            ["git", "branch", "--show-current"],
            stderr=subprocess.DEVNULL, timeout=3,
        ).decode().strip()
    except Exception:
        pass

    params = {
        "role": "user",
        "content": content,
        "session_id": session_id,
        "agent_source": "claude_code",
        "repo_root": repo_root,
        "git_branch": git_branch,
    }

    # B318: fail-open — a UserPromptSubmit hook must never block the agent
    # on a slow/unreachable daemon. call_brain_soft() degrades to the
    # sentinel below on any failure instead of raising; CAPTURE_TIMEOUT is
    # the write-path budget (see campy/brain_transport.py timeout table).
    _SOFT_FAIL = object()
    result = asyncio.run(
        call_brain_soft("notify_turn", params, timeout=CAPTURE_TIMEOUT, default=_SOFT_FAIL)
    )
    if result is _SOFT_FAIL:
        # Daemon offline/slow/erroring — queue for replay
        OFFLINE_QUEUE.parent.mkdir(parents=True, exist_ok=True)
        with open(OFFLINE_QUEUE, "a") as f:
            f.write(json.dumps({
                "method": "notify_turn",
                "params": params,
            }) + "\n")


if __name__ == "__main__":
    main()
