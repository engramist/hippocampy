"""Diagnostic and repair helpers for Campy installation."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tomllib
from importlib import resources
from pathlib import Path

import typer
from campy.branding import (
    LEGACY_LAUNCHD_LABEL,
    LEGACY_LAUNCHD_LABELS,
    LEGACY_MCP_SERVER,
    PRIMARY_LAUNCHD_LABEL,
    PRIMARY_MCP_SERVER,
    PRODUCT_NAME,
)
from campy.paths import get_launchd_plist_path


class DoctorChecker:
    """Run diagnostic checks and collect operator-facing results."""

    def __init__(self, repair_mode: bool = False, json_mode: bool = False):
        self.repair_mode = repair_mode
        self.json_mode = json_mode
        self.checks: list[tuple[str, bool, str]] = []

    def run_all_checks(self) -> bool:
        self._check_python_version()
        self._check_installation_mode()
        self._check_runtime_dir()
        self._check_config_file()
        self._check_database()
        self._check_daemon()
        self._check_activity_log()
        self._check_launchd()
        self._check_mcp_clients()
        self._check_plugin_status()
        return all(passed for _, passed, _ in self.checks)

    def _check_python_version(self) -> None:
        version = sys.version_info
        version_str = f"{version.major}.{version.minor}.{version.micro}"
        ok = version.major == 3 and 12 <= version.minor < 14
        msg = f"{version_str} (OK)" if ok else f"{version_str} (3.12-3.13 required)"
        self.checks.append(("Python Version", ok, msg))

    def _check_installation_mode(self) -> None:
        try:
            import campy

            package_path = Path(campy.__file__ or "").resolve()
            if "site-packages" in str(package_path):
                mode = "installed"
            else:
                mode = "editable/source"
            self.checks.append(("Installation Mode", True, mode))
        except Exception as exc:
            self.checks.append(("Installation Mode", False, f"Error: {exc}"))

    def _check_runtime_dir(self) -> None:
        try:
            from campy.paths import runtime_dir

            path = runtime_dir()
            mode = path.stat().st_mode & 0o777
            if mode == 0o700:
                self.checks.append(("Runtime Dir", True, f"{path} (0700)"))
            else:
                if self.repair_mode:
                    os.chmod(path, 0o700)
                    self.checks.append(("Runtime Dir", True, f"{path} (repaired to 0700)"))
                else:
                    self.checks.append(("Runtime Dir", False, f"{path} ({mode:o}; expected 700)"))
        except Exception as exc:
            self.checks.append(("Runtime Dir", False, f"Error: {exc}"))

    def _check_config_file(self) -> None:
        try:
            from mcp_engine.config import load_config
            try:
                config = load_config()
                path_str = config.get("_config_path", "unknown")
                is_legacy = "sidequests.toml" in path_str or ".sidequests" in path_str
                msg = f"{path_str}"
                if is_legacy:
                    msg += " (LEGACY - recommend: cp sidequests.toml campy.toml)"
                self.checks.append(("Config File", True, msg))
            except FileNotFoundError:
                from campy.paths import get_config_path
                path = get_config_path()
                if self.repair_mode:
                    self._repair_config_file(path)
                    self.checks.append(("Config File", True, f"{path} (created)"))
                else:
                    self.checks.append(("Config File", False, f"Missing: campy.toml or {path}"))
        except Exception as exc:
            self.checks.append(("Config File", False, f"Error: {exc}"))

    def _check_database(self) -> None:
        try:
            from campy.paths import get_database_path

            path = get_database_path()
            if path.exists():
                self.checks.append(("Database", True, f"{path} (exists)"))
            else:
                self.checks.append(("Database", True, f"{path} (will be created on first use)"))
        except Exception as exc:
            self.checks.append(("Database", False, f"Error: {exc}"))

    def _check_daemon(self) -> None:
        try:
            from campy.cli.smoke_test import check_status
            from campy.paths import get_daemon_socket_path

            path = get_daemon_socket_path()
            if path.exists() and check_status():
                self.checks.append(("Daemon", True, f"responding at {path}"))
            else:
                self.checks.append(("Daemon", False, f"not responding at {path}"))
        except Exception as exc:
            self.checks.append(("Daemon", False, f"Error: {exc}"))

    def _check_activity_log(self) -> None:
        try:
            from mcp_engine.activity_log import activity_log_path
            from mcp_engine.config import load_config

            try:
                config = load_config()
            except Exception:
                config = {}
            path = activity_log_path(config)
            if path.exists():
                self.checks.append(("Activity Log", True, str(path)))
            else:
                self.checks.append(("Activity Log", True, f"{path} (will be created)"))
                if self.repair_mode:
                    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    path.touch(mode=0o600)
        except Exception as exc:
            self.checks.append(("Activity Log", False, f"Error: {exc}"))

    def _check_launchd(self) -> None:
        if platform.system() != "Darwin":
            self.checks.append(("Launchd", True, "not macOS"))
            return
        try:
            from campy.paths import get_launchd_plist_path, get_legacy_launchd_plist_path

            path = get_launchd_plist_path()
            legacy_path = get_legacy_launchd_plist_path()
            if not path.exists():
                if self.repair_mode:
                    from campy.cli import launchd

                    launchd.PLIST_PATH = path
                    launchd.write_plist()
                    loaded = self._ensure_launchd_loaded(path)
                    self.checks.append(("Launchd", loaded, f"plist repaired: {path}"))
                elif legacy_path.exists() and self._launchd_loaded(LEGACY_LAUNCHD_LABEL):
                    self.checks.append(("Launchd", True, f"legacy plist loaded: {legacy_path}"))
                else:
                    self.checks.append(("Launchd", False, f"plist missing: {path}"))
                return
            result = subprocess.run(
                ["launchctl", "list", PRIMARY_LAUNCHD_LABEL],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                if self.repair_mode:
                    from campy.cli.launchd import unload_plist

                    for legacy_label in LEGACY_LAUNCHD_LABELS:
                        legacy_path = get_launchd_plist_path(legacy_label)
                        if legacy_path.exists() or self._launchd_loaded(legacy_label):
                            unload_plist(legacy_label, legacy_path)
                self.checks.append(("Launchd", True, "plist loaded"))
            else:
                self.checks.append(("Launchd", False, "plist exists but is not loaded"))
                if self.repair_mode:
                    loaded = self._ensure_launchd_loaded(path)
                    self.checks[-1] = (
                        "Launchd",
                        loaded,
                        "plist loaded" if loaded else "plist exists but load failed",
                    )
        except Exception as exc:
            self.checks.append(("Launchd", False, f"Error: {exc}"))

    def _ensure_launchd_loaded(self, path: Path) -> bool:
        if self._launchd_loaded(PRIMARY_LAUNCHD_LABEL):
            return True
        for legacy_label in LEGACY_LAUNCHD_LABELS:
            legacy_path = get_launchd_plist_path(legacy_label)
            if legacy_path.exists() or self._launchd_loaded(legacy_label):
                from campy.cli.launchd import unload_plist

                unload_plist(legacy_label, legacy_path)
        subprocess.run(
            ["launchctl", "load", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        return self._launchd_loaded(PRIMARY_LAUNCHD_LABEL)

    def _launchd_loaded(self, label: str) -> bool:
        return subprocess.run(
            ["launchctl", "list", label],
            capture_output=True,
            text=True,
        ).returncode == 0

    def _check_mcp_clients(self) -> None:
        ok: list[str] = []
        missing: list[str] = []
        stale: list[str] = []

        # Codex
        codex_config = Path.home() / ".codex" / "config.toml"
        if codex_config.exists():
            content = codex_config.read_text()
            has_campy = f"[mcp_servers.{PRIMARY_MCP_SERVER}]" in content
            has_legacy = any(f"[mcp_servers.{name}]" in content for name in (LEGACY_MCP_SERVER, "sidequests-brain", "sidequests-brain-desktop"))
            has_stale_path = "sidequests.adapters" in content or "sidequests.cli" in content

            if has_campy and not has_stale_path and not has_legacy:
                ok.append("Codex")
            elif has_campy or has_legacy or has_stale_path:
                stale.append("Codex")
                if self.repair_mode:
                    from campy.cli.setup import _register_codex
                    from campy.paths import package_root
                    _register_codex(package_root().parent)
            else:
                missing.append("Codex")
        else:
            missing.append("Codex")

        # Claude Desktop
        claude_config = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        if claude_config.exists():
            try:
                content_raw = claude_config.read_text()
                config = json.loads(content_raw)
                servers = config.get("mcpServers", {})
                has_campy = PRIMARY_MCP_SERVER in servers
                has_legacy = any(name in servers for name in (LEGACY_MCP_SERVER, "sidequests-brain", "sidequests-brain-desktop"))
                has_stale_path = "sidequests.adapters" in content_raw or "sidequests.cli" in content_raw

                if has_campy and not has_stale_path and not has_legacy:
                    ok.append("Claude Desktop")
                elif has_campy or has_legacy or has_stale_path:
                    stale.append("Claude Desktop")
                    if self.repair_mode:
                        from campy.cli.register import register_claude_desktop
                        from campy.cli.detect import detect_claude_desktop
                        # Use a dummy adapter path as it will be ignored for module mode
                        register_claude_desktop("adapters/claude_desktop/adapter.py", detect_claude_desktop())
                else:
                    missing.append("Claude Desktop")
            except Exception:
                missing.append("Claude Desktop")
        else:
            missing.append("Claude Desktop")

        if ok:
            message = f"registered: {', '.join(ok)}"
            if stale:
                message += f"; stale/repaired: {', '.join(stale)}"
            if missing:
                message += f"; not found: {', '.join(missing)}"
            self.checks.append(("MCP Clients", not stale, message))
        else:
            self.checks.append(("MCP Clients", False, f"none registered; missing: {', '.join(missing)}"))

    def _repair_config_file(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        template = (
            resources.files("campy.data")
            .joinpath("config", "campy.toml")
            .read_text()
        )
        path.write_text(template)
        print(f"Created config: {path}")

    def _check_plugin_status(self) -> None:
        """Check if plugin is installed for detected agents."""
        try:
            from campy.cli.plugin_installer import find_plugin_dir
            from campy.cli.detect import detect_all

            plugin_dir = find_plugin_dir()
            if plugin_dir is None:
                self.checks.append(("Plugin Status", False, "Plugin directory not found"))
                return

            clients = detect_all()
            installed = []
            not_detected = []

            # Check Claude Code
            if clients.get("claude_code") or clients.get("claude-code"):
                target = Path.home() / ".claude" / "plugins" / "hippocampy"
                if (target / ".mcp.json").exists():
                    installed.append("Claude Code")
                else:
                    not_detected.append("Claude Code")

            # Check Codex
            if clients.get("codex"):
                skill = Path.home() / ".codex" / "skills" / "campy-memory" / "SKILL.md"
                if skill.exists():
                    installed.append("Codex")
                else:
                    not_detected.append("Codex")

            # Check VS Code
            if clients.get("vscode"):
                installed.append("VS Code (config OK)")

            # Check Gemini CLI
            if clients.get("gemini_cli") or clients.get("gemini-cli"):
                installed.append("Gemini CLI (config deferred)")

            if installed:
                message = f"installed: {', '.join(installed)}"
                if not_detected:
                    message += f"; not installed: {', '.join(not_detected)}"
                self.checks.append(("Plugin Status", not not_detected, message))
            else:
                self.checks.append(("Plugin Status", False, "no agents detected with plugin"))
        except Exception as exc:
            self.checks.append(("Plugin Status", False, f"Error: {exc}"))

    def print_report(self) -> None:
        if self.json_mode:
            self._print_json_report()
        else:
            self._print_text_report()

    def _print_json_report(self) -> None:
        """Output results as JSON for machine readability."""
        output = self.get_json_results()
        print(json.dumps(output, indent=2))

    def _print_text_report(self) -> None:
        """Output results as formatted text for human readability."""
        print(f"\n=== {PRODUCT_NAME} Health Check ===\n")
        print(f"{'Check':<24} {'Status':<6} Details")
        print("-" * 82)
        for name, passed, message in self.checks:
            print(f"{name:<24} {'PASS' if passed else 'FAIL':<6} {message}")
        print("-" * 82)
        passed_count = sum(1 for _, passed, _ in self.checks if passed)
        print(f"Result: {passed_count}/{len(self.checks)} checks passed")
        if passed_count == len(self.checks):
            print(f"All checks passed. {PRODUCT_NAME} is healthy.")
        else:
            print("Some checks failed. Run 'campy doctor --repair' for safe repairs.")

    def get_json_results(self) -> dict:
        """Return check results as a dict suitable for JSON serialization."""
        checks_list = [
            {
                "name": name,
                "status": "pass" if passed else "fail",
                "message": message,
            }
            for name, passed, message in self.checks
        ]
        passed_count = sum(1 for _, passed, _ in self.checks if passed)
        return {
            "checks": checks_list,
            "summary": {
                "passed": passed_count,
                "total": len(self.checks),
                "all_passed": passed_count == len(self.checks),
            },
        }


def run_doctor(repair: bool = False, lines: int | None = None, json_output: bool = False) -> bool:
    if repair and not json_output:
        print("Running in repair mode...\n")
    
    # When json_output is enabled, suppress diagnostic prints from check_status() etc.
    if json_output:
        import io
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            checker = DoctorChecker(repair_mode=repair, json_mode=json_output)
            ok = checker.run_all_checks()
    else:
        checker = DoctorChecker(repair_mode=repair, json_mode=json_output)
        ok = checker.run_all_checks()
    
    checker.print_report()

    if lines and not json_output:
        print("\n=== Recent Activity ===\n")
        try:
            from mcp_engine.activity_log import activity_log_path
            from mcp_engine.config import load_config

            try:
                config = load_config()
            except Exception:
                config = {}
            path = activity_log_path(config)
            if path.exists():
                for line in path.read_text().splitlines()[-lines:]:
                    print(line)
            else:
                print(f"No activity log found at {path}")
        except Exception as exc:
            print(f"Could not read activity log: {exc}")
    return ok


app = typer.Typer(add_completion=False)


@app.callback(invoke_without_command=True)
def doctor(
    repair: bool = typer.Option(False, "--repair", help="Attempt safe repairs"),
    lines: int | None = typer.Option(None, "--lines", help="Show last N activity lines"),
) -> None:
    """Run diagnostics and repair common Campy issues."""
    ok = run_doctor(repair=repair, lines=lines)
    if not ok:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
