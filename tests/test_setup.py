"""Tests for campy.cli.setup OpenClaw wiring."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_patch_openclaw_config_adds_plugin_and_tools(tmp_path):
    from campy.cli import setup as setup_mod

    config_path = tmp_path / "openclaw.json"
    config_path.write_text(json.dumps({"plugins": {}, "tools": {}}))

    setup_mod._patch_openclaw_config(config_path)

    config = json.loads(config_path.read_text())
    assert "hippocampy" in config["plugins"]["allow"]
    assert "group:plugins" in config["tools"]["sandbox"]["tools"]["alsoAllow"]
    for tool_name in setup_mod._OPENCLAW_MEMORY_TOOLS:
        assert tool_name in config["tools"]["sandbox"]["tools"]["allow"]


def test_patch_openclaw_config_is_idempotent(tmp_path):
    from campy.cli import setup as setup_mod

    config_path = tmp_path / "openclaw.json"
    config_path.write_text("{}")

    setup_mod._patch_openclaw_config(config_path)
    first = json.loads(config_path.read_text())
    setup_mod._patch_openclaw_config(config_path)
    second = json.loads(config_path.read_text())

    assert first == second


def test_register_openclaw_installs_patches_and_restarts(tmp_path):
    from campy.cli import setup as setup_mod

    config_path = tmp_path / "openclaw.json"
    extension_dir = tmp_path / "extensions" / "hippocampy"
    extension_dir.mkdir(parents=True)

    calls = []

    def fake_run(cmd, capture_output=False, text=False):
        calls.append(cmd)
        return MagicMock(returncode=0, stdout="group:plugins\nmemory_recall\nmemory_search\nmemory_get\nmemory_store\nmemory_search_analogies\nmemory_status\nmemory_open_loops\n", stderr="")

    with patch.object(setup_mod, "_OPENCLAW_CONFIG_PATH", config_path):
        with patch.object(setup_mod, "_OPENCLAW_EXTENSION_DIR", extension_dir):
            with patch("campy.cli.setup.shutil.which", return_value="/usr/local/bin/openclaw"):
                with patch("campy.cli.setup.subprocess.run", side_effect=fake_run):
                    setup_mod._register_openclaw()

    saved = json.loads(config_path.read_text())
    assert "hippocampy" in saved["plugins"]["allow"]
    assert any(cmd[:3] == ["/usr/local/bin/openclaw", "plugins", "install"] for cmd in calls)
    assert ["/usr/local/bin/openclaw", "gateway", "restart"] in calls
    assert ["/usr/local/bin/openclaw", "sandbox", "explain"] in calls


def test_register_openclaw_patches_config_before_install(tmp_path):
    from campy.cli import setup as setup_mod

    config_path = tmp_path / "openclaw.json"
    extension_dir = tmp_path / "extensions" / "hippocampy"
    extension_dir.mkdir(parents=True)

    def fake_run(cmd, capture_output=False, text=False):
        if cmd[:3] == ["/usr/local/bin/openclaw", "plugins", "install"]:
            saved = json.loads(config_path.read_text())
            assert "hippocampy" in saved["plugins"]["allow"]
        return MagicMock(
            returncode=0,
            stdout="group:plugins\nmemory_recall\nmemory_search\nmemory_get\nmemory_store\nmemory_search_analogies\nmemory_status\nmemory_open_loops\n",
            stderr="",
        )

    with patch.object(setup_mod, "_OPENCLAW_CONFIG_PATH", config_path):
        with patch.object(setup_mod, "_OPENCLAW_EXTENSION_DIR", extension_dir):
            with patch("campy.cli.setup.shutil.which", return_value="/usr/local/bin/openclaw"):
                with patch("campy.cli.setup.subprocess.run", side_effect=fake_run):
                    setup_mod._register_openclaw()


def test_detect_installed_clients_reports_openclaw():
    with patch("campy.cli.detect.shutil.which") as mock_which:
        mock_which.side_effect = lambda name: "/usr/local/bin/openclaw" if name == "openclaw" else None
        from campy.cli.detect import detect_installed_clients
        clients = detect_installed_clients()
        assert clients["openclaw"] is True
