"""
adapters/claude_code/setup.py — Claude Code Registration

Called by `campy setup` to register the adapter with Claude Code:
  1. Writes .mcp.json in the project root (registers MCP server)
  2. Adds UserPromptSubmit hook to ~/.claude/settings.json
"""

import json
import sys
from pathlib import Path

ADAPTER_DIR  = Path(__file__).parent
HOOK_FILE    = ADAPTER_DIR / "hook_user_turn.py"
REPO_ROOT    = ADAPTER_DIR.parent.parent


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
    print("Claude Code adapter registered.")
    print(f"  MCP server: {project_root / '.mcp.json'}")
    print(f"  Hook config: {Path.home() / '.claude' / 'settings.json'}")


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
        with open(settings_path) as f:
            settings = json.load(f)

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

    # Repair stale entries as well as avoiding duplicates. Test runs or moved
    # installs can leave hooks pointing at a temp/interpreter path while still
    # containing the same hook script.
    user_prompt_hooks[:] = [
        entry
        for entry in user_prompt_hooks
        if not any(str(HOOK_FILE) in str(h) for h in entry.get("hooks", []))
    ]
    user_prompt_hooks.append(hook_entry)

    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)


if __name__ == "__main__":
    register()
