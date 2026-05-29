"""
adapters/claude_code/setup.py — Claude Code Registration

Called by `campy setup` to register the adapter with Claude Code:
  1. Writes .mcp.json in the project root (registers MCP server)
  2. Adds UserPromptSubmit hook to ~/.claude/settings.json
  3. Installs hook scripts to .claude/hooks/
"""

import json
import shutil
import sys
from pathlib import Path

ADAPTER_DIR  = Path(__file__).parent
HOOK_FILE    = ADAPTER_DIR / "hook_user_turn.py"
REPO_ROOT    = ADAPTER_DIR.parent.parent
HOOK_BASENAME = HOOK_FILE.name


def _python_executable() -> str:
    for candidate in (
        REPO_ROOT / ".venv" / "bin" / "python",
        REPO_ROOT / ".venv" / "bin" / "python3.12",
    ):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def register(project_root: Path = None) -> None:
    project_root = project_root or Path.cwd()

    _write_mcp_json(project_root)
    _write_hook_config()
    install_hooks(project_root)
    print("Claude Code adapter registered.")
    print(f"  MCP server: {project_root / '.mcp.json'}")
    print(f"  Hook config: {Path.home() / '.claude' / 'settings.json'}")
    print(f"  Hooks: {project_root / '.claude' / 'hooks'}")


def install_hooks(project_root: Path = None) -> bool:
    """Install Claude Code hooks for Campy memory integration."""
    if project_root is None:
        project_root = Path.cwd()
    
    hooks_dir = project_root / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    
    # Source hooks from the adapter directory
    adapter_hooks = ADAPTER_DIR / "hooks"
    if not adapter_hooks.exists():
        return False
    
    installed = []
    for hook_script in adapter_hooks.glob("*.sh"):
        dest = hooks_dir / hook_script.name
        shutil.copy2(hook_script, dest)
        dest.chmod(0o755)
        installed.append(dest)
    
    return len(installed) > 0


def _write_mcp_json(project_root: Path) -> None:
    """Write .mcp.json to register the MCP STDIO server with Claude Code."""
    mcp_config = {
        "mcpServers": {
            "campy": {
                "command": _python_executable(),
                "args": ["-m", "campy.adapters.mcp_server"],
            }
        }
    }
    mcp_path = project_root / ".mcp.json"
    with open(mcp_path, "w") as f:
        json.dump(mcp_config, f, indent=2)


def _write_hook_config() -> None:
    """Add UserPromptSubmit hook to ~/.claude/settings.json."""
    settings_path = Path.home() / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    settings = {}
    if settings_path.exists():
        try:
            with open(settings_path) as f:
                settings = json.load(f)
        except json.JSONDecodeError:
            settings = {}

    hook_entry = {
        "matcher": "",
        "hooks": [
            {
                "type": "command",
                "command": f"{_python_executable()} {HOOK_FILE}",
            }
        ],
    }

    hooks = settings.setdefault("hooks", {})
    user_prompt_hooks = hooks.setdefault("UserPromptSubmit", [])

    # Repair stale entries as well as avoiding duplicates. Claude updates can
    # start hard-blocking prompts when an old install path still points at a
    # missing hook_user_turn.py, so remove any legacy entry for this hook name
    # before writing the canonical one.
    user_prompt_hooks[:] = [
        entry
        for entry in user_prompt_hooks
        if not any(
            HOOK_BASENAME in str(hook.get("command", ""))
            for hook in entry.get("hooks", [])
            if isinstance(hook, dict)
        )
    ]
    user_prompt_hooks.append(hook_entry)

    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)


if __name__ == "__main__":
    register()
