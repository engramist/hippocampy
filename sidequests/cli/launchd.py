import os
import subprocess
import sys
import shutil
from pathlib import Path

LABEL = "ai.sidequests.brain"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_PATH = Path.home() / ".sidequests" / "daemon.log"

def resolve_system_python() -> str:
    """
    Find the Python interpreter launchd should use.

    Prefer the repository virtualenv so the daemon sees the same dependencies
    as the CLI/tests. Falling back to a bare system/Homebrew Python can miss
    runtime deps such as uvicorn.
    """
    repo_root = Path(__file__).parent.parent.parent
    venv_python = repo_root / ".venv" / "bin" / "python"
    if venv_python.exists():
        # Do not resolve the symlink: launchd must execute through the venv
        # path so Python initializes with the venv's site-packages.
        return str(venv_python)

    candidates = ["python3.12", "python3", "/usr/bin/python3"]
    for cmd in candidates:
        full_path = shutil.which(cmd)
        if full_path and "/.pyenv/shims/" not in full_path:
            return os.path.realpath(full_path)
    return os.path.realpath(sys.executable)

def _daemon_script() -> str:
    """Return absolute path to brain_daemon.py."""
    return str(Path(__file__).parent.parent.parent / "brain_daemon.py")

def is_loaded() -> bool:
    """Return True if the service is loaded in launchctl."""
    result = subprocess.run(
        ["launchctl", "list", LABEL],
        capture_output=True, text=True
    )
    return result.returncode == 0

def unload_plist() -> bool:
    """Unload the plist from launchctl."""
    if not PLIST_PATH.exists():
        return True
    result = subprocess.run(
        ["launchctl", "unload", str(PLIST_PATH)],
        capture_output=True, text=True
    )
    return result.returncode == 0

def load_plist() -> bool:
    """Load the plist into launchctl."""
    if not PLIST_PATH.exists():
        return False
    result = subprocess.run(
        ["launchctl", "load", str(PLIST_PATH)],
        capture_output=True, text=True
    )
    return result.returncode == 0

def generate_plist(brain_daemon_path: str, plist_path: str) -> bool:
    """Generate the launchd plist file for auto-start on macOS. Legacy signature for tests."""
    try:
        import sys
        python_exe = resolve_system_python()
        
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_exe}</string>
        <string>{brain_daemon_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{LOG_PATH}</string>
    <key>StandardErrorPath</key>
    <string>{LOG_PATH}</string>
    <key>WorkingDirectory</key>
    <string>{Path(brain_daemon_path).parent}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{Path(python_exe).parent}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
"""
        p = Path(plist_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        p.write_text(plist_content)
        return True
    except Exception:
        return False

def write_plist() -> Path:
    """Write the launchd plist file using canonical locations."""
    generate_plist(_daemon_script(), str(PLIST_PATH))
    return PLIST_PATH

def setup_daemon(brain_daemon_path: str = None) -> bool:
    """
    Wrapper for Typer setup command.
    """
    write_plist()
    if is_loaded():
        unload_plist()
    return load_plist()
