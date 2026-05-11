"""
sidequests/cli/setup.py — Register adapters + start the Brain Daemon.

Called by `sidequests setup [--target <client>] [--project-root <path>]`.
Idempotent: safe to run multiple times.
"""

from __future__ import annotations
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from sidequests.cli.register import (
    _python_for_adapter,
    _strip_codex_adapter_path_tables,
    _upsert_codex_mcp_block,
    install_codex_memory_skill,
)

# Absolute path to the adapters directory (resolved at import time)
_ADAPTERS_DIR = Path(__file__).parent.parent.parent / "adapters"
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_OPENCLAW_EXTENSION_DIR = _PROJECT_ROOT / "extensions" / "sidequests-brain"
_OPENCLAW_CONFIG_PATH = Path.home() / ".openclaw" / "openclaw.json"
_OPENCLAW_MEMORY_TOOLS = [
    "memory_recall",
    "memory_search",
    "memory_get",
    "memory_store",
    "memory_search_analogies",
    "memory_status",
    "memory_open_loops",
]


# ---------------------------------------------------------------------------
# Per-client registration
# ---------------------------------------------------------------------------

def _register_claude_code(project_root: Path) -> None:
    """Register the Claude Code adapter via .mcp.json + hook config."""
    adapter_setup_dir = _ADAPTERS_DIR / "claude_code"
    if str(adapter_setup_dir.parent.parent) not in sys.path:
        sys.path.insert(0, str(adapter_setup_dir.parent.parent))
    from adapters.claude_code.setup import register
    register(project_root=project_root)
    print("  [✓] Claude Code — .mcp.json + UserPromptSubmit hook registered")


def _register_claude_desktop() -> None:
    """Register the Claude Desktop adapter in its config file."""
    # B-6 Plan: Use python -m sidequests.adapters.claude_desktop
    entry = {
        "mcpServers": {
            "sidequests-brain-desktop": {
                "command": sys.executable,
                "args":    ["-m", "sidequests.adapters.claude_desktop"],
            }
        }
    }

    system = platform.system()
    if system == "Darwin":
        config_path = (
            Path.home() / "Library" / "Application Support"
            / "Claude" / "claude_desktop_config.json"
        )
    elif system == "Windows":
        config_path = (
            Path.home() / "AppData" / "Roaming" / "Claude"
            / "claude_desktop_config.json"
        )
    else:
        print("  [!] Claude Desktop: unsupported platform — manual config required")
        return

    config_path.parent.mkdir(parents=True, exist_ok=True)
    _merge_mcp_config(config_path, "sidequests-brain-desktop", entry["mcpServers"]["sidequests-brain-desktop"])
    print(f"  [✓] Claude Desktop — config updated at {config_path}")


def _register_codex(project_root: Path) -> None:
    """Register the Codex adapter in ~/.codex/config.toml (or project .codex/config.toml)."""
    adapter_path = (_ADAPTERS_DIR / "codex" / "adapter.py").resolve()

    project_config = project_root / ".codex" / "config.toml"
    global_config  = Path.home() / ".codex" / "config.toml"
    config_path = project_config if project_config.parent.exists() else global_config

    config_path.parent.mkdir(parents=True, exist_ok=True)

    existing = config_path.read_text() if config_path.exists() else ""
    updated = _strip_codex_adapter_path_tables(existing, str(adapter_path))
    updated = _upsert_codex_mcp_block(
        updated, _python_for_adapter(str(adapter_path)), str(adapter_path)
    )
    config_path.write_text(updated)
    install_codex_memory_skill(project_root)
    print(f"  [✓] Codex — config updated at {config_path}")


def _register_codex_desktop(project_root: Path) -> None:
    """Register Codex Desktop using the same Codex adapter entry."""
    adapter_path = (_ADAPTERS_DIR / "codex" / "adapter.py").resolve()
    system = platform.system()

    if system == "Darwin":
        config_candidates = [
            Path.home() / "Library" / "Application Support" / "Codex" / "config.toml",
            Path.home() / "Library" / "Application Support" / "com.openai.codex" / "config.toml",
            Path.home() / ".codex" / "config.toml",
        ]
    elif system == "Windows":
        appdata = Path.home() / "AppData" / "Roaming"
        config_candidates = [
            appdata / "Codex" / "config.toml",
            Path.home() / ".codex" / "config.toml",
        ]
    else:
        print("  [!] Codex Desktop: unsupported platform — falling back to Codex CLI config")
        _register_codex(project_root)
        return

    config_path = None
    for candidate in config_candidates:
        if candidate.parent.exists() or candidate.exists():
            config_path = candidate
            break
    if config_path is None:
        config_path = config_candidates[-1]

    config_path.parent.mkdir(parents=True, exist_ok=True)
    existing = config_path.read_text() if config_path.exists() else ""
    updated = _strip_codex_adapter_path_tables(existing, str(adapter_path))
    updated = _upsert_codex_mcp_block(
        updated, _python_for_adapter(str(adapter_path)), str(adapter_path)
    )
    config_path.write_text(updated)
    install_codex_memory_skill(project_root)
    print(f"  [✓] Codex Desktop — config updated at {config_path}")


def _register_chatgpt_desktop() -> None:
    """Print instructions for ChatGPT Desktop (SSE connector URL)."""
    print("  [i] ChatGPT Desktop — paste this URL in Settings > Apps > Add Connector:")
    print("        http://127.0.0.1:7799/sse")
    print("      (Requires the Brain Daemon to be running.)")


def _register_gemini_cli() -> None:
    """Register the Gemini CLI adapter."""
    adapter_path = (_ADAPTERS_DIR / "gemini_cli" / "adapter.py").resolve()

    config_candidates = [
        Path.home() / ".gemini" / "settings.json",
        Path.home() / ".config" / "gemini" / "settings.json",
    ]

    config_path = None
    for candidate in config_candidates:
        if candidate.exists():
            config_path = candidate
            break

    if config_path is None:
        config_path = config_candidates[0]
        config_path.parent.mkdir(parents=True, exist_ok=True)

    entry = {
        "command": sys.executable,
        "args":    [str(adapter_path)],
    }

    _merge_mcp_config(config_path, "sidequests-brain", entry)
    print(f"  [✓] Gemini CLI — config updated at {config_path}")


def _register_openclaw() -> None:
    """Install the OpenClaw extension, patch config, and restart gateway."""
    openclaw_bin = shutil.which("openclaw")
    if not openclaw_bin:
        raise RuntimeError("openclaw CLI not found in PATH")
    if not _OPENCLAW_EXTENSION_DIR.exists():
        raise RuntimeError(f"OpenClaw extension directory not found: {_OPENCLAW_EXTENSION_DIR}")

    _patch_openclaw_config(_OPENCLAW_CONFIG_PATH)
    print(f"  [✓] OpenClaw — config updated at {_OPENCLAW_CONFIG_PATH}")

    install_cmd = [openclaw_bin, "plugins", "install", str(_OPENCLAW_EXTENSION_DIR)]
    install_result = subprocess.run(install_cmd, capture_output=True, text=True)
    if install_result.returncode != 0:
        stderr = (install_result.stderr or "").strip()
        stdout = (install_result.stdout or "").strip()
        detail = stderr or stdout or "plugin install failed"
        raise RuntimeError(f"openclaw plugins install failed: {detail}")
    print(f"  [✓] OpenClaw — extension installed from {_OPENCLAW_EXTENSION_DIR}")

    restart_cmd = [openclaw_bin, "gateway", "restart"]
    restart_result = subprocess.run(restart_cmd, capture_output=True, text=True)
    if restart_result.returncode != 0:
        stderr = (restart_result.stderr or "").strip()
        stdout = (restart_result.stdout or "").strip()
        detail = stderr or stdout or "gateway restart failed"
        raise RuntimeError(f"openclaw gateway restart failed: {detail}")
    print("  [✓] OpenClaw — gateway restarted")

    explain_cmd = [openclaw_bin, "sandbox", "explain"]
    explain_result = subprocess.run(explain_cmd, capture_output=True, text=True)
    if explain_result.returncode != 0:
        stderr = (explain_result.stderr or "").strip()
        stdout = (explain_result.stdout or "").strip()
        detail = stderr or stdout or "sandbox explain failed"
        raise RuntimeError(f"openclaw sandbox explain failed: {detail}")

    explain_output = (explain_result.stdout or "") + "\n" + (explain_result.stderr or "")
    missing_tools = [tool for tool in _OPENCLAW_MEMORY_TOOLS if tool not in explain_output]
    if missing_tools and "group:plugins" not in explain_output:
        raise RuntimeError(
            "OpenClaw sandbox verification failed; memory tools not visible in sandbox explain: "
            + ", ".join(missing_tools)
        )
    print("  [✓] OpenClaw — sandbox policy verified")


# ---------------------------------------------------------------------------
# Config file helpers
# ---------------------------------------------------------------------------

def _merge_mcp_config(config_path: Path, server_name: str, server_entry: dict) -> None:
    """
    Merge a single MCP server entry into a JSON config file.
    Reads existing config, merges, writes back. Never clobbers other entries.
    """
    config = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            config = {}

    servers = config.setdefault("mcpServers", {})
    servers[server_name] = server_entry
    config_path.write_text(json.dumps(config, indent=2))


def _patch_openclaw_config(config_path: Path) -> None:
    """Ensure OpenClaw trusts and surfaces the SideQuests plugin tools."""
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            config = {}

    plugins = config.setdefault("plugins", {})
    allow = plugins.setdefault("allow", [])
    if "sidequests-brain" not in allow:
        allow.append("sidequests-brain")

    tools = config.setdefault("tools", {})
    sandbox = tools.setdefault("sandbox", {})
    sandbox_tools = sandbox.setdefault("tools", {})

    also_allow = sandbox_tools.setdefault("alsoAllow", [])
    if "group:plugins" not in also_allow:
        also_allow.append("group:plugins")

    explicit_allow = sandbox_tools.setdefault("allow", [])
    for tool_name in _OPENCLAW_MEMORY_TOOLS:
        if tool_name not in explicit_allow:
            explicit_allow.append(tool_name)

    config_path.write_text(json.dumps(config, indent=2))


def _ensure_sidequests_toml(project_root: Path) -> None:
    """Write a default sidequests.toml if none exists."""
    template_path = Path(__file__).parent.parent.parent / "sidequests.toml"
    target_path   = project_root / "sidequests.toml"

    if not target_path.exists() and template_path.exists():
        shutil.copy(template_path, target_path)
        print(f"  [✓] Created sidequests.toml at {target_path}")
    elif target_path.exists():
        print(f"  [=] sidequests.toml already exists at {target_path}")


# ---------------------------------------------------------------------------
# launchd / systemd daemon setup
# ---------------------------------------------------------------------------

def _setup_daemon(project_root: Path) -> bool:
    """
    Install and start the Brain Daemon as a background service.
    Returns True if started successfully.
    """
    system = platform.system()

    if system == "Darwin":
        from sidequests.cli.launchd import write_plist, load_plist, is_loaded
        plist_path = write_plist()
        print(f"  [✓] launchd plist written: {plist_path}")
        if not is_loaded():
            if load_plist():
                print("  [✓] Brain Daemon started via launchd")
                return True
            else:
                print("  [!] launchctl load failed — try: launchctl load " + str(plist_path))
                return False
        else:
            print("  [=] Brain Daemon already running via launchd")
            return True

    elif system == "Linux":
        return _setup_systemd(project_root)

    else:
        print(f"  [!] Auto-start not supported on {system}.")
        print(f"      Run manually: python brain_daemon.py")
        return False


def _setup_systemd(project_root: Path) -> bool:
    """Write and enable a systemd user service on Linux."""
    service_dir  = Path.home() / ".config" / "systemd" / "user"
    service_path = service_dir / "sidequests-brain.service"
    service_dir.mkdir(parents=True, exist_ok=True)

    daemon_script = shutil.which("sidequests-daemon") or str(
        project_root / "brain_daemon.py"
    )
    if daemon_script.endswith(".py"):
        exec_start = f"{sys.executable} {daemon_script}"
    else:
        exec_start = daemon_script

    log_path = Path.home() / ".sidequests" / "daemon.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    service_content = f"""[Unit]
Description=SideQuests Brain Daemon
After=network.target

[Service]
Type=simple
ExecStart={exec_start}
WorkingDirectory={Path.home()}
Restart=always
RestartSec=5
StandardOutput=append:{log_path}
StandardError=append:{log_path}

[Install]
WantedBy=default.target
"""
    service_path.write_text(service_content)

    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    result = subprocess.run(
        ["systemctl", "--user", "enable", "--now", "sidequests-brain"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"  [✓] systemd service enabled: {service_path}")
        return True
    else:
        print(f"  [!] systemd enable failed: {result.stderr.strip()}")
        return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_setup(target: str, project_root: str | None) -> None:
    """
    Main setup orchestration.

    1. Resolve project root
    2. Detect / select target clients
    3. Ensure sidequests.toml exists
    4. Register selected adapters
    5. Setup daemon background service
    6. Run smoke test
    """
    from sidequests.cli.detect import detect_installed_clients

    root = Path(project_root).resolve() if project_root else Path.cwd()

    print(f"\nSideQuests Brain Setup")
    print(f"{'=' * 40}")
    print(f"Project root: {root}\n")

    if target == "all":
        installed = detect_installed_clients()
        targets = [name for name, present in installed.items() if present]
        if not targets:
            print("No AI clients detected. Install Claude Code, Codex, Gemini CLI, or OpenClaw.")
            print("You can also specify a target directly: sidequests setup --target claude-code")
        else:
            print(f"Detected: {', '.join(targets)}\n")
    else:
        targets = [target]

    _ensure_sidequests_toml(root)
    print()

    print("Registering adapters...")
    for t in targets:
        try:
            if t == "claude-code":
                _register_claude_code(root)
            elif t == "claude-desktop":
                _register_claude_desktop()
            elif t == "codex":
                _register_codex(root)
            elif t == "codex-desktop":
                _register_codex_desktop(root)
            elif t == "chatgpt-desktop":
                _register_chatgpt_desktop()
            elif t == "gemini-cli":
                _register_gemini_cli()
            elif t == "openclaw":
                _register_openclaw()
        except Exception as e:
            print(f"  [✗] {t}: {e}")

    print()

    print("Starting Brain Daemon...")
    _setup_daemon(root)
    print()

    print("Running smoke test...")
    import time
    time.sleep(2)
    try:
        from sidequests.cli.smoke_test import check_status
        check_status()
    except Exception as e:
        print(f"  [!] Smoke test error: {e}")
        print("      Try `sidequests status` once the daemon is running.")
