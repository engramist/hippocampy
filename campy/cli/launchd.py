import os
import subprocess
import sys
import shutil
from pathlib import Path

from campy.branding import LEGACY_LAUNCHD_LABEL, LEGACY_LAUNCHD_LABELS, PRIMARY_LAUNCHD_LABEL
from campy.paths import get_daemon_log_path, get_launchd_plist_path, get_legacy_launchd_plist_path

LABEL = PRIMARY_LAUNCHD_LABEL
LEGACY_LABEL = LEGACY_LAUNCHD_LABEL
PLIST_PATH = get_launchd_plist_path(LABEL)
LEGACY_PLIST_PATH = get_legacy_launchd_plist_path()
LOG_PATH = get_daemon_log_path()


def resolve_system_python() -> str:
    """Find the Python interpreter launchd should use."""
    repo_root = Path(__file__).parent.parent.parent
    venv_python = repo_root / ".venv" / "bin" / "python"
    if venv_python.exists():
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


def _launchctl_list(label: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", "list", label], capture_output=True, text=True)


def is_loaded(label: str = LABEL) -> bool:
    """Return True if the service is loaded in launchctl."""
    return _launchctl_list(label).returncode == 0


def unload_plist(label: str = LABEL, plist_path: Path | None = None) -> bool:
    """Unload the plist from launchctl."""
    path = plist_path or (LEGACY_PLIST_PATH if label == LEGACY_LABEL else PLIST_PATH)
    if not path.exists():
        if not is_loaded(label):
            return True
        subprocess.run(["launchctl", "remove", label], capture_output=True, text=True)
        return not is_loaded(label)
    result = subprocess.run(["launchctl", "unload", str(path)], capture_output=True, text=True)
    if result.returncode != 0 and is_loaded(label):
        subprocess.run(["launchctl", "remove", label], capture_output=True, text=True)
    return result.returncode == 0 or not is_loaded(label)


def load_plist(label: str = LABEL, plist_path: Path | None = None) -> bool:
    """Load the plist into launchctl."""
    path = plist_path or (LEGACY_PLIST_PATH if label == LEGACY_LABEL else PLIST_PATH)
    if not path.exists():
        return False
    result = subprocess.run(["launchctl", "load", str(path)], capture_output=True, text=True)
    return result.returncode == 0 or is_loaded(label)


def generate_plist(brain_daemon_path: str, plist_path: str, label: str = LABEL) -> bool:
    """Generate the launchd plist file for auto-start on macOS."""
    try:
        python_exe = resolve_system_python()
        log_path = get_daemon_log_path()
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
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
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
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
        log_path.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(plist_content)
        return True
    except Exception:
        return False


def write_plist() -> Path:
    """Write the launchd plist file using canonical Campy locations."""
    generate_plist(_daemon_script(), str(PLIST_PATH), LABEL)
    return PLIST_PATH


def setup_daemon(brain_daemon_path: str = None) -> bool:
    """Install/reload the Campy daemon launchd plist."""
    write_plist()
    for legacy_label in LEGACY_LAUNCHD_LABELS:
        if is_loaded(legacy_label):
            unload_plist(legacy_label, get_launchd_plist_path(legacy_label))
    if is_loaded(LABEL):
        unload_plist(LABEL, PLIST_PATH)
    return load_plist(LABEL, PLIST_PATH)
