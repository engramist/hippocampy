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

import json
import socket
import sys
import uuid
from pathlib import Path

SOCKET_PATH   = Path.home() / ".sidequests" / "brain.sock"
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

    request = json.dumps({
        "jsonrpc": "2.0",
        "id":      str(uuid.uuid4()),
        "method":  "notify_turn",
        "params":  {"role": "user", "content": content, "session_id": session_id},
    }) + "\n"

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(SOCKET_PATH))
        sock.sendall(request.encode())
        sock.recv(4096)  # read and discard response
        sock.close()
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        # Daemon offline — queue for replay
        OFFLINE_QUEUE.parent.mkdir(parents=True, exist_ok=True)
        with open(OFFLINE_QUEUE, "a") as f:
            f.write(json.dumps({
                "method": "notify_turn",
                "params": {"role": "user", "content": content, "session_id": session_id}
            }) + "\n")


if __name__ == "__main__":
    main()
