"""
sidequests/cli/detect.py — Detect installed AI clients.

Checks for Claude Code, Claude Desktop, Codex, ChatGPT Desktop, and Gemini CLI
using platform-appropriate detection methods (which/where for CLI tools,
known app support directories for GUI apps).
"""

from __future__ import annotations
import platform
import shutil
from pathlib import Path


def detect_installed_clients() -> dict[str, bool]:
    """
    Detect which AI clients are installed on this machine.

    Returns a dict like:
      {
        "claude-code":      True,
        "claude-desktop":   False,
        "codex":            True,
        "chatgpt-desktop":  False,
        "gemini-cli":       False,
      }

    Detection methods:
      claude-code:     `which claude` succeeds (CLI tool in PATH)
      claude-desktop:  macOS: ~/Library/Application Support/Claude/ exists
                       Windows: %APPDATA%/Claude/ exists
      codex:           `which codex` succeeds
      chatgpt-desktop: macOS: ~/Library/Application Support/com.openai.chat/ exists
                       Windows: %APPDATA%/ChatGPT/ exists
      gemini-cli:      `which gemini` succeeds
    """
    system = platform.system()
    home = Path.home()

    clients: dict[str, bool] = {
        "claude-code":     False,
        "claude-desktop":  False,
        "codex":           False,
        "chatgpt-desktop": False,
        "gemini-cli":      False,
    }

    # CLI tools — check PATH
    clients["claude-code"] = shutil.which("claude") is not None
    clients["codex"]       = shutil.which("codex") is not None
    clients["gemini-cli"]  = shutil.which("gemini") is not None

    # GUI apps — check app support directories
    if system == "Darwin":
        clients["claude-desktop"] = (
            home / "Library" / "Application Support" / "Claude"
        ).exists()
        clients["chatgpt-desktop"] = (
            home / "Library" / "Application Support" / "com.openai.chat"
        ).exists()
    elif system == "Windows":
        appdata = Path.home() / "AppData" / "Roaming"
        clients["claude-desktop"]  = (appdata / "Claude").exists()
        clients["chatgpt-desktop"] = (appdata / "ChatGPT").exists()
    # Linux: GUI detection deferred (no standard location yet)

    return clients
