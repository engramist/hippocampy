"""
tests/test_install.py — Tests for sidequests install command.

All external operations are mocked:
- subprocess.run (Homebrew, Ollama, pip, spaCy, launchctl)
- urllib.request.urlopen (Ollama health check)
- click.prompt (user input)
- File I/O (config files, plist)
- OpenAI client (BYOK validation)
"""

import sys
import os
import json
import pytest
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, call

# Ensure the project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

class TestOllamaInstaller:

    def test_is_installed_true(self):
        """Returns True when ollama is in PATH."""
        with patch("shutil.which", return_value="/opt/homebrew/bin/ollama"):
            from campy.cli.install import OllamaInstaller
            assert OllamaInstaller.is_installed() is True

    def test_is_installed_false(self):
        """Returns False when ollama is not in PATH."""
        with patch("shutil.which", return_value=None):
            from campy.cli.install import OllamaInstaller
            assert OllamaInstaller.is_installed() is False

    def test_is_running_true(self):
        """Returns True when Ollama server responds."""
        with patch("urllib.request.urlopen") as mock_url:
            mock_url.return_value.__enter__ = lambda s: s
            mock_url.return_value.__exit__ = MagicMock(return_value=False)
            from campy.cli.install import OllamaInstaller
            assert OllamaInstaller.is_running() is True

    def test_is_running_false(self):
        """Returns False when Ollama server is unreachable."""
        with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError):
            from campy.cli.install import OllamaInstaller
            assert OllamaInstaller.is_running() is False

    def test_has_model_true(self):
        """Returns True when model appears in ollama list output."""
        mock_result = MagicMock(stdout="NAME\nllama3.1:8b\n", returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            from campy.cli.install import OllamaInstaller
            assert OllamaInstaller.has_model("llama3.1:8b") is True

    def test_has_model_false(self):
        """Returns False when model not in ollama list output."""
        mock_result = MagicMock(stdout="NAME\nmistral:7b\n", returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            from campy.cli.install import OllamaInstaller
            assert OllamaInstaller.has_model("llama3.1:8b") is False

    # The Darwin-branch tests pin platform.system just like the Linux-branch
    # tests below already do — install() branches on it first, so on a Linux
    # CI runner an unpinned test exercises the wrong code path entirely.

    def test_install_no_homebrew(self):
        """Returns False and prints message when brew not available."""
        with patch("platform.system", return_value="Darwin"):
            with patch("shutil.which", return_value=None):
                from campy.cli.install import OllamaInstaller
                inst = OllamaInstaller()
                assert inst.install() is False

    def test_install_brew_succeeds(self):
        """Returns True when brew install ollama succeeds."""
        def which_side_effect(name):
            if name == "brew":
                return "/opt/homebrew/bin/brew"
            if name == "ollama":
                return "/opt/homebrew/bin/ollama"
            return None

        with patch("platform.system", return_value="Darwin"):
            with patch("shutil.which", side_effect=which_side_effect):
                mock_result = MagicMock(returncode=0)
                with patch("subprocess.run", return_value=mock_result):
                    from campy.cli.install import OllamaInstaller
                    inst = OllamaInstaller()
                    assert inst.install() is True

    def test_install_brew_fails(self):
        """Returns False when brew install returns non-zero."""
        def which_side_effect(name):
            return "/opt/homebrew/bin/brew" if name == "brew" else None

        with patch("platform.system", return_value="Darwin"):
            with patch("shutil.which", side_effect=which_side_effect):
                mock_result = MagicMock(returncode=1, stderr="Error")
                with patch("subprocess.run", return_value=mock_result):
                    from campy.cli.install import OllamaInstaller
                    inst = OllamaInstaller()
                    assert inst.install() is False

    def test_install_linux_apt(self):
        """Uses apt-get on Linux when available."""
        def which_side_effect(name):
            if name == "apt-get": return "/usr/bin/apt-get"
            if name == "ollama": return "/usr/local/bin/ollama"
            return None

        with patch("platform.system", return_value="Linux"):
            with patch("shutil.which", side_effect=which_side_effect):
                with patch("subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0)
                    from campy.cli.install import OllamaInstaller
                    inst = OllamaInstaller()
                    assert inst.install() is True
                    # Should call update and install
                    mock_run.assert_any_call(["sudo", "apt-get", "update"], check=True)
                    mock_run.assert_any_call(["sudo", "apt-get", "install", "-y", "ollama"], check=True)

    def test_install_linux_no_pkg_manager(self):
        """Returns False on Linux when no supported package manager found."""
        with patch("platform.system", return_value="Linux"):
            with patch("shutil.which", return_value=None):
                from campy.cli.install import OllamaInstaller
                inst = OllamaInstaller()
                assert inst.install() is False

    def test_pull_model_already_exists(self):
        """Skips pull when model already available."""
        mock_result = MagicMock(stdout="NAME\nllama3.1:8b\n", returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            from campy.cli.install import OllamaInstaller
            inst = OllamaInstaller()
            assert inst.pull_model("llama3.1:8b") is True

    def test_pull_model_download(self):
        """Pulls model when not already available."""
        call_count = [0]
        def run_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:  # ollama list
                return MagicMock(stdout="NAME\n", returncode=0)
            return MagicMock(returncode=0)  # ollama pull

        with patch("subprocess.run", side_effect=run_side_effect):
            from campy.cli.install import OllamaInstaller
            inst = OllamaInstaller()
            assert inst.pull_model("llama3.1:8b") is True

class TestBYOKValidator:

    def test_validate_key_success(self):
        """Returns True when API call succeeds."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock()

        with patch("campy.cli.install.OpenAI", return_value=mock_client):
            from campy.cli.install import BYOKValidator
            v = BYOKValidator()
            assert v.validate_key("openai", "sk-test123") is True

    def test_validate_key_auth_error(self):
        """Returns False on authentication error."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("401 Unauthorized")

        with patch("campy.cli.install.OpenAI", return_value=mock_client):
            from campy.cli.install import BYOKValidator
            v = BYOKValidator()
            assert v.validate_key("openai", "bad-key") is False

    def test_prompt_api_key_from_env(self, monkeypatch):
        """Uses env var when user confirms."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        with patch("click.confirm", return_value=True):
            from campy.cli.install import BYOKValidator
            v = BYOKValidator()
            assert v.prompt_api_key("openai") == "sk-from-env"

    def test_prompt_api_key_manual(self, monkeypatch):
        """Prompts manually when env var not set."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("click.prompt", return_value="sk-manual"):
            from campy.cli.install import BYOKValidator
            v = BYOKValidator()
            assert v.prompt_api_key("openai") == "sk-manual"

class TestVenvManager:

    def test_exists_true(self, tmp_path):
        """Returns True when venv python3 binary exists."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        from campy.cli.install import VenvManager
        vm = VenvManager(venv_dir=tmp_path)
        assert vm.exists() is True

    def test_exists_false(self, tmp_path):
        """Returns False when venv does not exist."""
        from campy.cli.install import VenvManager
        vm = VenvManager(venv_dir=tmp_path / "nonexistent")
        assert vm.exists() is False

    def test_create_skips_existing(self, tmp_path):
        """Skips creation when venv already exists."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        from campy.cli.install import VenvManager
        vm = VenvManager(venv_dir=tmp_path)
        assert vm.create() is True

    def test_create_new_venv(self, tmp_path):
        """Creates venv when it does not exist."""
        venv_dir = tmp_path / "new_venv"
        mock_result = MagicMock(returncode=0)

        with patch("subprocess.run", return_value=mock_result):
            from campy.cli.install import VenvManager
            vm = VenvManager(venv_dir=venv_dir)
            # Simulate that venv python appears after creation
            with patch.object(vm, "exists", side_effect=[False, True]):
                # Need to create the bin dir to make final check pass
                (venv_dir / "bin").mkdir(parents=True)
                (venv_dir / "bin" / "python3").touch()
                assert vm.create() is True

    def test_install_deps_success(self, tmp_path):
        """Returns True when pip install succeeds."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        (tmp_path / "bin" / "pip3").touch()
        mock_result = MagicMock(returncode=0)

        with patch("subprocess.run", return_value=mock_result):
            from campy.cli.install import VenvManager
            vm = VenvManager(venv_dir=tmp_path)
            assert vm.install_deps() is True

    def test_install_deps_pip_failure(self, tmp_path):
        """Returns False when pip install fails."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "pip3").touch()
        mock_result = MagicMock(returncode=1, stderr="ERROR: No matching distribution")

        with patch("subprocess.run", return_value=mock_result):
            from campy.cli.install import VenvManager
            vm = VenvManager(venv_dir=tmp_path)
            assert vm.install_deps() is False

    def test_install_spacy_already_present(self, tmp_path):
        """Skips download when model already installed."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        mock_result = MagicMock(returncode=0)

        with patch("subprocess.run", return_value=mock_result):
            from campy.cli.install import VenvManager
            vm = VenvManager(venv_dir=tmp_path)
            assert vm.install_spacy_model() is True

    def test_prewarm_embeddings_success(self, tmp_path):
        """Returns True when embedding pre-warm succeeds."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        mock_result = MagicMock(returncode=0)

        with patch("subprocess.run", return_value=mock_result):
            from campy.cli.install import VenvManager
            vm = VenvManager(venv_dir=tmp_path)
            assert vm.prewarm_embeddings() is True

class TestConfigWriter:

    def test_write_ollama_config(self, tmp_path):
        """Writes correct config for Ollama provider."""
        config_path = tmp_path / "config.toml"
        from campy.cli.install import ConfigWriter
        ConfigWriter.write(
            {"provider": "ollama", "model": "llama3.1:8b"},
            config_path=config_path
        )
        content = config_path.read_text()
        assert 'provider = "ollama"' in content
        assert 'model = "llama3.1:8b"' in content
        assert "[capture]" in content
        assert "[capture.codex]" in content
        assert "[capture.claude_code]" in content
        assert "[capture.vscode]" in content
        assert "max_initial_backfill_files = 1" in content

    def test_write_byok_config(self, tmp_path):
        """Writes correct config for cloud provider."""
        config_path = tmp_path / "config.toml"
        from campy.cli.install import ConfigWriter
        with patch("campy.cli.install.SIDEQUESTS_HOME", tmp_path):
            ConfigWriter.write(
                {"provider": "openai", "model": "gpt-4o-mini",
                 "api_key": "sk-test", "env_var": "OPENAI_API_KEY"},
                config_path=config_path
            )
        content = config_path.read_text()
        assert 'provider = "openai"' in content
        assert 'model = "gpt-4o-mini"' in content
        # API key should NOT be in the TOML
        assert "sk-test" not in content

    def test_write_creates_env_file(self, tmp_path, monkeypatch):
        """Creates .env file with API key for BYOK providers."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        config_path = tmp_path / "config.toml"
        with patch("campy.cli.install.SIDEQUESTS_HOME", tmp_path):
            from campy.cli.install import ConfigWriter
            ConfigWriter.write(
                {"provider": "openai", "model": "gpt-4o-mini",
                 "api_key": "sk-secret", "env_var": "OPENAI_API_KEY"},
                config_path=config_path
            )
        env_file = tmp_path / ".env"
        assert env_file.exists()
        assert "sk-secret" in env_file.read_text()

    def test_write_idempotent(self, tmp_path):
        """Running write twice does not corrupt the file."""
        config_path = tmp_path / "config.toml"
        from campy.cli.install import ConfigWriter
        ConfigWriter.write(
            {"provider": "ollama", "model": "llama3.1:8b"},
            config_path=config_path
        )
        ConfigWriter.write(
            {"provider": "ollama", "model": "llama3.1:8b"},
            config_path=config_path
        )
        content = config_path.read_text()
        # B181: Expect 2 now (one in [llm], one in [judge])
        assert content.count('provider = "ollama"') == 2

class TestSchemaInitializer:

    def test_init_success(self, tmp_path):
        """Returns True when schema init script succeeds."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        mock_result = MagicMock(returncode=0, stdout="...SCHEMA_OK\n", stderr="")

        with patch("subprocess.run", return_value=mock_result):
            from campy.cli.install import VenvManager, SchemaInitializer
            vm = VenvManager(venv_dir=tmp_path)
            si = SchemaInitializer(vm)
            assert si.init() is True

    def test_init_failure(self, tmp_path):
        """Returns False when schema init script fails."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        mock_result = MagicMock(returncode=1, stdout="", stderr="ImportError: kuzu")

        with patch("subprocess.run", return_value=mock_result):
            from campy.cli.install import VenvManager, SchemaInitializer
            vm = VenvManager(venv_dir=tmp_path)
            si = SchemaInitializer(vm)
            assert si.init() is False

class TestAdapterRegistrar:

    def test_claude_code_prefers_native_plugin_install(self, tmp_path):
        """Claude Code installer prefers native plugin installation when available."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()

        calls = []
        def mock_run(*args, **kwargs):
            calls.append(args[0] if args else kwargs.get("args"))
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            with patch("shutil.which", return_value="/usr/local/bin/claude"):
                with patch("campy.cli.install._find_plugin_dir", return_value=Path("/tmp/plugin")):
                    from campy.cli.install import VenvManager, AdapterRegistrar
                    vm = VenvManager(venv_dir=tmp_path)
                    reg = AdapterRegistrar(vm)
                    result = reg._register_claude_code()
                    assert result is True
                    assert any(c[:3] == ["/usr/local/bin/claude", "plugin", "install"] for c in calls)

    def test_claude_code_legacy_scope_user(self, tmp_path):
        """Claude Code legacy fallback still registers with --scope user."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()

        calls = []
        def mock_run(*args, **kwargs):
            calls.append(args[0] if args else kwargs.get("args"))
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            with patch("shutil.which", return_value="/usr/local/bin/claude"):
                with patch("campy.cli.install._find_plugin_dir", return_value=None):
                    with patch("campy.cli.install.Path.home", return_value=tmp_path / "home"):
                        from campy.cli.install import VenvManager, AdapterRegistrar
                        vm = VenvManager(venv_dir=tmp_path)
                        reg = AdapterRegistrar(vm)
                        with patch.object(reg, "_register_hook"):
                            result = reg._register_claude_code()
                            assert result is True
                            add_call = [c for c in calls if c and "add" in str(c)]
                            assert any("--scope" in str(c) and "user" in str(c) for c in add_call)

    def test_codex_prefers_native_plugin_install(self, tmp_path):
        """Codex installer prefers native plugin installation when available."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()

        calls = []
        def mock_run(*args, **kwargs):
            calls.append(args[0] if args else kwargs.get("args"))
            return MagicMock(returncode=0, stdout="installed", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            with patch("shutil.which", side_effect=lambda name: "/usr/local/bin/codex" if name == "codex" else None):
                with patch("campy.cli.install._find_plugin_dir", return_value=Path("/tmp/plugin")):
                    from campy.cli.install import VenvManager, AdapterRegistrar
                    vm = VenvManager(venv_dir=tmp_path)
                    reg = AdapterRegistrar(vm)
                    assert reg._register_codex() is True
                    assert any(c[:3] == ["/usr/local/bin/codex", "plugin", "install"] for c in calls)

    def test_gemini_prefers_native_extension_link(self, tmp_path):
        """Gemini installer prefers native extension linking when available."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()

        calls = []
        def mock_run(*args, **kwargs):
            calls.append(args[0] if args else kwargs.get("args"))
            return MagicMock(returncode=0, stdout="linked", stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            with patch("shutil.which", side_effect=lambda name: "/usr/local/bin/gemini" if name == "gemini" else None):
                with patch("campy.cli.install._find_plugin_dir", return_value=Path("/tmp/plugin")):
                    from campy.cli.install import VenvManager, AdapterRegistrar
                    vm = VenvManager(venv_dir=tmp_path)
                    reg = AdapterRegistrar(vm)
                    assert reg._register_gemini_cli() is True
                    assert any(c[:3] == ["/usr/local/bin/gemini", "extensions", "link"] for c in calls)

    def test_claude_desktop_writes_config(self, tmp_path):
        """Claude Desktop writes to the correct config file."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()

        config_path = tmp_path / "claude_desktop_config.json"

        with patch("platform.system", return_value="Darwin"):
            with patch("campy.cli.install.Path.home", return_value=tmp_path):
                from campy.cli.install import VenvManager, AdapterRegistrar
                vm = VenvManager(venv_dir=tmp_path)
                reg = AdapterRegistrar(vm)
                # Directly test _merge_mcp_config
                adapter_path = Path("/fake/adapter.py")
                reg._merge_mcp_config(config_path, "sidequests-brain", {
                    "command": str(vm.python),
                    "args": [str(adapter_path)],
                })
                config = json.loads(config_path.read_text())
                assert "sidequests-brain" in config["mcpServers"]

    def test_claude_desktop_registration_uses_module_entrypoint(self, tmp_path):
        """Claude Desktop installer uses the canonical module-based adapter launch."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()

        config_path = (
            tmp_path / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        )

        with patch("platform.system", return_value="Darwin"):
            with patch("campy.cli.install.Path.home", return_value=tmp_path):
                from campy.cli.install import VenvManager, AdapterRegistrar

                vm = VenvManager(venv_dir=tmp_path)
                reg = AdapterRegistrar(vm)

                assert reg._register_claude_desktop() is True

        config = json.loads(config_path.read_text())
        assert config["mcpServers"]["campy"]["command"] == str(tmp_path / "bin" / "python3")
        assert config["mcpServers"]["campy"]["args"] == ["-m", "campy.adapters.claude_desktop"]

    def test_detect_no_clients(self):
        """Returns empty dict when no clients detected."""
        with patch("campy.cli.detect.detect_installed_clients",
                   return_value={"claude-code": False, "claude-desktop": False,
                                 "codex": False, "codex-desktop": False,
                                 "chatgpt-desktop": False,
                                 "gemini-cli": False,
                                 "vscode": False,
                                 "openclaw": False}):
            from campy.cli.install import VenvManager, AdapterRegistrar
            vm = MagicMock()
            reg = AdapterRegistrar(vm)
            results = reg.register_all()
            assert results == {}

    def test_register_all_includes_codex_desktop(self):
        """register_all wires codex-desktop when detected."""
        detected = {
            "claude-code": False,
            "claude-desktop": False,
            "codex": False,
            "codex-desktop": True,
            "chatgpt-desktop": False,
            "gemini-cli": False,
            "vscode": False,
            "openclaw": False,
        }
        with patch("campy.cli.detect.detect_installed_clients", return_value=detected):
            from campy.cli.install import VenvManager, AdapterRegistrar
            vm = MagicMock()
            reg = AdapterRegistrar(vm)
            with patch.object(reg, "_register_codex_desktop", return_value=True) as mock_reg:
                results = reg.register_all()
                mock_reg.assert_called_once()
                assert results["codex-desktop"] is True

    def test_register_all_includes_vscode(self):
        """register_all wires VS Code when detected."""
        detected = {
            "claude-code": False,
            "claude-desktop": False,
            "codex": False,
            "codex-desktop": False,
            "chatgpt-desktop": False,
            "gemini-cli": False,
            "vscode": True,
            "openclaw": False,
        }
        with patch("campy.cli.detect.detect_installed_clients", return_value=detected):
            from campy.cli.install import AdapterRegistrar
            reg = AdapterRegistrar(MagicMock())
            with patch.object(reg, "_register_vscode", return_value=True) as mock_reg:
                results = reg.register_all()
                mock_reg.assert_called_once()
                assert results["vscode"] is True

    def test_register_codex_desktop_macos_writes_config(self, tmp_path):
        """Codex Desktop writes sidequests entry to a desktop config location on macOS."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        desktop_dir = tmp_path / "Library" / "Application Support" / "Codex"
        desktop_dir.mkdir(parents=True)

        with patch("platform.system", return_value="Darwin"):
            with patch("campy.cli.install.Path.home", return_value=tmp_path):
                from campy.cli.install import VenvManager, AdapterRegistrar
                vm = VenvManager(venv_dir=tmp_path)
                reg = AdapterRegistrar(vm)
                result = reg._register_codex_desktop()
                assert result is True
                content = (desktop_dir / "config.toml").read_text()
                assert "[mcp_servers.campy]" in content

    def test_register_all_includes_openclaw(self):
        """register_all wires openclaw when detected."""
        detected = {
            "claude-code": False,
            "claude-desktop": False,
            "codex": False,
            "codex-desktop": False,
            "chatgpt-desktop": False,
            "gemini-cli": False,
            "openclaw": True,
        }
        with patch("campy.cli.detect.detect_installed_clients", return_value=detected):
            from campy.cli.install import VenvManager, AdapterRegistrar
            vm = MagicMock()
            reg = AdapterRegistrar(vm)
            with patch.object(reg, "_register_openclaw", return_value=True) as mock_reg:
                results = reg.register_all()
                mock_reg.assert_called_once()
                assert results["openclaw"] is True

class TestDaemonSetup:

    def test_plist_uses_venv_site_packages(self, tmp_path, monkeypatch):
        """Plist PYTHONPATH points to ~/.sidequests/venv/ site-packages."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        monkeypatch.setattr("campy.cli.launchd.PLIST_PATH",
                           tmp_path / "test.plist")
        monkeypatch.setattr("campy.cli.launchd.LOG_PATH",
                           tmp_path / "test.log")

        with patch("shutil.which", return_value="/usr/bin/python3"):
            from campy.cli.install import VenvManager, DaemonSetup
            vm = VenvManager(venv_dir=tmp_path)
            with patch.object(vm, "site_packages_dir",
                            return_value=tmp_path / "lib" / "python3.12" / "site-packages"):
                ds = DaemonSetup(vm)
                plist_path = ds._write_plist()

                import plistlib
                with open(plist_path, "rb") as f:
                    plist = plistlib.load(f)

                pythonpath = plist["EnvironmentVariables"]["PYTHONPATH"]
                assert str(tmp_path) in pythonpath
                assert "site-packages" in pythonpath

    def test_plist_includes_env_vars(self, tmp_path, monkeypatch):
        """Plist includes API key env vars from .env file."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        monkeypatch.setattr("campy.cli.launchd.PLIST_PATH",
                           tmp_path / "test.plist")
        monkeypatch.setattr("campy.cli.launchd.LOG_PATH",
                           tmp_path / "test.log")

        env_file = tmp_path / ".env"
        env_file.write_text('OPENAI_API_KEY="sk-test123"\n')

        with patch("shutil.which", return_value="/usr/bin/python3"):
            with patch("campy.cli.install.SIDEQUESTS_HOME", tmp_path):
                from campy.cli.install import VenvManager, DaemonSetup
                vm = VenvManager(venv_dir=tmp_path)
                with patch.object(vm, "site_packages_dir",
                                return_value=tmp_path / "lib" / "python3.12" / "site-packages"):
                    ds = DaemonSetup(vm)
                    plist_path = ds._write_plist()

                    import plistlib
                    with open(plist_path, "rb") as f:
                        plist = plistlib.load(f)

                    assert plist["EnvironmentVariables"]["OPENAI_API_KEY"] == "sk-test123"

class TestIdempotency:

    def test_full_install_idempotent(self, tmp_path):
        """Running write twice does not corrupt state."""
        config_path = tmp_path / "config.toml"

        from campy.cli.install import ConfigWriter
        ConfigWriter.write(
            {"provider": "ollama", "model": "llama3.1:8b"},
            config_path=config_path
        )
        first_content = config_path.read_text()

        ConfigWriter.write(
            {"provider": "ollama", "model": "llama3.1:8b"},
            config_path=config_path
        )
        second_content = config_path.read_text()

        assert first_content == second_content

    def test_venv_skips_if_exists(self, tmp_path):
        """VenvManager.create() returns True without calling subprocess if venv exists."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()

        with patch("subprocess.run") as mock_run:
            from campy.cli.install import VenvManager
            vm = VenvManager(venv_dir=tmp_path)
            assert vm.create() is True
            mock_run.assert_not_called()

class TestFailureModes:

    def test_ollama_pull_timeout(self):
        """Returns False when ollama pull exceeds timeout."""
        def run_side_effect(*args, **kwargs):
            if "list" in str(args):
                return MagicMock(stdout="NAME\n", returncode=0)
            raise subprocess.TimeoutExpired(cmd="ollama pull", timeout=600)

        with patch("subprocess.run", side_effect=run_side_effect):
            from campy.cli.install import OllamaInstaller
            inst = OllamaInstaller()
            assert inst.pull_model("llama3.1:8b") is False

    def test_schema_init_timeout(self, tmp_path):
        """Returns False when schema init exceeds timeout."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="python", timeout=120)):
            from campy.cli.install import VenvManager, SchemaInitializer
            vm = VenvManager(venv_dir=tmp_path)
            si = SchemaInitializer(vm)
            assert si.init() is False

    def test_resolve_seed_examples_path_prefers_project_root(self, tmp_path, monkeypatch):
        """Should prefer InvertorsDocs/GistSeedExamples.md if it exists."""
        dev_root = tmp_path / "dev"
        docs_dir = dev_root / "InvertorsDocs"
        docs_dir.mkdir(parents=True)
        seed_file = docs_dir / "GistSeedExamples.md"
        seed_file.touch()

        import campy.cli.install as install_mod
        monkeypatch.setattr(install_mod, "PROJECT_ROOT", dev_root)

        # Mock Path.exists to be true for this specific file
        path = install_mod.resolve_seed_examples_path()
        assert str(seed_file.resolve()) == path

    def test_resolve_seed_examples_path_falls_back_to_package_data(self, tmp_path, monkeypatch):
        """Should fall back to campy/data/GistSeedExamples.md if dev path missing."""
        # PROJECT_ROOT points to a dir without InvertorsDocs
        dev_root = tmp_path / "empty_dev"
        dev_root.mkdir()
        
        # campy/data exists relative to the module
        fake_mod_dir = tmp_path / "site-packages" / "sidequests" / "cli"
        fake_mod_dir.mkdir(parents=True)
        data_dir = tmp_path / "site-packages" / "sidequests" / "data"
        data_dir.mkdir(parents=True)
        seed_file = data_dir / "GistSeedExamples.md"
        seed_file.touch()

        import campy.cli.install as install_mod
        monkeypatch.setattr(install_mod, "PROJECT_ROOT", dev_root)
        
        # We need to mock __file__ in the module to point to our fake_mod_dir
        monkeypatch.setattr(install_mod, "__file__", str(fake_mod_dir / "install.py"))

        path = install_mod.resolve_seed_examples_path()
        assert str(seed_file.resolve()) == path

    def test_resolve_seed_examples_path_raises_when_missing(self, tmp_path, monkeypatch):
        """Should raise RuntimeError if no seed file found."""
        dev_root = tmp_path / "empty_dev"
        dev_root.mkdir()
        
        import campy.cli.install as install_mod
        monkeypatch.setattr(install_mod, "PROJECT_ROOT", dev_root)
        
        # Point __file__ to somewhere with no ../data/
        monkeypatch.setattr(install_mod, "__file__", str(tmp_path / "nowhere" / "install.py"))

        with pytest.raises(RuntimeError, match="Could not find GistSeedExamples.md"):
            install_mod.resolve_seed_examples_path()

class TestLaunchdResolver:

    def test_launchd_resolver_prefers_repo_venv(self, tmp_path):
        """Should prefer the repository venv so launchd sees installed deps."""
        import campy.cli.launchd as launchd

        # Fixture repo root with a venv python — the runner's own checkout
        # may not have .venv (CI installs deps into the system interpreter).
        venv_bin = tmp_path / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python").touch()

        resolved = launchd.resolve_system_python(repo_root=tmp_path)
        assert resolved.endswith(".venv/bin/python")

    def test_launchd_resolver_skips_pyenv_shim(self, monkeypatch):
        """Should skip interpreters that resolve to pyenv shims."""
        import campy.cli.launchd as launchd
        monkeypatch.setattr(launchd.Path, "exists", lambda self: False)
        
        # 1. which("python3.12") returns a shim
        # 2. which("python3") returns a real path
        def fake_which(cmd):
            if "3.12" in cmd: return "/Users/me/.pyenv/shims/python3.12"
            return "/usr/local/bin/python3"
            
        monkeypatch.setattr(launchd.shutil, "which", fake_which)
        
        # Mock realpath for the shim
        import os
        original_realpath = os.path.realpath
        def fake_realpath(path):
            if ".pyenv/shims" in path: return "/Users/me/.pyenv/shims/python3.12"
            return original_realpath(path)
        monkeypatch.setattr(os.path, "realpath", fake_realpath)
        
        resolved = launchd.resolve_system_python()
        assert resolved == "/usr/local/bin/python3"

    def test_launchd_resolver_falls_back_to_sys_executable(self, monkeypatch):
        """Should fall back to sys.executable if no other candidates work."""
        import campy.cli.launchd as launchd
        monkeypatch.setattr(launchd.Path, "exists", lambda self: False)
        monkeypatch.setattr(launchd.shutil, "which", lambda cmd: None)
        monkeypatch.setattr(os.path, "exists", lambda p: False)
        
        import sys
        resolved = launchd.resolve_system_python()
        assert resolved == os.path.realpath(sys.executable)

class TestDaemonSetupReload:

    def test_daemon_setup_best_effort_process_cleanup_called(self, tmp_path, monkeypatch):
        """setup() should attempt to pkill stale processes."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        
        import campy.cli.install as install_mod
        from campy.cli.install import VenvManager, DaemonSetup
        
        vm = VenvManager(venv_dir=tmp_path)
        ds = DaemonSetup(vm)
        
        # Mock platform.system to be Darwin
        monkeypatch.setattr(install_mod.platform, "system", lambda: "Darwin")
        
        # Mock _write_plist, unload_plist, load_plist
        monkeypatch.setattr(ds, "_write_plist", lambda: Path("/tmp/test.plist"))
        
        import campy.cli.launchd as launchd
        monkeypatch.setattr(launchd, "unload_plist", MagicMock())
        monkeypatch.setattr(launchd, "load_plist", MagicMock(returncode=0))
        
        # Capture pkill calls
        pkills = []
        def fake_run(args, **kwargs):
            if args[0] == "pkill":
                pkills.append(args)
            return MagicMock(returncode=0)
        
        monkeypatch.setattr(install_mod.subprocess, "run", fake_run)
        
        ds.setup()
        
        assert any("brain_daemon.py" in str(arg) for arg in pkills)
        assert any("campy.daemon" in str(arg) for arg in pkills)

    def test_daemon_setup_forces_unload_then_load_even_when_not_loaded(self, tmp_path, monkeypatch):
        """setup() should call unload_plist regardless of current state."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        
        import campy.cli.install as install_mod
        from campy.cli.install import VenvManager, DaemonSetup
        
        vm = VenvManager(venv_dir=tmp_path)
        ds = DaemonSetup(vm)
        
        monkeypatch.setattr(install_mod.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(ds, "_write_plist", lambda: Path("/tmp/test.plist"))
        
        import campy.cli.launchd as launchd
        unload_mock = MagicMock()
        load_mock = MagicMock(return_value=True)
        monkeypatch.setattr(launchd, "unload_plist", unload_mock)
        monkeypatch.setattr(launchd, "load_plist", load_mock)
        monkeypatch.setattr(launchd, "is_loaded", lambda: False) # Simulate NOT loaded
        
        monkeypatch.setattr(install_mod.subprocess, "run", lambda *a, **k: MagicMock(returncode=0))
        
        ds.setup()
        
        unload_mock.assert_called_once()
        load_mock.assert_called_once()

    def test_daemon_setup_write_plist_uses_launchd_resolver(self, tmp_path, monkeypatch):
        """DaemonSetup._write_plist should use resolve_system_python."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        
        from campy.cli.install import VenvManager, DaemonSetup
        import campy.cli.launchd as launchd
        
        vm = VenvManager(venv_dir=tmp_path)
        ds = DaemonSetup(vm)
        
        monkeypatch.setattr(launchd, "PLIST_PATH", tmp_path / "test.plist")
        monkeypatch.setattr(launchd, "LOG_PATH", tmp_path / "test.log")
        
        resolver_mock = MagicMock(return_value="/usr/bin/python3.concrete")
        monkeypatch.setattr(launchd, "resolve_system_python", resolver_mock)
        
        with patch.object(vm, "site_packages_dir", return_value=tmp_path):
            ds._write_plist()
            
        resolver_mock.assert_called_once()

class TestInstallReport:

    def test_print_report_all_pass(self):
        """Returns True when all steps pass."""
        from campy.cli.install import InstallStepResult, _print_install_report
        results = [
            InstallStepResult("Step 1", True, "ok"),
            InstallStepResult("Step 2", True, "ok"),
        ]
        assert _print_install_report(results) is True

    def test_print_report_with_failure(self):
        """Returns False when any step fails."""
        from campy.cli.install import InstallStepResult, _print_install_report
        results = [
            InstallStepResult("Step 1", True, "ok"),
            InstallStepResult("Step 2", False, "failed"),
        ]
        assert _print_install_report(results) is False

class TestConnectivity:

    def test_verify_ollama_success(self):
        """Returns True when Ollama endpoint responds."""
        with patch("urllib.request.urlopen") as mock_url:
            from campy.cli.install import verify_llm_connectivity
            ok, detail = verify_llm_connectivity({"provider": "ollama"})
            assert ok is True
            assert "reachable" in detail

    def test_verify_ollama_failure(self):
        """Returns False when Ollama endpoint unreachable."""
        with patch("urllib.request.urlopen", side_effect=Exception("Refused")):
            from campy.cli.install import verify_llm_connectivity
            ok, detail = verify_llm_connectivity({"provider": "ollama"})
            assert ok is False
            assert "unreachable" in detail

    def test_verify_byok_success(self):
        """Returns True when BYOK call succeeds."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock()
        with patch("campy.cli.install.OpenAI", return_value=mock_client):
            from campy.cli.install import verify_llm_connectivity
            ok, detail = verify_llm_connectivity({
                "provider": "openai",
                "api_key": "sk-test",
                "model": "gpt-4o-mini"
            })
            assert ok is True
            assert "connected" in detail

    def test_verify_byok_failure(self):
        """Returns False when BYOK call fails."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("Invalid key")
        with patch("campy.cli.install.OpenAI", return_value=mock_client):
            from campy.cli.install import verify_llm_connectivity
            ok, detail = verify_llm_connectivity({
                "provider": "openai",
                "api_key": "sk-bad",
                "model": "gpt-4o-mini"
            })
            assert ok is False
            assert "failed" in detail

class TestOrchestration:

    @patch("campy.cli.install._print_install_report")
    @patch("campy.cli.install._print_step_header")
    @patch("click.prompt")
    @patch("campy.cli.install.OllamaInstaller")
    @patch("campy.cli.install.verify_llm_connectivity")
    @patch("campy.cli.install.VenvManager")
    def test_run_install_emits_report_on_failure(self, mock_venv, mock_verify, mock_ollama, mock_prompt, mock_header, mock_report):
        """run_install should continue to report even if a step fails."""
        mock_prompt.return_value = "1" # Ollama
        mock_inst = mock_ollama.return_value
        mock_inst.setup.return_value = False # FAIL OLLAMA SETUP
        
        mock_v = mock_venv.return_value
        mock_v.create.return_value = False # FAIL VENV

        mock_report.return_value = False # Force failure return from report
        
        from campy.cli.install import run_install
        import click
        with pytest.raises(click.ClickException):
            run_install()
            
        # Verify report was called
        mock_report.assert_called_once()
        results = mock_report.call_args[0][0]
        # Check that we have failures in results
        assert any(not r.passed for r in results)
