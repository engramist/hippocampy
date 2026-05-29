"""
adapters/codex/setup.py — Codex CLI Registration

Called by `campy setup` to register Campy hooks with Codex CLI:
  1. Copies hook scripts to ~/.codex/hooks/campy/
  2. Adds hook entries to ~/.codex/hooks.json
"""

import json
import shutil
import sys
from pathlib import Path

ADAPTER_DIR = Path(__file__).parent
HOOKS_DIR = ADAPTER_DIR / "hooks"
REPO_ROOT = ADAPTER_DIR.parent.parent

# Target locations
CODEX_HOOKS_DIR = Path.home() / ".codex" / "hooks" / "campy"
CODEX_HOOKS_JSON = Path.home() / ".codex" / "hooks.json"


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
    """Register Campy hooks with Codex CLI."""
    project_root = project_root or Path.cwd()

    install_hooks(project_root)
    _write_hook_config()
    print("Codex CLI adapter registered.")
    print(f"  Hook scripts: {CODEX_HOOKS_DIR}")
    print(f"  Hook config: {CODEX_HOOKS_JSON}")


def install_hooks(project_root: Path = None) -> bool:
    """Copy Campy hook scripts to ~/.codex/hooks/campy/."""
    if not HOOKS_DIR.exists():
        return False

    CODEX_HOOKS_DIR.mkdir(parents=True, exist_ok=True)

    installed = []
    for hook_script in sorted(HOOKS_DIR.glob("*.py")):
        if hook_script.name == "__init__.py":
            continue
        dest = CODEX_HOOKS_DIR / hook_script.name
        shutil.copy2(hook_script, dest)
        dest.chmod(0o755)
        installed.append(dest)

    return len(installed) > 0


def _write_hook_config() -> None:
    """Add Campy hook entries to ~/.codex/hooks.json.

    Merges with existing config — does not overwrite user's other hooks.
    Removes stale Campy entries before adding fresh ones.
    """
    CODEX_HOOKS_JSON.parent.mkdir(parents=True, exist_ok=True)

    config = {}
    if CODEX_HOOKS_JSON.exists():
        try:
            with open(CODEX_HOOKS_JSON) as f:
                config = json.load(f)
        except (json.JSONDecodeError, OSError):
            config = {}

    hooks = config.setdefault("hooks", {})

    # Campy hook entries per Codex spec
    campy_hooks = {
        "SessionStart": {
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": f"python3 {CODEX_HOOKS_DIR / 'session_start.py'}",
                "timeout": 10,
            }],
        },
        "PreToolUse": {
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": f"python3 {CODEX_HOOKS_DIR / 'pre_tool_use.py'}",
                "timeout": 5,
            }],
        },
        "PostToolUse": {
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": f"python3 {CODEX_HOOKS_DIR / 'post_tool_use.py'}",
                "timeout": 5,
            }],
        },
        "UserPromptSubmit": {
            "matcher": "",
            "hooks": [{
                "type": "command",
                "command": f"python3 {CODEX_HOOKS_DIR / 'user_prompt.py'}",
                "timeout": 5,
            }],
        },
    }

    for event_name, campy_entry in campy_hooks.items():
        event_hooks = hooks.setdefault(event_name, [])
        # Remove stale Campy entries (detect by path containing "campy")
        event_hooks[:] = [
            entry for entry in event_hooks
            if not any("campy" in str(h.get("command", "")) for h in entry.get("hooks", []))
        ]
        event_hooks.append(campy_entry)

    with open(CODEX_HOOKS_JSON, "w") as f:
        json.dump(config, f, indent=2)


if __name__ == "__main__":
    register()
