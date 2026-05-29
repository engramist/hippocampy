"""
adapters/gemini_cli/setup.py — Gemini CLI Registration

Called by `campy setup` to register Campy hooks with Gemini CLI:
  1. Copies hook scripts to ~/.gemini/hooks/campy/
  2. Adds hook entries to ~/.gemini/settings.json
"""

import json
import shutil
import sys
from pathlib import Path

ADAPTER_DIR = Path(__file__).parent
HOOKS_DIR = ADAPTER_DIR / "hooks"
REPO_ROOT = ADAPTER_DIR.parent.parent

# Target locations
GEMINI_HOOKS_DIR = Path.home() / ".gemini" / "hooks" / "campy"
GEMINI_SETTINGS = Path.home() / ".gemini" / "settings.json"


def _python_executable() -> str:
    """Find the best Python executable to use in hook commands."""
    for candidate in (
        REPO_ROOT / ".venv" / "bin" / "python",
        REPO_ROOT / ".venv" / "bin" / "python3.12",
    ):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def register(project_root: Path = None) -> None:
    """Register Campy hooks with Gemini CLI."""
    project_root = project_root or Path.cwd()

    install_hooks(project_root)
    _write_hook_config()
    print("Gemini CLI adapter registered.")
    print(f"  Hook scripts: {GEMINI_HOOKS_DIR}")
    print(f"  Hook config: {GEMINI_SETTINGS}")


def install_hooks(project_root: Path = None) -> bool:
    """Copy Campy hook scripts to ~/.gemini/hooks/campy/."""
    if not HOOKS_DIR.exists():
        return False

    GEMINI_HOOKS_DIR.mkdir(parents=True, exist_ok=True)

    installed = []
    for hook_script in sorted(HOOKS_DIR.glob("*.py")):
        if hook_script.name == "__init__.py":
            continue
        dest = GEMINI_HOOKS_DIR / hook_script.name
        shutil.copy2(hook_script, dest)
        dest.chmod(0o755)
        installed.append(dest)

    return len(installed) > 0


def _write_hook_config() -> None:
    """Add Campy hook entries to ~/.gemini/settings.json.

    Merges with existing config — does not overwrite user's mcpServers,
    security, or other settings. Removes stale Campy entries before
    adding fresh ones.
    """
    GEMINI_SETTINGS.parent.mkdir(parents=True, exist_ok=True)

    settings = {}
    if GEMINI_SETTINGS.exists():
        try:
            with open(GEMINI_SETTINGS) as f:
                settings = json.load(f)
        except (json.JSONDecodeError, OSError):
            settings = {}

    hooks = settings.setdefault("hooks", {})

    # Campy hook entries per Gemini spec (timeout in ms, name for identification)
    campy_hooks = {
        "SessionStart": {
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": f"python3 {GEMINI_HOOKS_DIR / 'session_start.py'}",
                "timeout": 5000,
                "name": "campy-session-start",
            }],
        },
        "BeforeTool": {
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": f"python3 {GEMINI_HOOKS_DIR / 'before_tool.py'}",
                "timeout": 5000,
                "name": "campy-before-tool",
            }],
        },
        "AfterTool": {
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": f"python3 {GEMINI_HOOKS_DIR / 'after_tool.py'}",
                "timeout": 5000,
                "name": "campy-after-tool",
            }],
        },
    }

    for event_name, campy_entry in campy_hooks.items():
        event_hooks = hooks.setdefault(event_name, [])
        # Remove stale Campy entries (detect by name prefix "campy-")
        event_hooks[:] = [
            entry for entry in event_hooks
            if not any(h.get("name", "").startswith("campy-") for h in entry.get("hooks", []))
        ]
        event_hooks.append(campy_entry)

    with open(GEMINI_SETTINGS, "w") as f:
        json.dump(settings, f, indent=2)


if __name__ == "__main__":
    register()
