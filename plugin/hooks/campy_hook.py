#!/usr/bin/env python3
"""Shared hook logic for Campy plugin integrations."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

MANIFEST_PATH = Path.home() / ".campy" / "triggers" / "manifest.json"
MAX_MATCHES = 3
DEFAULT_SESSION_MESSAGE = (
    "Campy memory is available. Use memory_decision to check what the Brain knows "
    "before starting work."
)


def load_manifest() -> list[dict]:
    """Load trigger manifest entries from disk."""
    path = Path(os.environ.get("CAMPY_TRIGGER_MANIFEST", str(MANIFEST_PATH))).expanduser()
    if not path.exists():
        return []

    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []

    if isinstance(raw, dict):
        triggers = raw.get("triggers", [])
        return [item for item in triggers if isinstance(item, dict)]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def match_triggers(
    manifest: list[dict],
    hook_type: str,
    tool_name: str = "",
    content: str = "",
    cwd: str | None = None,
) -> list[dict]:
    """Return matching trigger entries for the hook event."""
    current_dir = cwd or os.getcwd()
    matches: list[dict] = []

    for trigger in manifest:
        if trigger.get("hook_type") != hook_type:
            continue

        trigger_tool = trigger.get("tool") or trigger.get("tool_name") or ""
        if trigger_tool and trigger_tool != tool_name:
            continue

        scope = trigger.get("project_scope", "")
        if scope and not current_dir.startswith(scope):
            continue

        pattern = trigger.get("pattern", "")
        if not pattern:
            continue

        try:
            if re.search(pattern, content, re.IGNORECASE):
                matches.append(trigger)
        except re.error:
            continue

        if len(matches) >= MAX_MATCHES:
            break

    return matches


def format_context_snippets(matches: list[dict]) -> str:
    """Format matching triggers into prompt-injection text."""
    parts: list[str] = []
    for match in matches[:MAX_MATCHES]:
        name = match.get("name", "Memory")
        node_type = match.get("node_type", "Campy Memory")
        snippet = match.get("context_snippet") or match.get("snippet") or ""
        if not snippet:
            continue
        parts.append(f"[Campy Memory — {node_type}: {name}]\n{snippet}")
    return "\n\n".join(parts)


def get_session_context() -> str:
    """Fetch session-start prompt context from the Campy CLI."""
    campy_cmd = shutil.which("campy")
    command = [campy_cmd, "decide", "new session starting", "--format=prompt"] if campy_cmd else [
        sys.executable,
        "-m",
        "campy.cli.main",
        "decide",
        "new session starting",
        "--format=prompt",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def check_daemon_health() -> bool:
    """Return True when the local Campy daemon health endpoint responds."""
    try:
        request = urllib.request.Request("http://127.0.0.1:7799/health", method="GET")
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.getcode() == 200
    except Exception:
        return False