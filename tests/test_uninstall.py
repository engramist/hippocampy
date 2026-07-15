"""
tests/test_uninstall.py — Tests for `sidequests uninstall` (B19).

Covers:
  - MCP JSON entry removal from Claude Code / Claude Desktop / Gemini CLI configs
  - Codex TOML block removal
  - Claude UserPromptSubmit hook removal
  - OpenClaw config patch reversal
  - Database / ~/.sidequests deletion
  - Ollama model removal (mocked)
  - CLI command: --keep-data / --delete-data flags
  - Idempotency: safe to run when nothing is registered
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner


# ---------------------------------------------------------------------------
# Helper import — load module under test
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from campy.cli import uninstall as U
from campy.cli.main import app as cli


# ---------------------------------------------------------------------------
# JSON MCP entry removal
# ---------------------------------------------------------------------------

class TestRemoveMcpJsonEntry:
    def test_removes_existing_entry(self, tmp_path):
        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps({
            "mcpServers": {
                "hippocampy": {"command": "python"},
                "other-tool": {"command": "node"},
            }
        }))
        changed = U._remove_mcp_json_entry(cfg)
        assert changed
        data = json.loads(cfg.read_text())
        assert "hippocampy" not in data["mcpServers"]
        assert "other-tool" in data["mcpServers"]  # other entries preserved

    def test_noop_when_entry_absent(self, tmp_path):
        cfg = tmp_path / "cfg.json"
        cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
        changed = U._remove_mcp_json_entry(cfg)
        assert not changed

    def test_noop_when_file_missing(self, tmp_path):
        changed = U._remove_mcp_json_entry(tmp_path / "nonexistent.json")
        assert not changed

    def test_noop_on_corrupt_json(self, tmp_path):
        cfg = tmp_path / "cfg.json"
        cfg.write_text("not valid json {{{")
        changed = U._remove_mcp_json_entry(cfg)
        assert not changed

    def test_created_only_preserves_user_managed_http_entry(self, tmp_path):
        """Regression: uninstall must not strip a hand-authored campy entry
        (e.g. HTTP to the daemon) from a git-tracked project .mcp.json,
        leaving behind an empty mcpServers map."""
        cfg = tmp_path / ".mcp.json"
        original = {
            "mcpServers": {
                "campy": {"type": "http", "url": "http://127.0.0.1:7799/mcp"},
            }
        }
        cfg.write_text(json.dumps(original))
        changed = U._remove_mcp_json_entry(cfg, created_only=True)
        assert not changed
        assert json.loads(cfg.read_text()) == original

    def test_created_only_still_removes_campy_created_entry(self, tmp_path):
        cfg = tmp_path / ".mcp.json"
        cfg.write_text(json.dumps({
            "mcpServers": {
                "campy": {
                    "command": "/some/venv/bin/python",
                    "args": ["-m", "campy.adapters.mcp_server"],
                },
                "other-tool": {"command": "node"},
            }
        }))
        changed = U._remove_mcp_json_entry(cfg, created_only=True)
        assert changed
        data = json.loads(cfg.read_text())
        assert "campy" not in data["mcpServers"]
        assert "other-tool" in data["mcpServers"]


# ---------------------------------------------------------------------------
# Codex TOML block removal
# ---------------------------------------------------------------------------

class TestRemoveCodexTomlEntry:
    def test_removes_block(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            "[other]\nkey = \"val\"\n\n[mcp_servers.campy]\n"
            "command = \"python3\"\nargs = [\"/path/adapter.py\"]\n"
        )
        changed = U._remove_codex_toml_entry(cfg)
        assert changed
        text = cfg.read_text()
        assert "mcp_servers.campy" not in text
        assert "[other]" in text  # other sections preserved

    def test_noop_when_block_absent(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text("[other]\nkey = \"val\"\n")
        changed = U._remove_codex_toml_entry(cfg)
        assert not changed

    def test_noop_when_file_missing(self, tmp_path):
        changed = U._remove_codex_toml_entry(tmp_path / "nonexistent.toml")
        assert not changed


# ---------------------------------------------------------------------------
# Claude hook removal
# ---------------------------------------------------------------------------

class TestRemoveClaudeHook:
    def test_removes_hook_entry(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({
            "hooks": {
                "UserPromptSubmit": [
                    {"hooks": [{"command": "python hook_user_turn.py"}]},
                    {"hooks": [{"command": "other_hook.py"}]},
                ]
            }
        }))
        changed = U._remove_claude_hook(settings)
        assert changed
        data = json.loads(settings.read_text())
        remaining = data["hooks"]["UserPromptSubmit"]
        assert len(remaining) == 1
        assert "other_hook.py" in json.dumps(remaining)

    def test_noop_when_hook_absent(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": {"UserPromptSubmit": []}}))
        changed = U._remove_claude_hook(settings)
        assert not changed

    def test_noop_when_file_missing(self, tmp_path):
        changed = U._remove_claude_hook(tmp_path / "nonexistent.json")
        assert not changed


class TestRemoveAgentHookEntries:
    def test_removes_codex_hook_entries(self, tmp_path):
        hooks = tmp_path / "hooks.json"
        hooks.write_text(json.dumps({
            "hooks": {
                "PreToolUse": [
                    {"hooks": [{"command": "python3 /Users/me/.codex/hooks/campy/pre_tool_use.py"}]},
                    {"hooks": [{"command": "python3 /tmp/other_hook.py"}]},
                ]
            }
        }))

        changed = U._remove_codex_hooks(hooks)

        assert changed
        data = json.loads(hooks.read_text())
        remaining = data["hooks"]["PreToolUse"]
        assert len(remaining) == 1
        assert "other_hook.py" in json.dumps(remaining)

    def test_removes_gemini_hook_entries(self, tmp_path):
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({
            "hooks": {
                "BeforeTool": [
                    {"hooks": [{"name": "campy-before-tool", "command": "python3 /Users/me/.gemini/hooks/campy/before_tool.py"}]},
                    {"hooks": [{"name": "other-hook", "command": "python3 /tmp/other_hook.py"}]},
                ]
            }
        }))

        changed = U._remove_gemini_hooks(settings)

        assert changed
        data = json.loads(settings.read_text())
        remaining = data["hooks"]["BeforeTool"]
        assert len(remaining) == 1
        assert "other-hook" in json.dumps(remaining)


# ---------------------------------------------------------------------------
# OpenClaw config patch reversal
# ---------------------------------------------------------------------------

class TestDeregisterOpenclaw:
    def test_reverses_config_patches(self, tmp_path, monkeypatch):
        config_path = tmp_path / "openclaw.json"
        config_path.write_text(json.dumps({
            "plugins": {"allow": ["hippocampy", "other-plugin"]},
            "tools": {
                "sandbox": {
                    "tools": {
                        "alsoAllow": ["group:plugins"],
                        "allow": [
                            "memory_recall", "memory_search", "memory_get",
                            "memory_store", "memory_search_analogies",
                            "memory_status", "memory_open_loops",
                            "some_other_tool",
                        ]
                    }
                }
            }
        }))

        monkeypatch.setattr(U, "_OPENCLAW_CONFIG_PATH", config_path)
        monkeypatch.setattr("shutil.which", lambda name: None)  # no openclaw binary

        result = U._deregister_openclaw()
        assert result.done

        data = json.loads(config_path.read_text())
        # hippocampy removed from plugins.allow
        assert "hippocampy" not in data["plugins"]["allow"]
        # other plugin preserved
        assert "other-plugin" in data["plugins"]["allow"]
        # memory tools removed from sandbox allow
        sandbox_allow = data["tools"]["sandbox"]["tools"]["allow"]
        for tool in U._OPENCLAW_MEMORY_TOOLS:
            assert tool not in sandbox_allow
        # non-sidequests tool preserved
        assert "some_other_tool" in sandbox_allow
        # alsoAllow preserved (other plugins might need it)
        assert "group:plugins" in data["tools"]["sandbox"]["tools"]["alsoAllow"]

    def test_noop_when_config_absent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(U, "_OPENCLAW_CONFIG_PATH", tmp_path / "nonexistent.json")
        monkeypatch.setattr("shutil.which", lambda name: None)
        result = U._deregister_openclaw()
        assert result.done


# ---------------------------------------------------------------------------
# Database removal
# ---------------------------------------------------------------------------

class TestRemoveDatabase:
    def test_keeps_when_keep_data_true(self, tmp_path, monkeypatch):
        db = tmp_path / "brain.db"
        db.write_text("fake db")
        monkeypatch.setattr(U, "DB_PATH", db)
        result = U._remove_database(keep_data=True)
        assert result.done
        assert db.exists()  # not deleted

    def test_deletes_file_when_keep_data_false(self, tmp_path, monkeypatch):
        db = tmp_path / "brain.db"
        db.write_text("fake db")
        monkeypatch.setattr(U, "DB_PATH", db)
        result = U._remove_database(keep_data=False)
        assert result.done
        assert not db.exists()

    def test_deletes_dir_when_keep_data_false(self, tmp_path, monkeypatch):
        db = tmp_path / "brain.db"
        db.mkdir()
        (db / "data.kz").write_text("fake")
        monkeypatch.setattr(U, "DB_PATH", db)
        result = U._remove_database(keep_data=False)
        assert result.done
        assert not db.exists()

    def test_noop_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(U, "DB_PATH", tmp_path / "missing.db")
        result = U._remove_database(keep_data=False)
        assert result.done


# ---------------------------------------------------------------------------
# Sidequests home removal
# ---------------------------------------------------------------------------

class TestRemoveSideQuestsHome:
    def test_deletes_tree(self, tmp_path, monkeypatch):
        home = tmp_path / ".sidequests"
        home.mkdir()
        (home / "brain.db").write_text("data")
        monkeypatch.setattr(U, "SIDEQUESTS_HOME", home)
        result = U._remove_sidequests_home(keep_data=False)
        assert result.done
        assert not home.exists()

    def test_keeps_when_keep_data_true(self, tmp_path, monkeypatch):
        home = tmp_path / ".sidequests"
        home.mkdir()
        monkeypatch.setattr(U, "SIDEQUESTS_HOME", home)
        result = U._remove_sidequests_home(keep_data=True)
        assert result.done
        assert home.exists()


class TestRemoveSkillDirs:
    def test_removes_known_skill_directories(self, tmp_path):
        skills_root = tmp_path / "skills"
        skills_root.mkdir()
        (skills_root / "recall").mkdir()
        (skills_root / "campy-grill").mkdir()
        (skills_root / "custom-skill").mkdir()

        removed = U._remove_skill_dirs(skills_root)

        assert removed == 2
        assert not (skills_root / "recall").exists()
        assert not (skills_root / "campy-grill").exists()
        assert (skills_root / "custom-skill").exists()


# ---------------------------------------------------------------------------
# Ollama model removal
# ---------------------------------------------------------------------------

class TestRemoveOllamaModel:
    def test_removes_model(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/ollama")
        mock_run = MagicMock(return_value=MagicMock(returncode=0, stderr="", stdout=""))
        monkeypatch.setattr(subprocess, "run", mock_run)
        result = U._remove_ollama_model("qwen2.5:3b")
        assert result.done
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "rm" in call_args
        assert "qwen2.5:3b" in call_args

    def test_noop_when_model_not_found(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/ollama")
        mock_run = MagicMock(return_value=MagicMock(
            returncode=1, stderr="model not found", stdout=""
        ))
        monkeypatch.setattr(subprocess, "run", mock_run)
        result = U._remove_ollama_model("qwen2.5:3b")
        assert result.done  # graceful skip

    def test_noop_when_ollama_missing(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: None)
        result = U._remove_ollama_model("qwen2.5:3b")
        assert result.done


class TestRemovePythonPackage:
    def test_reports_removed_package(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/pipx" if name == "pipx" else None)

        def fake_run(cmd, **kwargs):
            if cmd[0] == "/usr/local/bin/pipx":
                return MagicMock(returncode=0, stdout="uninstalled", stderr="")
            return MagicMock(returncode=0, stdout="Successfully uninstalled hippocampy", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = U._remove_python_package()

        assert result.done
        assert "removed via" in result.detail

    def test_reports_skip_when_not_installed(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: None)

        def fake_run(cmd, **kwargs):
            return MagicMock(returncode=1, stdout="WARNING: Skipping hippocampy as it is not installed.", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        result = U._remove_python_package()

        assert result.done
        assert "not installed" in result.detail or "skipped" in result.detail


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

class TestUninstallCli:
    def _make_runner(self):
        return CliRunner()

    def test_requires_confirmation_by_default(self, monkeypatch):
        runner = self._make_runner()
        # Decline confirmation
        result = runner.invoke(cli, ["uninstall"], input="n\n")
        # Should abort without error exit code 1 (click Abort)
        assert result.exit_code != 0 or "Aborted" in (result.output or "")

    def test_yes_flag_skips_confirmation(self, monkeypatch):
        called_with = {}

        def fake_run_uninstall(**kwargs):
            called_with.update(kwargs)

        monkeypatch.setattr("campy.cli.uninstall.run_uninstall", fake_run_uninstall)

        runner = self._make_runner()
        result = runner.invoke(cli, ["uninstall", "--yes"])
        assert result.exit_code == 0
        assert called_with.get("keep_data") is True
        assert called_with.get("remove_ollama_model") is False

    def test_delete_data_flag(self, monkeypatch):
        called_with = {}

        def fake_run_uninstall(**kwargs):
            called_with.update(kwargs)

        monkeypatch.setattr("campy.cli.uninstall.run_uninstall", fake_run_uninstall)

        runner = self._make_runner()
        result = runner.invoke(cli, ["uninstall", "--yes", "--delete-data"])
        assert result.exit_code == 0
        assert called_with.get("keep_data") is False

    def test_remove_ollama_model_flag(self, monkeypatch):
        called_with = {}

        def fake_run_uninstall(**kwargs):
            called_with.update(kwargs)

        monkeypatch.setattr("campy.cli.uninstall.run_uninstall", fake_run_uninstall)

        runner = self._make_runner()
        result = runner.invoke(cli, [
            "uninstall", "--yes", "--remove-ollama-model", "--ollama-model", "llama3.1:8b"
        ])
        assert result.exit_code == 0
        assert called_with.get("remove_ollama_model") is True
        assert called_with.get("ollama_model") == "llama3.1:8b"

    def test_force_alias_skips_confirmation(self, monkeypatch):
        called_with = {}

        def fake_run_uninstall(**kwargs):
            called_with.update(kwargs)

        monkeypatch.setattr("campy.cli.uninstall.run_uninstall", fake_run_uninstall)

        runner = self._make_runner()
        result = runner.invoke(cli, ["uninstall", "--force"])
        assert result.exit_code == 0
        assert called_with.get("keep_data") is True


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    """run_uninstall should not raise even when nothing is registered."""

    def test_idempotent_run(self, tmp_path, monkeypatch):
        """Running uninstall with nothing registered completes without errors."""
        monkeypatch.setattr(U, "SIDEQUESTS_HOME", tmp_path / ".sidequests")
        monkeypatch.setattr(U, "DB_PATH", tmp_path / "brain.db")
        monkeypatch.setattr(U, "_OPENCLAW_CONFIG_PATH", tmp_path / "openclaw.json")

        # Patch out launchd calls
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: MagicMock(returncode=0, stderr="", stdout=""))
        monkeypatch.setattr("shutil.which", lambda name: None)

        # Should not raise
        U.run_uninstall(keep_data=True, remove_ollama_model=False)
