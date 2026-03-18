"""
sidequests/cli/launchd.py — macOS launchd plist generation and control.

Manages the Brain Daemon as a launchd user agent so it starts automatically
at login and stays running.

Label: ai.sidequests.brain
Plist: ~/Library/LaunchAgents/ai.sidequests.brain.plist
"""

from __future__ import annotations
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL      = "ai.sidequests.brain"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_PATH   = Path.home() / ".sidequests" / "daemon.log"


def _daemon_script() -> str:
    """Return absolute path to the Brain Daemon entry point."""
    # Prefer installed sidequests-daemon script; fall back to brain_daemon.py
    import shutil
    daemon_script = shutil.which("sidequests-daemon")
    if daemon_script:
        return daemon_script
    # Dev install: find brain_daemon.py relative to this file
    return str(Path(__file__).parent.parent.parent / "brain_daemon.py")


def write_plist() -> Path:
    """
    Write ~/Library/LaunchAgents/ai.sidequests.brain.plist.

    Configures Brain Daemon as a launchd user agent:
    - Starts at login (RunAtLoad: true)
    - Restarts on crash (KeepAlive: true)
    - Logs stdout + stderr to ~/.sidequests/daemon.log
    """
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    daemon = _daemon_script()
    # If it's a Python script, run it with the current interpreter
    if daemon.endswith(".py"):
        program_args = [sys.executable, daemon]
    else:
        program_args = [daemon]

    plist_data = {
        "Label":                LABEL,
        "ProgramArguments":     program_args,
        "RunAtLoad":            True,
        "KeepAlive":            True,
        "StandardOutPath":      str(LOG_PATH),
        "StandardErrorPath":    str(LOG_PATH),
        "WorkingDirectory":     str(Path.home()),
    }

    with open(PLIST_PATH, "wb") as f:
        plistlib.dump(plist_data, f)

    return PLIST_PATH


def load_plist() -> bool:
    """
    Load the plist with launchctl. Returns True on success.
    Safe to call if already loaded (launchctl prints a warning but exits 0).
    """
    if not PLIST_PATH.exists():
        return False
    result = subprocess.run(
        ["launchctl", "load", str(PLIST_PATH)],
        capture_output=True, text=True
    )
    return result.returncode == 0


def unload_plist() -> bool:
    """Unload the plist with launchctl. Returns True on success."""
    if not PLIST_PATH.exists():
        return False
    result = subprocess.run(
        ["launchctl", "unload", str(PLIST_PATH)],
        capture_output=True, text=True
    )
    return result.returncode == 0


def is_loaded() -> bool:
    """Return True if the ai.sidequests.brain agent is loaded in launchctl."""
    result = subprocess.run(
        ["launchctl", "list", LABEL],
        capture_output=True, text=True
    )
    return result.returncode == 0
