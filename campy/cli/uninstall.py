"""
campy/cli/uninstall.py — Reverse everything `campy install` does.

Removes:
  - MCP adapter entries from all detected AI client configs
  - UserPromptSubmit hook from ~/.claude/settings.json
  - launchd plist (macOS) or systemd service (Linux)
  - OpenClaw extension config patches

Optionally (with user confirmation):
  - Kuzu database at ~/.campy/brain.db or legacy ~/.sidequests/brain.db
  - Entire active Campy runtime directory
  - Ollama model (qwen2.5:3b or configured model)
"""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

import click

# ---------------------------------------------------------------------------
# Canonical paths (mirrors install.py)
# ---------------------------------------------------------------------------

from campy.paths import runtime_dir
from campy.branding import PRIMARY_MCP_SERVER, LEGACY_MCP_SERVER

SIDEQUESTS_HOME = runtime_dir()
DB_PATH         = SIDEQUESTS_HOME / "brain.db"
CONFIG_PATH     = SIDEQUESTS_HOME / "config.toml"
ENV_FILE        = SIDEQUESTS_HOME / ".env"

_PROJECT_ROOT           = Path(__file__).resolve().parent.parent.parent
_OPENCLAW_CONFIG_PATH   = Path.home() / ".openclaw" / "openclaw.json"
_OPENCLAW_MEMORY_TOOLS  = [
    "memory_recall",
    "memory_search",
    "memory_get",
    "memory_store",
    "memory_search_analogies",
    "memory_status",
    "memory_open_loops",
]

_CAMPY_SKILL_DIR_NAMES = {
    "brief",
    "campy-diagnose",
    "campy-grill",
    "campy-handoff",
    "campy-improve-architecture",
    "campy-memory",
    "campy-tdd",
    "diagnose",
    "grill",
    "handoff",
    "improve-architecture",
    "learn",
    "memory-awareness",
    "quest-management",
    "recall",
    "session-start",
    "sidequests-memory",
    "status",
    "tdd",
}

_PACKAGE_NAMES = ("hippocampy", "sidequests")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

class _R:
    def __init__(self, name: str, done: bool, detail: str) -> None:
        self.name   = name
        self.done   = done
        self.detail = detail


def _remove_tree(path: Path) -> bool:
    """Remove a file or directory if it exists."""
    if not path.exists():
        return False
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    return True


def _remove_hook_entries(
    config_path: Path,
    predicate: Callable[[dict], bool],
) -> bool:
    """Remove matching hook entries from a JSON config file."""
    if not config_path.exists():
        return False

    try:
        config = json.loads(config_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False

    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return False

    changed = False
    for event_name, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        filtered = [
            entry for entry in entries
            if not (isinstance(entry, dict) and predicate(entry))
        ]
        if len(filtered) != len(entries):
            changed = True
            if filtered:
                hooks[event_name] = filtered
            else:
                del hooks[event_name]

    if changed:
        config["hooks"] = hooks
        config_path.write_text(json.dumps(config, indent=2))

    return changed


def _remove_skill_dirs(skills_root: Path) -> int:
    """Remove known Campy skill directories under a skills root."""
    removed = 0
    for name in sorted(_CAMPY_SKILL_DIR_NAMES):
        try:
            if _remove_tree(skills_root / name):
                removed += 1
        except OSError:
            continue
    return removed


# ---------------------------------------------------------------------------
# Service teardown
# ---------------------------------------------------------------------------

def _stop_launchd() -> _R:
    """Unload the launchd user agent and remove its plist."""
    from campy.cli.launchd import LABEL, LEGACY_LABEL, LEGACY_PLIST_PATH, PLIST_PATH, unload_plist

    if not PLIST_PATH.exists() and not LEGACY_PLIST_PATH.exists():
        return _R("launchd service", True, "plist not present (skipped)")

    result = subprocess.run(["true"], capture_output=True, text=True)
    unload_plist(LABEL, PLIST_PATH)
    unload_plist(LEGACY_LABEL, LEGACY_PLIST_PATH)
    PLIST_PATH.unlink(missing_ok=True)
    LEGACY_PLIST_PATH.unlink(missing_ok=True)

    if result.returncode != 0 and "Could not find specified service" not in result.stderr:
        return _R("launchd service", False, f"unload warning: {result.stderr.strip()[:120]}")

    return _R("launchd service", True, "unloaded and removed Campy launchd plist(s)")


def _stop_systemd() -> _R:
    """Disable and remove the systemd user service."""
    service_path = Path.home() / ".config" / "systemd" / "user" / "hippocampy.service"

    if not service_path.exists():
        return _R("systemd service", True, "service file not present (skipped)")

    subprocess.run(
        ["systemctl", "--user", "disable", "--now", "hippocampy"],
        capture_output=True, text=True,
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)

    service_path.unlink(missing_ok=True)
    return _R("systemd service", True, f"disabled and removed {service_path}")


def _stop_daemon() -> _R:
    """Stop the daemon service for the current platform."""
    if platform.system() == "Darwin":
        return _stop_launchd()
    elif platform.system() == "Linux":
        return _stop_systemd()
    return _R("daemon service", True, f"not managed on {platform.system()}")


# ---------------------------------------------------------------------------
# Adapter / MCP config removal
# ---------------------------------------------------------------------------

def _remove_mcp_json_entry(config_path: Path, server_name: str = PRIMARY_MCP_SERVER) -> bool:
    """Remove a named entry from a JSON MCP config file. Returns True if changed."""
    if not config_path.exists():
        return False

    try:
        config = json.loads(config_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False

    changed = False
    for key in ("mcpServers", "mcp_servers"):
        for name in (
            server_name,
            "hippocampy",
            LEGACY_MCP_SERVER,
            "sidequests-brain",
            "sidequests-brain-desktop",
        ):
            if key in config and name in config[key]:
                del config[key][name]
                changed = True

    if changed:
        config_path.write_text(json.dumps(config, indent=2))

    return changed


def _remove_codex_toml_entry(config_path: Path) -> bool:
    """Remove the [mcp_servers.campy] block from a TOML config file."""
    if not config_path.exists():
        return False

    text = config_path.read_text()
    # Remove the section: from [mcp_servers.campy] to the next [section] or EOF
    new_text = re.sub(
        r"\n?\[mcp_servers\.(campy|sidequests)\][^\[]*",
        "",
        text,
        flags=re.DOTALL,
    ).strip() + "\n"

    if new_text != text.strip() + "\n":
        config_path.write_text(new_text)
        return True

    return False


def _remove_claude_hook(settings_path: Path) -> bool:
    """Remove the campy hook_user_turn.py entry from Claude settings.json."""
    if not settings_path.exists():
        return False

    try:
        settings = json.loads(settings_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False

    hooks = settings.get("hooks", {})
    user_hooks = hooks.get("UserPromptSubmit", [])

    before = len(user_hooks)
    hooks["UserPromptSubmit"] = [
        entry for entry in user_hooks
        if "hook_user_turn" not in json.dumps(entry)
    ]
    after = len(hooks["UserPromptSubmit"])

    if after != before:
        settings["hooks"] = hooks
        settings_path.write_text(json.dumps(settings, indent=2))
        return True

    return False


def _remove_codex_hooks(config_path: Path) -> bool:
    """Remove Campy hook entries from Codex hooks.json."""
    return _remove_hook_entries(
        config_path,
        lambda entry: any(
            "campy" in str(hook.get("command", ""))
            for hook in entry.get("hooks", [])
            if isinstance(hook, dict)
        ),
    )


def _remove_gemini_hooks(config_path: Path) -> bool:
    """Remove Campy hook entries from Gemini settings.json."""
    return _remove_hook_entries(
        config_path,
        lambda entry: any(
            hook.get("name", "").startswith("campy-")
            or "campy" in str(hook.get("command", ""))
            for hook in entry.get("hooks", [])
            if isinstance(hook, dict)
        ),
    )


def _remove_python_package() -> _R:
    """Attempt to uninstall Campy from pipx and pip.

    This intentionally runs last; it may remove the `campy` console script.
    """
    attempted = False
    removed = False
    details: list[str] = []

    pipx_bin = shutil.which("pipx")
    if pipx_bin:
        for package_name in _PACKAGE_NAMES:
            attempted = True
            result = subprocess.run(
                [pipx_bin, "uninstall", package_name],
                capture_output=True,
                text=True,
                timeout=60,
            )
            stdout = result.stdout.lower()
            stderr = result.stderr.lower()
            if result.returncode == 0:
                removed = True
                details.append(f"pipx:{package_name}")
            elif "not installed" not in stdout and "nothing to uninstall" not in stdout and "not installed" not in stderr:
                details.append(f"pipx warning for {package_name}")

    for package_name in _PACKAGE_NAMES:
        attempted = True
        result = subprocess.run(
            [sys.executable, "-m", "pip", "uninstall", "-y", package_name],
            capture_output=True,
            text=True,
            timeout=60,
        )
        stdout = result.stdout.lower()
        stderr = result.stderr.lower()
        if result.returncode == 0 and "successfully uninstalled" in stdout:
            removed = True
            details.append(f"pip:{package_name}")
        elif "skipping" not in stdout and "not installed" not in stdout and "warning: skipping" not in stderr:
            details.append(f"pip warning for {package_name}")

    if removed:
        return _R("Python package", True, f"removed via {', '.join(details)}")
    if attempted:
        detail = "; ".join(details) if details else "not installed (skipped)"
        return _R("Python package", True, detail)
    return _R("Python package", True, "pip/pipx not available (skipped)")


def _deregister_claude_code() -> _R:
    """Remove the Claude Code adapter registration."""
    changed = False

    # 1. Try `claude mcp remove` if claude CLI is available
    claude_bin = shutil.which("claude")
    if claude_bin:
        result = subprocess.run(
            [claude_bin, "mcp", "remove", "hippocampy", "--scope", "user"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            changed = True

    # 2. Also clean up ~/.claude.json (may have been written directly)
    for config_file in [Path.home() / ".claude.json", Path.cwd() / ".mcp.json"]:
        if _remove_mcp_json_entry(config_file):
            changed = True

    # 3. Remove UserPromptSubmit hook
    hook_settings = Path.home() / ".claude" / "settings.json"
    if _remove_claude_hook(hook_settings):
        changed = True

    # 4. Remove plugin and project-local hook artifacts.
    for path in [
        Path.home() / ".claude" / "plugins" / "hippocampy",
        Path.cwd() / ".claude" / "hooks",
    ]:
        try:
            if _remove_tree(path):
                changed = True
        except OSError:
            pass

    if changed:
        return _R("Claude Code", True, "adapter and hook removed")
    return _R("Claude Code", True, "not registered (skipped)")


def _deregister_claude_desktop() -> _R:
    """Remove the Claude Desktop adapter entry."""
    if platform.system() == "Darwin":
        config_path = (
            Path.home() / "Library" / "Application Support"
            / "Claude" / "claude_desktop_config.json"
        )
    elif platform.system() == "Windows":
        config_path = (
            Path.home() / "AppData" / "Roaming" / "Claude"
            / "claude_desktop_config.json"
        )
    else:
        return _R("Claude Desktop", True, "unsupported platform (skipped)")

    if _remove_mcp_json_entry(config_path):
        return _R("Claude Desktop", True, f"removed from {config_path}")
    return _R("Claude Desktop", True, "not registered (skipped)")


def _deregister_codex() -> _R:
    """Remove the Codex adapter entry from all known config locations."""
    changed = False

    codex_configs: list[Path] = [Path.home() / ".codex" / "config.toml"]
    if platform.system() == "Darwin":
        codex_configs += [
            Path.home() / "Library" / "Application Support" / "Codex" / "config.toml",
            Path.home() / "Library" / "Application Support" / "com.openai.codex" / "config.toml",
        ]
    elif platform.system() == "Windows":
        codex_configs.append(Path.home() / "AppData" / "Roaming" / "Codex" / "config.toml")

    for p in codex_configs:
        if _remove_codex_toml_entry(p):
            changed = True

    if _remove_codex_hooks(Path.home() / ".codex" / "hooks.json"):
        changed = True

    try:
        if _remove_tree(Path.home() / ".codex" / "hooks" / "campy"):
            changed = True
    except OSError:
        pass

    skills_root = Path.home() / ".codex" / "skills"
    if _remove_skill_dirs(skills_root):
        changed = True

    for path in [
        skills_root / "_archived_by_campy",
        Path.home() / ".codex" / "plugins" / "hippocampy",
    ]:
        try:
            if _remove_tree(path):
                changed = True
        except OSError:
            pass

    if changed:
        return _R("Codex", True, "removed config, hooks, and plugin artifacts")
    return _R("Codex", True, "not registered (skipped)")


def _deregister_gemini_cli() -> _R:
    """Remove the Gemini CLI adapter entry."""
    changed = False
    for config_path in [
        Path.home() / ".gemini" / "settings.json",
        Path.home() / ".config" / "gemini" / "settings.json",
    ]:
        if _remove_mcp_json_entry(config_path):
            changed = True
        if _remove_gemini_hooks(config_path):
            changed = True

    try:
        if _remove_tree(Path.home() / ".gemini" / "hooks" / "campy"):
            changed = True
    except OSError:
        pass

    if _remove_skill_dirs(Path.home() / ".gemini" / "skills"):
        changed = True

    try:
        if _remove_tree(Path.home() / ".gemini" / "plugins" / "hippocampy"):
            changed = True
    except OSError:
        pass

    if changed:
        return _R("Gemini CLI", True, "removed settings, hooks, and plugin artifacts")
    return _R("Gemini CLI", True, "not registered (skipped)")


def _deregister_openclaw() -> _R:
    """Undo OpenClaw config patches and optionally uninstall the plugin."""
    openclaw_bin = shutil.which("openclaw")
    changed = False

    # 1. Reverse config patches in openclaw.json
    if _OPENCLAW_CONFIG_PATH.exists():
        try:
            config = json.loads(_OPENCLAW_CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            config = {}

        # Remove plugin allow entry
        plugins = config.get("plugins", {})
        allow = plugins.get("allow", [])
        for plugin_id in ("hippocampy", "sidequests-brain"):
            if plugin_id in allow:
                allow.remove(plugin_id)
            config["plugins"] = plugins
            changed = True

        # Remove memory tools from sandbox allow
        sandbox_allow = (
            config.get("tools", {})
                  .get("sandbox", {})
                  .get("tools", {})
                  .get("allow", [])
        )
        before = len(sandbox_allow)
        for tool in _OPENCLAW_MEMORY_TOOLS:
            if tool in sandbox_allow:
                sandbox_allow.remove(tool)
        if len(sandbox_allow) != before:
            changed = True

        # Leave alsoAllow["group:plugins"] — could be needed by other plugins

        if changed:
            _OPENCLAW_CONFIG_PATH.write_text(json.dumps(config, indent=2))

    # 2. Remove the plugin
    if openclaw_bin:
        result = subprocess.run(
            [openclaw_bin, "plugins", "remove", "hippocampy"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            changed = True

        # 3. Restart gateway to pick up changes
        subprocess.run(
            [openclaw_bin, "gateway", "restart"],
            capture_output=True, text=True, timeout=15,
        )

    if changed:
        return _R("OpenClaw", True, "plugin removed, config patched, gateway restarted")
    return _R("OpenClaw", True, "not registered (skipped)")


# ---------------------------------------------------------------------------
# Data / config removal
# ---------------------------------------------------------------------------

def _remove_database(keep_data: bool) -> _R:
    """Remove the Kuzu database (or skip if user wants to keep it)."""
    if keep_data:
        return _R("Brain database", True, f"kept at {DB_PATH} (user requested)")

    if not DB_PATH.exists():
        return _R("Brain database", True, "not found (skipped)")

    try:
        shutil.rmtree(DB_PATH) if DB_PATH.is_dir() else DB_PATH.unlink()
        return _R("Brain database", True, f"deleted {DB_PATH}")
    except OSError as e:
        return _R("Brain database", False, f"delete failed: {e}")


def _remove_campy_home(keep_data: bool) -> _R:
    """Remove ~/.campy entirely (or skip if user wants to keep it)."""
    if keep_data:
        return _R("~/.campy dir", True, "kept (user requested)")

    if not SIDEQUESTS_HOME.exists():
        return _R("~/.campy dir", True, "not found (skipped)")

    try:
        shutil.rmtree(SIDEQUESTS_HOME)
        return _R("~/.campy dir", True, f"deleted {SIDEQUESTS_HOME}")
    except OSError as e:
        return _R("~/.campy dir", False, f"delete failed: {e}")


def _remove_sidequests_home(keep_data: bool) -> _R:
    """Legacy compatibility wrapper for tests and older callers."""
    return _remove_campy_home(keep_data)


def _remove_ollama_model(model: str = "qwen2.5:3b") -> _R:
    """Remove the Ollama model if present."""
    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        return _R(f"Ollama model ({model})", True, "ollama not in PATH (skipped)")

    result = subprocess.run(
        [ollama_bin, "rm", model],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode == 0:
        return _R(f"Ollama model ({model})", True, f"removed")
    if "not found" in result.stderr.lower() or "not found" in result.stdout.lower():
        return _R(f"Ollama model ({model})", True, "not installed (skipped)")
    return _R(f"Ollama model ({model})", False, result.stderr.strip()[:100])


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _print_report(results: list[_R]) -> None:
    click.echo("\n" + "=" * 50)
    click.echo("  UNINSTALL REPORT")
    click.echo("=" * 50)
    for r in results:
        status = "[ok]" if r.done else "[!!]"
        click.echo(f"  {status} {r.name:<30} {r.detail}")
    click.echo("=" * 50)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_uninstall(
    keep_data: bool = True,
    remove_ollama_model: bool = False,
    ollama_model: str = "qwen2.5:3b",
) -> None:
    """
    Full uninstall orchestration.

    keep_data=True  → leave ~/.campy/ and brain.db intact (default)
    keep_data=False → delete ~/.campy/ entirely
    """
    click.echo("\n" + "=" * 50)
    click.echo("  HippoCampy — Uninstall")
    click.echo("=" * 50 + "\n")

    results: list[_R] = []

    # ── Step 1: Stop daemon service ──────────────────────────────────────
    click.echo("Step 1/4: Stopping Brain Daemon service...")
    results.append(_stop_daemon())

    # ── Step 2: Deregister all AI client adapters ─────────────────────────
    click.echo("\nStep 2/4: Removing adapter registrations...")
    results.append(_deregister_claude_code())
    results.append(_deregister_claude_desktop())
    results.append(_deregister_codex())
    results.append(_deregister_gemini_cli())
    results.append(_deregister_openclaw())

    # ── Step 3: Data / config removal ─────────────────────────────────────
    click.echo("\nStep 3/4: Data and config removal...")
    if keep_data:
        results.append(_R("Brain data", True, f"kept at {SIDEQUESTS_HOME}"))
    else:
        results.append(_remove_campy_home(keep_data=False))

    # ── Step 4: Optional Ollama model removal ─────────────────────────────
    click.echo("\nStep 4/4: Optional Ollama model removal...")
    if remove_ollama_model:
        results.append(_remove_ollama_model(ollama_model))
    else:
        results.append(
            _R(f"Ollama model ({ollama_model})", True, "kept (use --remove-ollama-model to delete)")
        )

    results.append(_remove_python_package())

    _print_report(results)

    failures = [r for r in results if not r.done]
    if failures:
        click.echo(f"\n  {len(failures)} step(s) had warnings — see report above.\n")
    else:
        click.echo("\n  HippoCampy uninstalled cleanly.\n")
        if keep_data:
            click.echo(
                f"  Your memory data is still at {SIDEQUESTS_HOME}.\n"
                f"  Delete it manually if you no longer need it:\n"
                f"    rm -rf {SIDEQUESTS_HOME}\n"
            )
