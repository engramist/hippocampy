"""
sidequests/cli/uninstall.py — Reverse everything `sidequests install` does.

Removes:
  - MCP adapter entries from all detected AI client configs
  - UserPromptSubmit hook from ~/.claude/settings.json
  - launchd plist (macOS) or systemd service (Linux)
  - OpenClaw extension config patches

Optionally (with user confirmation):
  - Kuzu database at ~/.sidequests/brain.db
  - Entire ~/.sidequests/ directory
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
from typing import Optional

import click

# ---------------------------------------------------------------------------
# Canonical paths (mirrors install.py)
# ---------------------------------------------------------------------------

SIDEQUESTS_HOME = Path.home() / ".sidequests"
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


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

class _R:
    def __init__(self, name: str, done: bool, detail: str) -> None:
        self.name   = name
        self.done   = done
        self.detail = detail


# ---------------------------------------------------------------------------
# Service teardown
# ---------------------------------------------------------------------------

def _stop_launchd() -> _R:
    """Unload the launchd user agent and remove its plist."""
    from sidequests.cli.launchd import LABEL, PLIST_PATH

    if not PLIST_PATH.exists():
        return _R("launchd service", True, "plist not present (skipped)")

    result = subprocess.run(
        ["launchctl", "unload", str(PLIST_PATH)],
        capture_output=True, text=True,
    )

    PLIST_PATH.unlink(missing_ok=True)

    if result.returncode != 0 and "Could not find specified service" not in result.stderr:
        return _R("launchd service", False, f"unload warning: {result.stderr.strip()[:120]}")

    return _R("launchd service", True, f"unloaded and removed {PLIST_PATH}")


def _stop_systemd() -> _R:
    """Disable and remove the systemd user service."""
    service_path = Path.home() / ".config" / "systemd" / "user" / "sidequests-brain.service"

    if not service_path.exists():
        return _R("systemd service", True, "service file not present (skipped)")

    subprocess.run(
        ["systemctl", "--user", "disable", "--now", "sidequests-brain"],
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

def _remove_mcp_json_entry(config_path: Path, server_name: str = "sidequests-brain") -> bool:
    """Remove a named entry from a JSON MCP config file. Returns True if changed."""
    if not config_path.exists():
        return False

    try:
        config = json.loads(config_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False

    changed = False
    for key in ("mcpServers", "mcp_servers"):
        if key in config and server_name in config[key]:
            del config[key][server_name]
            changed = True

    if changed:
        config_path.write_text(json.dumps(config, indent=2))

    return changed


def _remove_codex_toml_entry(config_path: Path) -> bool:
    """Remove the [mcp_servers.sidequests] block from a TOML config file."""
    if not config_path.exists():
        return False

    text = config_path.read_text()
    # Remove the section: from [mcp_servers.sidequests] to the next [section] or EOF
    new_text = re.sub(
        r"\n?\[mcp_servers\.sidequests\][^\[]*",
        "",
        text,
        flags=re.DOTALL,
    ).strip() + "\n"

    if new_text != text.strip() + "\n":
        config_path.write_text(new_text)
        return True

    return False


def _remove_claude_hook(settings_path: Path) -> bool:
    """Remove the sidequests hook_user_turn.py entry from Claude settings.json."""
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


def _deregister_claude_code() -> _R:
    """Remove the Claude Code adapter registration."""
    changed = False

    # 1. Try `claude mcp remove` if claude CLI is available
    claude_bin = shutil.which("claude")
    if claude_bin:
        result = subprocess.run(
            [claude_bin, "mcp", "remove", "sidequests-brain", "--scope", "user"],
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

    if changed:
        return _R("Codex", True, "removed from config")
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

    if changed:
        return _R("Gemini CLI", True, "removed from settings.json")
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
        if "sidequests-brain" in allow:
            allow.remove("sidequests-brain")
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
            [openclaw_bin, "plugins", "remove", "sidequests-brain"],
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


def _remove_sidequests_home(keep_data: bool) -> _R:
    """Remove ~/.sidequests entirely (or skip if user wants to keep it)."""
    if keep_data:
        return _R("~/.sidequests dir", True, "kept (user requested)")

    if not SIDEQUESTS_HOME.exists():
        return _R("~/.sidequests dir", True, "not found (skipped)")

    try:
        shutil.rmtree(SIDEQUESTS_HOME)
        return _R("~/.sidequests dir", True, f"deleted {SIDEQUESTS_HOME}")
    except OSError as e:
        return _R("~/.sidequests dir", False, f"delete failed: {e}")


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

    keep_data=True  → leave ~/.sidequests/ and brain.db intact (default)
    keep_data=False → delete ~/.sidequests/ entirely
    """
    click.echo("\n" + "=" * 50)
    click.echo("  SideQuests Brain — Uninstall")
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
        results.append(_remove_sidequests_home(keep_data=False))

    # ── Step 4: Optional Ollama model removal ─────────────────────────────
    click.echo("\nStep 4/4: Optional Ollama model removal...")
    if remove_ollama_model:
        results.append(_remove_ollama_model(ollama_model))
    else:
        results.append(
            _R(f"Ollama model ({ollama_model})", True, "kept (use --remove-ollama-model to delete)")
        )

    _print_report(results)

    failures = [r for r in results if not r.done]
    if failures:
        click.echo(f"\n  {len(failures)} step(s) had warnings — see report above.\n")
    else:
        click.echo("\n  SideQuests Brain uninstalled cleanly.\n")
        if keep_data:
            click.echo(
                f"  Your memory data is still at {SIDEQUESTS_HOME}.\n"
                f"  Delete it manually if you no longer need it:\n"
                f"    rm -rf {SIDEQUESTS_HOME}\n"
            )
