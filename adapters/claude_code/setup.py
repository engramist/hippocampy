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
    # B290: Install .githooks directory as the project git hooks path
    _configure_git_hooks(project_root)
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


def _configure_git_hooks(project_root: Path) -> None:
    """Set core.hooksPath to .githooks so post-commit fires on every commit."""
    import subprocess
    githooks_dir = project_root / ".githooks"
    githooks_dir.mkdir(exist_ok=True)
    post_commit = githooks_dir / "post-commit"
    if not post_commit.exists():
        # Copy from repo if running from development checkout
        src = REPO_ROOT / ".githooks" / "post-commit"
        if src.exists():
            import shutil
            shutil.copy2(src, post_commit)
            post_commit.chmod(0o755)
    try:
        subprocess.run(
            ["git", "-C", str(project_root), "config", "core.hooksPath", ".githooks"],
            check=True, capture_output=True, timeout=5,
        )
    except Exception as e:
        print(f"  Warning: could not set core.hooksPath: {e}")


def _is_campy_created_entry(entry) -> bool:
    """True if an mcpServers entry has the shape campy's own tooling writes.

    Campy registers stdio entries whose command/args reference the
    `campy.adapters.*` modules or an `adapters/<client>/adapter.py` path.
    Anything else (e.g. an HTTP entry to the daemon, hand-authored and
    git-tracked) is user-managed and must not be touched.
    """
    if not isinstance(entry, dict):
        return False
    parts = [str(entry.get("command", ""))] + [str(a) for a in entry.get("args", [])]
    return any("campy.adapters" in p or "adapters/claude_code/adapter.py" in p for p in parts)


def _write_mcp_json(project_root: Path) -> None:
    """Merge the campy server entry into the project-root .mcp.json.

    The file is git-tracked and may hold entries for other MCP servers (or a
    hand-authored campy entry pointing at the HTTP daemon). Merge into the
    existing config — never drop entries campy didn't create.
    """
    mcp_path = project_root / ".mcp.json"
    config = {}
    if mcp_path.exists():
        try:
            config = json.loads(mcp_path.read_text())
        except json.JSONDecodeError:
            print(f"  Warning: {mcp_path} is not valid JSON — leaving it untouched")
            return
    if not isinstance(config, dict):
        config = {}

    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = config["mcpServers"] = {}

    existing = servers.get("campy")
    if existing is not None and not _is_campy_created_entry(existing):
        # User-managed entry (e.g. {"type": "http", "url": ...}) — keep it.
        return

    servers["campy"] = {
        "command": _python_executable(),
        "args": ["-m", "campy.adapters.mcp_server"],
    }
    with open(mcp_path, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")


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
