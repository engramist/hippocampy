"""Helpers for piggybacking Claude Code auto-memory writes into Campy."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


_MEMORY_PATH_RE = re.compile(r".*/\.claude/projects/.*/memory/[^/]+\.md$")


def is_claude_memory_file(file_path: str) -> bool:
    return bool(_MEMORY_PATH_RE.match(file_path))


def should_capture_memory_file(file_path: str) -> bool:
    path = Path(file_path)
    if path.name == "MEMORY.md":
        return False
    return is_claude_memory_file(file_path)


def parse_memory_markdown(file_path: str) -> dict | None:
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return None

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    if len(lines) < 3 or lines[0].strip() != "---":
        return None

    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return None

    frontmatter_lines = lines[1:end_idx]
    body_lines = lines[end_idx + 1 :]

    fm_name = ""
    fm_description = ""
    fm_type = ""
    in_metadata = False

    for raw in frontmatter_lines:
        line = raw.rstrip("\n")
        if line.strip().startswith("metadata:"):
            in_metadata = True
            continue
        if in_metadata and line.startswith("  ") and ":" in line:
            key, value = line.strip().split(":", 1)
            if key.strip() == "type":
                fm_type = value.strip().strip('"\'')
            continue
        in_metadata = False
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"\'')
        if key == "name":
            fm_name = value
        elif key == "description":
            fm_description = value

    body = "\n".join(body_lines).strip()
    if not fm_name:
        return None

    return {
        "name": fm_name,
        "description": fm_description,
        "memory_type": fm_type or "unknown",
        "body": body,
    }


def _stable_memory_key(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]


def build_notify_turn_payload(memory: dict, session_id: str) -> dict:
    memory_name = memory["name"]
    memory_description = memory.get("description", "")
    memory_type = memory.get("memory_type", "unknown")
    memory_body = memory.get("body", "")

    structured_content = (
        "[source: claude_auto_memory]\n"
        "[format: claude_memory]\n"
        f"name: {memory_name}\n"
        f"description: {memory_description}\n"
        f"source_memory_class: {memory_type}\n"
        f"memory_key: {_stable_memory_key(memory_name)}\n"
        "body:\n"
        f"{memory_body}"
    )

    return {
        "role": "system",
        "content": structured_content,
        "session_id": session_id,
        "source": "claude_auto_memory",
        "source_memory_class": memory_type,
        "source_memory_name": memory_name,
        "source_memory_key": _stable_memory_key(memory_name),
    }
