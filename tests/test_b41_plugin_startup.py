"""
tests/test_b41_plugin_startup.py

Validates B41: OpenClaw plugin startup warning improvements.
- isDaemonServiceInstalled() distinguishes macOS/Linux/other
- Plugin start() logic handles alive vs service-not-installed vs transient-down
- autoLaunch config is present and disabled by default
"""

from pathlib import Path
import re

EXTENSION_SRC = (
    Path(__file__).parent.parent
    / "extensions"
    / "sidequests-brain"
    / "src"
    / "index.ts"
)


def _source() -> str:
    return EXTENSION_SRC.read_text()


# ---------------------------------------------------------------------------
# Service detection helpers
# ---------------------------------------------------------------------------

def test_is_launchd_service_installed_checks_plist_path():
    src = _source()
    assert "isLaunchdServiceInstalled" in src
    # Must reference the correct plist label
    assert "ai.sidequests.brain.plist" in src


def test_is_systemd_service_installed_checks_unit_path():
    src = _source()
    assert "isSystemdServiceInstalled" in src
    assert "sidequests-brain.service" in src


def test_is_daemon_service_installed_dispatches_by_platform():
    src = _source()
    assert "isDaemonServiceInstalled" in src
    # Should branch on darwin and linux
    assert "darwin" in src
    assert "linux" in src


def test_is_daemon_service_installed_returns_false_for_other_platforms():
    src = _source()
    # When platform is not darwin or linux, should return false
    # We check that the function has a final `return false` fallback
    fn_block = src[src.index("function isDaemonServiceInstalled"):]
    fn_block = fn_block[:fn_block.index("\n}\n", fn_block.index("{")) + 3]
    assert "return false" in fn_block


# ---------------------------------------------------------------------------
# Config: autoLaunch is opt-in and disabled by default
# ---------------------------------------------------------------------------

def test_autolaunch_config_defaults_to_false():
    src = _source()
    assert "autoLaunch" in src
    assert "autoLaunch: api.pluginConfig?.autoLaunch ?? false" in src


def test_autolaunch_interface_field_defined():
    src = _source()
    # autoLaunch should be in BrainConfig interface
    config_block = src[src.index("interface BrainConfig"):]
    config_block = config_block[:config_block.index("\n}")]
    assert "autoLaunch" in config_block


# ---------------------------------------------------------------------------
# Plugin start() — warning messages
# ---------------------------------------------------------------------------

def test_start_distinguishes_service_not_installed():
    src = _source()
    # Should emit a message pointing to sidequests install when service is not found
    assert "no persistent service found" in src
    assert "sidequests install" in src


def test_start_distinguishes_transient_down():
    src = _source()
    # Should emit a different message when service IS installed but not reachable
    assert "service is registered but not currently reachable" in src
    assert "sidequests status" in src


def test_start_connects_silently_when_alive():
    src = _source()
    # When alive, should log success without warnings
    assert "Connected to Brain Daemon at" in src
    assert "Streamable HTTP" in src


def test_start_checks_service_installed_when_not_alive():
    src = _source()
    # isDaemonServiceInstalled should be called inside start()
    start_fn = src[src.index("async start()"):]
    start_fn = start_fn[:start_fn.index("async stop()")]
    assert "isDaemonServiceInstalled" in start_fn


# ---------------------------------------------------------------------------
# Auto-launch fallback
# ---------------------------------------------------------------------------

def test_autolaunching_is_guarded_by_cfg_autlaunch():
    src = _source()
    assert "cfg.autoLaunch" in src


def test_autolaunching_only_when_service_not_installed():
    src = _source()
    # autoLaunch fallback should only trigger when service is NOT installed
    assert "cfg.autoLaunch && !serviceInstalled" in src


def test_autolaunching_attempts_sidequests_daemon_first():
    src = _source()
    assert "sidequests-daemon" in src


def test_autolaunching_falls_back_to_python3():
    src = _source()
    assert "python3" in src
    assert '"-m", "sidequests.daemon"' in src


def test_autolaunching_uses_detached_spawn():
    src = _source()
    assert "detached: true" in src


def test_autolaunching_retries_ping_after_launch():
    src = _source()
    assert "retryAlive" in src
    assert "Auto-launch succeeded" in src


# ---------------------------------------------------------------------------
# fs / os / path imports for service detection
# ---------------------------------------------------------------------------

def test_imports_fs_os_path():
    src = _source()
    assert 'import * as fs from "fs"' in src
    assert 'import * as os from "os"' in src
    assert 'import * as path from "path"' in src


def test_uses_os_homedir_for_service_paths():
    src = _source()
    assert "os.homedir()" in src


def test_uses_fs_existssync():
    src = _source()
    assert "fs.existsSync" in src
