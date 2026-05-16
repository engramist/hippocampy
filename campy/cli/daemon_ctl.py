"""
sidequests/cli/daemon_ctl.py — Daemon start / stop helpers.
"""

from __future__ import annotations
import platform
import sys


def start_daemon() -> None:
    """
    Start the Brain Daemon in the foreground.
    Useful for debugging; production uses launchd (macOS) or systemd (Linux).
    """
    # Add project root to sys.path so brain_daemon imports work
    from pathlib import Path
    project_root = Path(__file__).parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    import asyncio
    import brain_daemon
    asyncio.run(brain_daemon.main())


def stop_daemon() -> None:
    """Stop the daemon via the platform service manager."""
    system = platform.system()

    if system == "Darwin":
        from campy.cli.launchd import unload_plist, is_loaded
        if is_loaded():
            if unload_plist():
                print("Brain Daemon stopped.")
            else:
                print("Failed to stop Brain Daemon. Check ~/Library/LaunchAgents/.")
        else:
            print("Brain Daemon is not running.")

    elif system == "Linux":
        import subprocess
        result = subprocess.run(
            ["systemctl", "--user", "stop", "hippocampy"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("Brain Daemon stopped.")
        else:
            print(f"Failed to stop: {result.stderr.strip()}")

    else:
        print(f"stop not supported on {system}. Kill the process manually.")


def daemon_status() -> bool:
    """Return True if the daemon is running."""
    system = platform.system()
    if system == "Darwin":
        from campy.cli.launchd import is_loaded
        return is_loaded()
    elif system == "Linux":
        import subprocess
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "hippocampy"],
            capture_output=True, text=True
        )
        return result.returncode == 0
    return False
