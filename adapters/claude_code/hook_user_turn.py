"""
adapters/claude_code/hook_user_turn.py — UserPromptSubmit Hook

Called by Claude Code's UserPromptSubmit hook on every user message.
Receives hook payload on stdin, forwards user turn to Brain Daemon socket.
Zero LLM involvement — truly passive for user turns.

Claude Code hook payload (stdin, JSON):
  {"session_id": "...", "prompt": "user message text", ...}

Registered in ~/.claude/settings.json by `sidequests setup`:
  "UserPromptSubmit": [{"matcher": "", "hooks": [{"type": "command",
    "command": "python /path/to/hook_user_turn.py"}]}]
"""

import asyncio
import json
import sys
import uuid
from pathlib import Path
from sidequests.brain_transport import call_brain

OFFLINE_QUEUE = Path.home() / ".sidequests" / "offline_queue.jsonl"


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)  # silently skip malformed hook calls

    session_id = payload.get("session_id", str(uuid.uuid4()))
    content    = payload.get("prompt", "")

    if not content.strip():
        sys.exit(0)

    params = {"role": "user", "content": content, "session_id": session_id}

    try:
        asyncio.run(call_brain("notify_turn", params))
    except RuntimeError:
        # Daemon offline — queue for replay
        OFFLINE_QUEUE.parent.mkdir(parents=True, exist_ok=True)
        with open(OFFLINE_QUEUE, "a") as f:
            f.write(json.dumps({
                "method": "notify_turn",
                "params": params,
            }) + "\n")


if __name__ == "__main__":
    main()
