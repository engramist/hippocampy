"""
adapters/claude_code/setup.py — Claude Code Registration

Called by `sidequests setup` to register the adapter with Claude Code:
  1. Writes .mcp.json in the project root (registers MCP server)
  2. Adds UserPromptSubmit hook to ~/.claude/settings.json
"""

import json
import sys
from pathlib import Path

ADAPTER_DIR  = Path(__file__).parent
ADAPTER_FILE = ADAPTER_DIR / "adapter.py"
HOOK_FILE    = ADAPTER_DIR / "hook_user_turn.py"


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
            "sidequests-brain": {
                "command": sys.executable,
                "args": [str(ADAPTER_FILE)],
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
                "command": f"{sys.executable} {HOOK_FILE}",
            }
        ],
    }

    hooks = settings.setdefault("hooks", {})
    user_prompt_hooks = hooks.setdefault("UserPromptSubmit", [])

    # Avoid duplicate registration
    already_registered = any(
        str(HOOK_FILE) in str(h)
        for entry in user_prompt_hooks
        for h in entry.get("hooks", [])
    )
    if not already_registered:
        user_prompt_hooks.append(hook_entry)

    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)


if __name__ == "__main__":
    register()
