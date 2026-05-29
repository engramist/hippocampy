#!/usr/bin/env python3
"""Codex CLI UserPromptSubmit hook — passive turn notification.

Codex sends JSON on stdin with session metadata.
Forwards user turn to Brain Daemon socket. Zero LLM involvement.
Output {} (no-op JSON) to stdout.
"""
import asyncio
import json
import sys
import uuid
from pathlib import Path


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        json.dump({}, sys.stdout)
        return

    session_id = payload.get("session_id", str(uuid.uuid4()))
    content = payload.get("prompt", payload.get("user_prompt", ""))

    if not content.strip():
        json.dump({}, sys.stdout)
        return

    params = {"role": "user", "content": content, "session_id": session_id}

    try:
        from campy.brain_transport import call_brain
        asyncio.run(call_brain("notify_turn", params))
    except Exception:
        # Daemon offline — queue for replay
        from campy.paths import runtime_dir
        offline_queue = runtime_dir() / "offline_queue.jsonl"
        offline_queue.parent.mkdir(parents=True, exist_ok=True)
        with open(offline_queue, "a") as f:
            f.write(json.dumps({
                "method": "notify_turn",
                "params": params,
            }) + "\n")

    json.dump({}, sys.stdout)


if __name__ == "__main__":
    main()
