"""
sidequests/cli/install.py — One-command installer for SideQuests Brain.

Handles: LLM provider selection, venv creation, dependency installation,
spaCy model download, embedding model pre-warm, Kuzu schema init,
MCP adapter registration, launchd daemon setup, and smoke test.

Idempotent: safe to re-run. Skips completed steps.
"""

from __future__ import annotations
import json
import os
import platform
import shutil
import subprocess
import sys
import re
import time
import urllib.request
from pathlib import Path
from typing import Optional

import click
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Canonical paths
SIDEQUESTS_HOME  = Path.home() / ".sidequests"
VENV_DIR         = SIDEQUESTS_HOME / "venv"
CONFIG_PATH      = SIDEQUESTS_HOME / "config.toml"
DB_PATH          = SIDEQUESTS_HOME / "brain.db"
SOCKET_PATH      = SIDEQUESTS_HOME / "brain.sock"
LOG_PATH         = SIDEQUESTS_HOME / "daemon.log"
PROJECT_ROOT     = Path(__file__).resolve().parent.parent.parent

_MINIMAL_TOML_TEMPLATE = """\
[llm]
provider = "ollama"
model = "llama3.1:8b"
base_url = "http://localhost:11434/v1"

[embeddings]
model = "sentence-transformers/all-MiniLM-L6-v2"

[nlp]
spacy_model = "en_core_web_md"

[ingestion]
max_ingest_chars = 4000

[quest]
auto_complete_days = 30

[hebbian]
co_occurrence_threshold = 10

[pruning]
archive_threshold = 0.10
resurrection_threshold = 0.85
sweep_interval_seconds = 300

[web]
port = 7799
"""

class OllamaInstaller:
    """Install and configure Ollama for local LLM inference."""

    @staticmethod
    def is_installed() -> bool:
        """Return True if `ollama` binary is in PATH."""
        return shutil.which("ollama") is not None

    @staticmethod
    def is_running() -> bool:
        """Return True if Ollama server is responding at localhost:11434."""
        try:
            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
            return True
        except Exception:
            return False

    @staticmethod
    def has_model(model: str = "llama3.1:8b") -> bool:
        """Return True if the specified model is already pulled."""
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True, text=True, timeout=10
            )
            return model.split(":")[0] in result.stdout
        except Exception:
            return False

    @staticmethod
    def homebrew_available() -> bool:
        """Return True if `brew` is in PATH."""
        return shutil.which("brew") is not None

    def install(self) -> bool:
        """Install Ollama via Homebrew. Returns True on success."""
        if not self.homebrew_available():
            click.echo("  [!] Homebrew not found. Install Ollama manually:")
            click.echo("      https://ollama.com/download")
            return False

        click.echo("  Installing Ollama via Homebrew...")
        result = subprocess.run(
            ["brew", "install", "ollama"],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            click.echo(f"  [!] brew install ollama failed: {result.stderr.strip()}")
            return False

        if not self.is_installed():
            click.echo("  [!] ollama not found in PATH after install")
            return False

        click.echo("  [ok] Ollama installed")
        return True

    def ensure_running(self) -> bool:
        """Ensure Ollama server is running."""
        if self.is_running():
            return True

        click.echo("  Starting Ollama server...")
        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            click.echo(f"  [!] Failed to start Ollama: {e}")
            return False

        for _ in range(10):
            time.sleep(1)
            if self.is_running():
                click.echo("  [ok] Ollama server running")
                return True

        click.echo("  [!] Ollama server did not start within 10 seconds")
        return False

    def pull_model(self, model: str = "llama3.1:8b") -> bool:
        """Pull the specified model."""
        if self.has_model(model):
            click.echo(f"  [=] Model {model} already available")
            return True

        click.echo(f"  Pulling {model} (this may take several minutes)...")
        try:
            result = subprocess.run(
                ["ollama", "pull", model],
                timeout=600
            )
        except subprocess.TimeoutExpired:
            click.echo(f"  [!] Timeout pulling {model}")
            return False
        if result.returncode != 0:
            click.echo(f"  [!] Failed to pull {model}")
            return False

        click.echo(f"  [ok] Model {model} ready")
        return True

    def setup(self, model: str = "llama3.1:8b") -> bool:
        """Full Ollama setup pipeline."""
        if not self.is_installed():
            if not self.install():
                return False

        if not self.ensure_running():
            return False

        return self.pull_model(model)

class BYOKValidator:
    """Validate Bring Your Own Key configurations."""

    PROVIDERS = {
        "openai": {
            "env_var": "OPENAI_API_KEY",
            "base_url": None,
            "default_model": "gpt-4o-mini",
            "test_model": "gpt-4o-mini",
        },
        "anthropic": {
            "env_var": "ANTHROPIC_API_KEY",
            "base_url": "https://api.anthropic.com/v1",
            "default_model": "claude-sonnet-4-20250514",
            "test_model": "claude-sonnet-4-20250514",
        },
        "google": {
            "env_var": "GOOGLE_API_KEY",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "default_model": "gemini-2.0-flash",
            "test_model": "gemini-2.0-flash",
        },
    }

    def prompt_provider(self) -> str:
        """Ask the user which cloud provider they want to use."""
        return click.prompt(
            "Which provider?",
            type=click.Choice(["openai", "anthropic", "google"], case_sensitive=False),
        ).lower()

    def prompt_api_key(self, provider: str) -> str:
        """Ask the user for their API key."""
        env_var = self.PROVIDERS[provider]["env_var"]
        existing = os.environ.get(env_var, "")

        if existing:
            use_existing = click.confirm(
                f"  Found ${env_var} in environment. Use it?", default=True
            )
            if use_existing:
                return existing

        return click.prompt(f"  Enter your {provider.title()} API key", hide_input=True)

    def validate_key(self, provider: str, api_key: str) -> bool:
        """Validate the API key by making a minimal test call."""
        if OpenAI is None:
            click.echo("  [!] openai SDK not found in environment")
            return False

        try:
            pinfo = self.PROVIDERS[provider]

            kwargs = {"api_key": api_key}
            if pinfo["base_url"]:
                kwargs["base_url"] = pinfo["base_url"]

            client = OpenAI(**kwargs)
            client.chat.completions.create(
                model=pinfo["test_model"],
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
            )
            click.echo(f"  [ok] {provider.title()} API key validated")
            return True
        except Exception as e:
            if "auth" in str(e).lower() or "401" in str(e):
                click.echo(f"  [!] Invalid API key for {provider}")
            else:
                click.echo(f"  [!] Validation failed: {e}")
            return False

    def setup(self) -> dict:
        """Full BYOK setup."""
        provider = self.prompt_provider()
        pinfo = self.PROVIDERS[provider]

        while True:
            api_key = self.prompt_api_key(provider)
            if self.validate_key(provider, api_key):
                return {
                    "provider": provider,
                    "model": pinfo["default_model"],
                    "api_key": api_key,
                    "base_url": pinfo["base_url"],
                    "env_var": pinfo["env_var"],
                }
            click.echo("  Try again or press Ctrl+C to cancel.")

class VenvManager:
    """Manage the isolated Python environment at ~/.sidequests/venv/."""

    def __init__(self, venv_dir: Path = VENV_DIR):
        self.venv_dir = venv_dir
        self.python = venv_dir / "bin" / "python3"
        self.pip = venv_dir / "bin" / "pip3"

    def exists(self) -> bool:
        """Return True if the venv python3 binary exists."""
        return self.python.exists()

    def site_packages_dir(self) -> Path:
        """Return the site-packages path for the venv."""
        if self.exists():
            result = subprocess.run(
                [str(self.python), "-c",
                 "import sysconfig; print(sysconfig.get_path('purelib'))"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                return Path(result.stdout.strip())
        
        # Fallback: construct expected path
        py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
        return self.venv_dir / "lib" / py_ver / "site-packages"

    def create(self) -> bool:
        """Create the venv. Idempotent: skips if venv already exists."""
        if self.exists():
            click.echo(f"  [=] Venv already exists at {self.venv_dir}")
            return True

        click.echo(f"  Creating Python venv at {self.venv_dir}...")
        self.venv_dir.parent.mkdir(parents=True, exist_ok=True)

        result = subprocess.run(
            [sys.executable, "-m", "venv", str(self.venv_dir)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            click.echo(f"  [!] venv creation failed: {result.stderr.strip()}")
            return False

        if not self.python.exists():
            click.echo(f"  [!] venv created but python3 not found at {self.python}")
            return False

        click.echo(f"  [ok] Venv created")
        return True

    def install_deps(self) -> bool:
        """Install project dependencies into the venv."""
        click.echo("  Installing dependencies (this may take a few minutes)...")
        req_file = PROJECT_ROOT / "requirements.txt"

        result = subprocess.run(
            [str(self.pip), "install", "-r", str(req_file)],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode != 0:
            click.echo(f"  [!] pip install failed: {result.stderr.strip()[-500:]}")
            return False

        # Also install the project itself (for sidequests CLI + module imports)
        result = subprocess.run(
            [str(self.pip), "install", "-e", str(PROJECT_ROOT)],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            click.echo(f"  [!] Project install failed: {result.stderr.strip()[-500:]}")
            return False

        click.echo("  [ok] Dependencies installed")
        return True

    def install_spacy_model(self) -> bool:
        """Download spaCy en_core_web_md model."""
        click.echo("  Checking spaCy model...")
        check = subprocess.run(
            [str(self.python), "-c",
             "import spacy; spacy.load('en_core_web_md')"],
            capture_output=True, text=True, timeout=30
        )
        if check.returncode == 0:
            click.echo("  [=] spaCy en_core_web_md already installed")
            return True

        click.echo("  Downloading spaCy en_core_web_md (~40 MB)...")
        result = subprocess.run(
            [str(self.python), "-m", "spacy", "download", "en_core_web_md"],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            click.echo(f"  [!] spaCy model download failed: {result.stderr.strip()[-300:]}")
            return False

        click.echo("  [ok] spaCy model installed")
        return True

    def prewarm_embeddings(self) -> bool:
        """Pre-warm sentence-transformers model."""
        click.echo("  Pre-warming embedding model...")
        result = subprocess.run(
            [str(self.python), "-c",
             "from sentence_transformers import SentenceTransformer; "
             "m = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); "
             "m.encode('test')"],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            click.echo(f"  [!] Embedding model pre-warm failed: {result.stderr.strip()[-300:]}")
            return False

        click.echo("  [ok] Embedding model cached")
        return True

class ConfigWriter:
    """Write sidequests.toml configuration."""

    @staticmethod
    def write(llm_config: dict, config_path: Path = CONFIG_PATH) -> Path:
        """Write sidequests.toml with the chosen LLM provider settings."""
        config_path.parent.mkdir(parents=True, exist_ok=True)

        template = PROJECT_ROOT / "sidequests.toml"
        if template.exists():
            content = template.read_text()
        else:
            content = _MINIMAL_TOML_TEMPLATE

        provider = llm_config.get("provider", "ollama")
        model = llm_config.get("model", "llama3.1:8b")

        content = re.sub(
            r'^provider\s*=\s*"[^"]*"',
            f'provider = "{provider}"',
            content, count=1, flags=re.MULTILINE
        )
        content = re.sub(
            r'^model\s*=\s*"[^"]*"',
            f'model = "{model}"',
            content, count=1, flags=re.MULTILINE
        )

        if provider != "ollama":
            content = re.sub(
                r'^base_url\s*=\s*"[^"]*"',
                f'# base_url not needed for {provider}',
                content, count=1, flags=re.MULTILINE
            )

        config_path.write_text(content)
        click.echo(f"  [ok] Config written: {config_path}")

        if llm_config.get("api_key") and llm_config.get("env_var"):
            env_var = llm_config["env_var"]
            api_key = llm_config["api_key"]

            if not os.environ.get(env_var):
                env_file = SIDEQUESTS_HOME / ".env"
                with open(env_file, "a") as f:
                    f.write(f'{env_var}="{api_key}"\n')
                env_file.chmod(0o600)
                click.echo(f"  [ok] API key saved to {env_file} (chmod 600)")
                click.echo(f"  Add to your shell profile: export {env_var}=$(cat {env_file} | grep {env_var} | cut -d'\"' -f2)")

        return config_path

class SchemaInitializer:
    """Initialize the Kuzu database schema."""

    def __init__(self, venv: VenvManager):
        self.venv = venv

    def init(self) -> bool:
        """Initialize Kuzu schema."""
        click.echo("  Initializing Kuzu schema...")

        init_script = f"""
import sys
sys.path.insert(0, {str(PROJECT_ROOT)!r})
from mcp_engine.graph.kuzu_client import KuzuClient
from mcp_engine.schema import init_schema
db = KuzuClient({str(DB_PATH)!r})
seed_path = {str(PROJECT_ROOT / 'InvertorsDocs' / 'GistSeedExamples.md')!r}
init_schema(db, seed_path, 'sentence-transformers/all-MiniLM-L6-v2')
print('SCHEMA_OK')
"""

        try:
            result = subprocess.run(
                [str(self.venv.python), "-c", init_script],
                capture_output=True, text=True, timeout=120
            )
        except subprocess.TimeoutExpired:
            click.echo("  [!] Schema init timed out after 120 seconds")
            return False

        if result.returncode != 0 or "SCHEMA_OK" not in result.stdout:
            click.echo(f"  [!] Schema init failed:")
            click.echo(f"      {result.stderr.strip()[-500:]}")
            return False

        click.echo("  [ok] Kuzu schema initialized")
        return True

class AdapterRegistrar:
    """Register MCP adapters with detected AI clients."""

    def __init__(self, venv: VenvManager):
        self.venv = venv
        self._adapters_dir = PROJECT_ROOT / "adapters"

    def register_all(self) -> dict[str, bool]:
        """Auto-detect installed clients and register adapters."""
        from sidequests.cli.detect import detect_installed_clients
        detected = detect_installed_clients()
        results = {}

        click.echo("  Detecting AI clients...")
        any_detected = False
        for client, present in detected.items():
            if present:
                any_detected = True
                click.echo(f"    Found: {client}")

        if not any_detected:
            click.echo("    No AI clients detected.")
            click.echo("    Install Claude Code, Claude Desktop, Codex, or Gemini CLI.")
            return results

        click.echo("  Registering adapters...")

        if detected.get("claude-code"):
            results["claude-code"] = self._register_claude_code()

        if detected.get("claude-desktop"):
            results["claude-desktop"] = self._register_claude_desktop()

        if detected.get("codex"):
            results["codex"] = self._register_codex()

        if detected.get("gemini-cli"):
            results["gemini-cli"] = self._register_gemini_cli()

        if detected.get("chatgpt-desktop"):
            results["chatgpt-desktop"] = self._register_chatgpt_desktop()

        return results

    def _register_claude_code(self) -> bool:
        """Register Claude Code adapter with --scope user."""
        adapter_path = (self._adapters_dir / "claude_code" / "adapter.py").resolve()
        claude_bin = shutil.which("claude")
        
        if claude_bin:
            subprocess.run(
                [claude_bin, "mcp", "remove", "sidequests-brain", "--scope", "user"],
                capture_output=True, text=True, timeout=10
            )
            result = subprocess.run(
                [claude_bin, "mcp", "add", "sidequests-brain",
                 "--scope", "user", "--",
                 str(self.venv.python), str(adapter_path)],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                click.echo(f"    [!] claude mcp add failed: {result.stderr.strip()}")
                return False
        else:
            config_path = Path.home() / ".claude.json"
            self._merge_mcp_json(config_path, adapter_path)

        self._register_hook()
        click.echo("    [ok] Claude Code — registered (user scope)")
        return True

    def _merge_mcp_json(self, config_path: Path, adapter_path: Path) -> None:
        """Merge sidequests-brain into a .claude.json / .mcp.json file."""
        config = {}
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
            except (json.JSONDecodeError, OSError):
                config = {}

        servers = config.setdefault("mcpServers", {})
        servers["sidequests-brain"] = {
            "command": str(self.venv.python),
            "args": [str(adapter_path)],
        }
        config_path.write_text(json.dumps(config, indent=2))

    def _register_hook(self) -> None:
        """Register UserPromptSubmit hook in ~/.claude/settings.json."""
        hook_file = (self._adapters_dir / "claude_code" / "hook_user_turn.py").resolve()
        settings_path = Path.home() / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)

        settings = {}
        if settings_path.exists():
            try:
                settings = json.loads(settings_path.read_text())
            except (json.JSONDecodeError, OSError):
                settings = {}

        hook_entry = {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": f"{self.venv.python} {hook_file}",
                }
            ],
        }

        hooks = settings.setdefault("hooks", {})
        user_prompt_hooks = hooks.setdefault("UserPromptSubmit", [])
        user_prompt_hooks[:] = [
            entry for entry in user_prompt_hooks
            if "hook_user_turn" not in str(entry)
        ]
        user_prompt_hooks.append(hook_entry)
        settings_path.write_text(json.dumps(settings, indent=2))

    def _register_claude_desktop(self) -> bool:
        """Register Claude Desktop adapter."""
        adapter_path = (self._adapters_dir / "claude_desktop" / "adapter.py").resolve()

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
            click.echo("    [!] Claude Desktop: unsupported platform")
            return False

        config_path.parent.mkdir(parents=True, exist_ok=True)
        self._merge_mcp_config(config_path, "sidequests-brain", {
            "command": str(self.venv.python),
            "args": [str(adapter_path)],
        })
        click.echo(f"    [ok] Claude Desktop — registered")
        return True

    def _register_codex(self) -> bool:
        """Register the Codex adapter in ~/.codex/config.toml."""
        adapter_path = (self._adapters_dir / "codex" / "adapter.py").resolve()
        config_path = Path.home() / ".codex" / "config.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)

        existing = config_path.read_text() if config_path.exists() else ""
        entry_block = (
            f'\n[mcp_servers.sidequests]\n'
            f'command = "{self.venv.python}"\n'
            f'args = ["{adapter_path}"]\n'
        )

        if "mcp_servers.sidequests" not in existing:
            with open(config_path, "a") as f:
                f.write(entry_block)

        click.echo("    [ok] Codex — registered")
        return True

    def _register_gemini_cli(self) -> bool:
        """Register the Gemini CLI adapter in settings.json."""
        adapter_path = (self._adapters_dir / "gemini_cli" / "adapter.py").resolve()

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

        self._merge_mcp_config(config_path, "sidequests-brain", {
            "command": str(self.venv.python),
            "args": [str(adapter_path)],
        })
        click.echo("    [ok] Gemini CLI — registered")
        return True

    def _register_chatgpt_desktop(self) -> bool:
        """Print instructions for ChatGPT Desktop (SSE connector)."""
        click.echo("    [i] ChatGPT Desktop — paste this URL in Settings > Apps:")
        click.echo("        http://127.0.0.1:7799/sse")
        return True

    @staticmethod
    def _merge_mcp_config(config_path: Path, server_name: str, entry: dict) -> None:
        """Merge an MCP server entry into a JSON config file."""
        config = {}
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
            except (json.JSONDecodeError, OSError):
                config = {}
        servers = config.setdefault("mcpServers", {})
        servers[server_name] = entry
        config_path.write_text(json.dumps(config, indent=2))

class DaemonSetup:
    """Set up Brain Daemon as a launchd service."""

    def __init__(self, venv: VenvManager):
        self.venv = venv

    def setup(self) -> bool:
        """Write launchd plist and start the daemon."""
        if platform.system() != "Darwin":
            click.echo("  [!] launchd only available on macOS")
            click.echo("      Start manually: sidequests start")
            return False

        click.echo("  Setting up launchd service...")
        plist_path = self._write_plist()
        click.echo(f"    Plist: {plist_path}")

        from sidequests.cli.launchd import is_loaded, unload_plist, load_plist
        if is_loaded():
            unload_plist()

        if load_plist():
            click.echo("  [ok] Brain Daemon started via launchd")
            return True
        else:
            click.echo(f"  [!] launchctl load failed")
            click.echo(f"      Try: launchctl load {plist_path}")
            return False

    def _write_plist(self) -> Path:
        """Write the launchd plist, overriding launchd.py's write_plist()."""
        import plistlib
        from sidequests.cli.launchd import LABEL, PLIST_PATH, LOG_PATH

        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        daemon_script = str(PROJECT_ROOT / "brain_daemon.py")
        system_python = shutil.which("python3.12") or shutil.which("python3") or sys.executable

        site_packages = str(self.venv.site_packages_dir())
        pythonpath = f"{site_packages}:{PROJECT_ROOT}"

        env_vars = {"PYTHONPATH": pythonpath}
        env_file = SIDEQUESTS_HOME / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    env_vars[key.strip()] = val.strip().strip('"')

        plist_data = {
            "Label": LABEL,
            "ProgramArguments": [system_python, daemon_script],
            "EnvironmentVariables": env_vars,
            "RunAtLoad": True,
            "KeepAlive": True,
            "StandardOutPath": str(LOG_PATH),
            "StandardErrorPath": str(LOG_PATH),
            "WorkingDirectory": str(Path.home()),
        }

        with open(PLIST_PATH, "wb") as f:
            plistlib.dump(plist_data, f)

        return PLIST_PATH

def run_install() -> None:
    """Main install orchestrator."""
    click.echo("\n" + "=" * 50)
    click.echo("  SideQuests Brain — Installation")
    click.echo("=" * 50 + "\n")

    click.echo("Step 1/7: LLM Provider\n")
    click.echo("  SideQuests needs a language model for advanced reasoning.")
    click.echo("  Options:")
    click.echo("    1) Ollama (free, local, private — recommended)")
    click.echo("    2) Bring Your Own API Key (OpenAI / Anthropic / Google)\n")

    choice = click.prompt(
        "  Choose",
        type=click.Choice(["1", "2"]),
        default="1"
    )

    llm_config: dict = {}

    if choice == "1":
        click.echo("\n  Setting up Ollama...\n")
        ollama = OllamaInstaller()
        if not ollama.setup():
            click.echo("\n  [!] Ollama setup failed. You can:")
            click.echo("      1. Install Ollama manually: https://ollama.com/download")
            click.echo("      2. Re-run: sidequests install")
            click.echo("      3. Choose option 2 (BYOK) instead")
            sys.exit(1)
        llm_config = {
            "provider": "ollama",
            "model": "llama3.1:8b",
            "base_url": "http://localhost:11434/v1",
        }
    else:
        click.echo("\n  Setting up cloud provider...\n")
        byok = BYOKValidator()
        llm_config = byok.setup()

    click.echo()

    click.echo("Step 2/7: Python Environment\n")
    venv = VenvManager()
    if not venv.create():
        click.echo("\n  [!] Cannot create Python environment. Aborting.")
        sys.exit(1)
    if not venv.install_deps():
        click.echo("\n  [!] Dependency installation failed. Aborting.")
        sys.exit(1)
    venv.install_spacy_model()
    venv.prewarm_embeddings()
    click.echo()

    click.echo("Step 3/7: Configuration\n")
    ConfigWriter.write(llm_config)
    click.echo()

    click.echo("Step 4/7: Database Schema\n")
    schema_init = SchemaInitializer(venv)
    if not schema_init.init():
        click.echo("\n  [!] Schema initialization failed.")
        click.echo("      The daemon will retry on startup. Continuing...\n")
    click.echo()

    click.echo("Step 5/7: Adapter Registration\n")
    registrar = AdapterRegistrar(venv)
    registrar.register_all()
    click.echo()

    click.echo("Step 6/7: Brain Daemon\n")
    daemon = DaemonSetup(venv)
    daemon_ok = daemon.setup()
    click.echo()

    click.echo("Step 7/7: Smoke Test\n")
    if daemon_ok:
        click.echo("  Waiting for daemon to initialize...")
        time.sleep(3)
        try:
            from sidequests.cli.smoke_test import check_status
            check_status()
        except Exception as e:
            click.echo(f"  [!] Smoke test error: {e}")
            click.echo("      Try: sidequests status")
    else:
        click.echo("  [=] Skipped (daemon not started)")

    click.echo("\n" + "=" * 50)
    click.echo("  Installation complete!")
    click.echo("=" * 50)
    click.echo(f"\n  Config:   {CONFIG_PATH}")
    click.echo(f"  Database: {DB_PATH}")
    click.echo(f"  Logs:     {LOG_PATH}")
    click.echo(f"  Venv:     {VENV_DIR}")
    click.echo(f"\n  Commands:")
    click.echo(f"    sidequests status   — check daemon health")
    click.echo(f"    sidequests stop     — stop daemon")
    click.echo(f"    sidequests start    — start daemon (foreground)")
    click.echo(f"    sidequests review   — review open loops")
    click.echo()
