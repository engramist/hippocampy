"""Diagnostic and repair helpers for SideQuests installation."""

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


class DoctorChecker:
    """Run diagnostic checks and collect operator-facing results."""

    def __init__(self, repair_mode: bool = False):
        self.repair_mode = repair_mode
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
        return all(passed for _, passed, _ in self.checks)

    def _check_python_version(self) -> None:
        version = sys.version_info
        version_str = f"{version.major}.{version.minor}.{version.micro}"
        ok = version.major == 3 and 12 <= version.minor < 14
        msg = f"{version_str} (OK)" if ok else f"{version_str} (3.12-3.13 required)"
        self.checks.append(("Python Version", ok, msg))

    def _check_installation_mode(self) -> None:
        try:
            import sidequests

            package_path = Path(sidequests.__file__ or "").resolve()
            if "site-packages" in str(package_path):
                mode = "installed"
            else:
                mode = "editable/source"
            self.checks.append(("Installation Mode", True, mode))
        except Exception as exc:
            self.checks.append(("Installation Mode", False, f"Error: {exc}"))

    def _check_runtime_dir(self) -> None:
        try:
            from sidequests.paths import runtime_dir

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
            from sidequests.paths import get_config_path

            path = get_config_path()
            if not path.exists():
                if self.repair_mode:
                    self._repair_config_file(path)
                    with path.open("rb") as fh:
                        tomllib.load(fh)
                    self.checks.append(("Config File", True, f"{path} (created)"))
                else:
                    self.checks.append(("Config File", False, f"Missing: {path}"))
                return
            with path.open("rb") as fh:
                tomllib.load(fh)
            self.checks.append(("Config File", True, f"{path} (valid)"))
        except Exception as exc:
            self.checks.append(("Config File", False, f"Error: {exc}"))

    def _check_database(self) -> None:
        try:
            from sidequests.paths import get_database_path

            path = get_database_path()
            if path.exists():
                self.checks.append(("Database", True, f"{path} (exists)"))
            else:
                self.checks.append(("Database", True, f"{path} (will be created on first use)"))
        except Exception as exc:
            self.checks.append(("Database", False, f"Error: {exc}"))

    def _check_daemon(self) -> None:
        try:
            from sidequests.cli.smoke_test import check_status
            from sidequests.paths import get_daemon_socket_path

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
            from sidequests.paths import get_launchd_plist_path

            path = get_launchd_plist_path()
            if not path.exists():
                if self.repair_mode:
                    from sidequests.cli import launchd

                    launchd.PLIST_PATH = path
                    launchd.write_plist()
                    loaded = self._ensure_launchd_loaded(path)
                    self.checks.append(("Launchd", loaded, f"plist repaired: {path}"))
                else:
                    self.checks.append(("Launchd", False, f"plist missing: {path}"))
                return
            result = subprocess.run(
                ["launchctl", "list", "ai.sidequests.brain"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
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
        listed = subprocess.run(
            ["launchctl", "list", "ai.sidequests.brain"],
            capture_output=True,
            text=True,
        )
        if listed.returncode == 0:
            return True
        subprocess.run(
            ["launchctl", "load", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        listed = subprocess.run(
            ["launchctl", "list", "ai.sidequests.brain"],
            capture_output=True,
            text=True,
        )
        return listed.returncode == 0

    def _check_mcp_clients(self) -> None:
        ok: list[str] = []
        missing: list[str] = []

        codex_config = Path.home() / ".codex" / "config.toml"
        if codex_config.exists() and "sidequests" in codex_config.read_text().lower():
            ok.append("Codex")
        else:
            missing.append("Codex")

        claude_config = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        if claude_config.exists():
            try:
                if "sidequests" in json.dumps(json.loads(claude_config.read_text())).lower():
                    ok.append("Claude Desktop")
                else:
                    missing.append("Claude Desktop")
            except Exception:
                missing.append("Claude Desktop")
        else:
            missing.append("Claude Desktop")

        if ok:
            message = f"registered: {', '.join(ok)}"
            if missing:
                message += f"; not registered/found: {', '.join(missing)}"
            self.checks.append(("MCP Clients", True, message))
        else:
            self.checks.append(("MCP Clients", False, f"none registered; missing: {', '.join(missing)}"))

    def _repair_config_file(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        template = (
            resources.files("sidequests.data")
            .joinpath("config", "sidequests.toml")
            .read_text()
        )
        path.write_text(template)
        print(f"Created config: {path}")

    def print_report(self) -> None:
        print("\n=== SideQuests Health Check ===\n")
        print(f"{'Check':<24} {'Status':<6} Details")
        print("-" * 82)
        for name, passed, message in self.checks:
            print(f"{name:<24} {'PASS' if passed else 'FAIL':<6} {message}")
        print("-" * 82)
        passed_count = sum(1 for _, passed, _ in self.checks if passed)
        print(f"Result: {passed_count}/{len(self.checks)} checks passed")
        if passed_count == len(self.checks):
            print("All checks passed. SideQuests is healthy.")
        else:
            print("Some checks failed. Run 'sidequests doctor --repair' for safe repairs.")


def run_doctor(repair: bool = False, lines: int | None = None) -> bool:
    if repair:
        print("Running in repair mode...\n")
    checker = DoctorChecker(repair_mode=repair)
    ok = checker.run_all_checks()
    checker.print_report()

    if lines:
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
    """Run diagnostics and repair common SideQuests issues."""
    ok = run_doctor(repair=repair, lines=lines)
    if not ok:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
