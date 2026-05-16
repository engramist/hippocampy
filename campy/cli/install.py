"""
sidequests/cli/install.py — Legacy installer shim for HippoCampy.

Handles: LLM provider selection, venv creation, dependency installation,
spaCy model download, embedding model pre-warm, Kuzu schema init,
MCP adapter registration, launchd daemon setup, and smoke test.

Idempotent: safe to re-run. Skips completed steps.
"""

from __future__ import annotations
from dataclasses import dataclass
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
from campy.cli.register import (
    _strip_codex_adapter_path_tables,
    _upsert_codex_mcp_block,
    install_codex_memory_skill,
    register_vscode,
)
from campy.branding import PRIMARY_MCP_SERVER, LEGACY_MCP_SERVER
from campy.paths import (
    runtime_dir,
    get_config_path,
    get_database_path,
    get_daemon_socket_path,
    get_daemon_log_path,
)
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

@dataclass
class InstallStepResult:
    name: str
    passed: bool
    detail: str
    fix_hint: str = ""

def _print_step_header(step_num: int, total_steps: int, title: str) -> None:
    click.echo(f"\nStep {step_num}/{total_steps}: {title}")
    click.echo("-" * (len(title) + 12))

def _print_install_report(results: list[InstallStepResult]) -> bool:
    """Print final pass/fail report and return True only if all critical steps passed."""
    click.echo("\n" + "=" * 50)
    click.echo("  INSTALLATION REPORT")
    click.echo("=" * 50)
    
    all_passed = True
    for res in results:
        status = "[ok]" if res.passed else "[!!]"
        click.echo(f"  {status} {res.name:<25} {res.detail}")
        if not res.passed:
            all_passed = False
            if res.fix_hint:
                click.echo(f"       -> Fix: {res.fix_hint}")
    
    click.echo("=" * 50)
    return all_passed

# Canonical paths
SIDEQUESTS_HOME  = runtime_dir()
VENV_DIR         = SIDEQUESTS_HOME / "venv"
CONFIG_PATH      = get_config_path()
DB_PATH          = get_database_path()
SOCKET_PATH      = get_daemon_socket_path()
LOG_PATH         = get_daemon_log_path()
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

[capture]
enabled = true

[capture.codex]
enabled = true
scan_interval_seconds = 10
max_events_per_scan = 50
initial_backfill_events = 20
max_initial_backfill_files = 1

[capture.claude_code]
enabled = true
scan_interval_seconds = 10
max_events_per_scan = 50
initial_backfill_events = 20
max_initial_backfill_files = 1

[capture.vscode]
enabled = true
scan_interval_seconds = 15
max_events_per_scan = 50
initial_backfill_events = 20
max_initial_backfill_files = 5

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

[judge]
provider = "ollama"
model = "qwen2.5:7b"
timeout_seconds = 60
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
            # Check version or tags endpoint
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
        """Install Ollama via platform-appropriate package manager. Returns True on success."""
        system = platform.system()
        
        if system == "Darwin":
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

        elif system == "Linux":
            if shutil.which("apt-get"):
                click.echo("  Installing Ollama via apt-get...")
                # We try to use the official install script if possible for Linux
                # but following the B13 request for package manager paths:
                try:
                    subprocess.run(["sudo", "apt-get", "update"], check=True)
                    subprocess.run(["sudo", "apt-get", "install", "-y", "ollama"], check=True)
                except subprocess.CalledProcessError as e:
                    click.echo(f"  [!] apt-get install failed: {e}")
                    return False
            elif shutil.which("dnf"):
                click.echo("  Installing Ollama via dnf...")
                try:
                    subprocess.run(["sudo", "dnf", "install", "-y", "ollama"], check=True)
                except subprocess.CalledProcessError as e:
                    click.echo(f"  [!] dnf install failed: {e}")
                    return False
            elif shutil.which("pacman"):
                click.echo("  Installing Ollama via pacman...")
                try:
                    subprocess.run(["sudo", "pacman", "-S", "--noconfirm", "ollama"], check=True)
                except subprocess.CalledProcessError as e:
                    click.echo(f"  [!] pacman install failed: {e}")
                    return False
            else:
                click.echo("  [!] No supported Linux package manager (apt, dnf, pacman) found.")
                click.echo("      Install Ollama manually: curl -fsSL https://ollama.com/install.sh | sh")
                return False
        else:
            click.echo(f"  [!] Automatic install not supported for {system}.")
            click.echo("      Install Ollama manually: https://ollama.com/download")
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
    """Manage the isolated Python environment at the active Campy runtime venv."""

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
    """Write campy.toml configuration."""

    @staticmethod
    def write(llm_config: dict, config_path: Path = CONFIG_PATH) -> Path:
        """Write campy.toml with the chosen LLM provider settings."""
        config_path.parent.mkdir(parents=True, exist_ok=True)

        template = PROJECT_ROOT / "campy.toml"
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

def resolve_seed_examples_path() -> str:
    """
    Resolve the absolute path to GistSeedExamples.md.
    
    Candidate order:
    1) PROJECT_ROOT/InvertorsDocs/GistSeedExamples.md (dev checkout)
    2) sidequests/data/GistSeedExamples.md (package data in wheel installs)
    """
    # 1. Dev checkout
    dev_path = PROJECT_ROOT / "InvertorsDocs" / "GistSeedExamples.md"
    if dev_path.exists():
        return str(dev_path.resolve())

    # 2. Package data fallback (using importlib.resources if available, or manual path)
    # For simplicity and to avoid extra deps in the installer, we check the relative path
    # in the site-packages or installed location.
    # __file__ is sidequests/cli/install.py, so data is at ../data/GistSeedExamples.md
    pkg_path = Path(__file__).resolve().parent.parent / "data" / "GistSeedExamples.md"
    if pkg_path.exists():
        return str(pkg_path.resolve())

    raise RuntimeError(
        "Could not find GistSeedExamples.md. \\n"
        f"Checked: \\n  1. {dev_path}\\n  2. {pkg_path}\\n"
        "If you are installing from source, ensure InvertorsDocs/ exists.\\n"
        "If you are installing from wheel, ensure sidequests/data/ is included."
    )

class SchemaInitializer:
    """Initialize the Kuzu database schema."""

    def __init__(self, venv: VenvManager):
        self.venv = venv

    def init(self) -> bool:
        """Initialize Kuzu schema."""
        click.echo("  Initializing Kuzu schema...")

        try:
            seed_path = resolve_seed_examples_path()
        except RuntimeError as e:
            click.echo(f"  [!] {e}")
            return False

        init_script = f"""
import sys
sys.path.insert(0, {str(PROJECT_ROOT)!r})
from mcp_engine.graph.kuzu_client import KuzuClient
from mcp_engine.schema import init_schema
db = KuzuClient({str(DB_PATH)!r})
seed_path = {seed_path!r}
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
            if "Could not set lock" in result.stderr or "set lock on file" in result.stderr:
                click.echo("  [=] Schema already initialized (daemon is running — skipping re-init)")
                return True
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
        from campy.cli.detect import detect_installed_clients
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
            click.echo("    Install Claude Code, Claude Desktop, Codex, Codex Desktop, or Gemini CLI.")
            return results

        click.echo("  Registering adapters...")

        if detected.get("claude-code"):
            results["claude-code"] = self._register_claude_code()

        if detected.get("claude-desktop"):
            results["claude-desktop"] = self._register_claude_desktop()

        if detected.get("codex"):
            results["codex"] = self._register_codex()

        if detected.get("codex-desktop"):
            results["codex-desktop"] = self._register_codex_desktop()

        if detected.get("gemini-cli"):
            results["gemini-cli"] = self._register_gemini_cli()

        if detected.get("vscode"):
            results["vscode"] = self._register_vscode()

        if detected.get("chatgpt-desktop"):
            results["chatgpt-desktop"] = self._register_chatgpt_desktop()

        if detected.get("openclaw"):
            results["openclaw"] = self._register_openclaw()

        return results

    def _register_claude_code(self) -> bool:
        """Register Claude Code adapter with --scope user."""
        adapter_path = (self._adapters_dir / "claude_code" / "adapter.py").resolve()
        claude_bin = shutil.which("claude")
        
        if claude_bin:
            subprocess.run(
                [claude_bin, "mcp", "remove", PRIMARY_MCP_SERVER, "--scope", "user"],
                capture_output=True, text=True, timeout=10
            )
            result = subprocess.run(
                [claude_bin, "mcp", "add", PRIMARY_MCP_SERVER,
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
        """Merge Campy into a .claude.json / .mcp.json file."""
        config = {}
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
            except (json.JSONDecodeError, OSError):
                config = {}

        servers = config.setdefault("mcpServers", {})
        for stale in (PRIMARY_MCP_SERVER, LEGACY_MCP_SERVER, "sidequests-brain", "sidequests-brain-desktop"):
            servers.pop(stale, None)
        servers[PRIMARY_MCP_SERVER] = {
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
        """Register Claude Desktop via plugin directory."""
        plugin_dir = PROJECT_ROOT / "plugin"
        if not plugin_dir.exists():
            click.echo("    [!] Plugin directory not found at plugin/")
            return False

        click.echo("    [ok] Claude Desktop — HippoCampy plugin ready")
        click.echo("")
        click.echo("    To install the plugin:")
        click.echo(f"      1. Open Claude Desktop → Cowork tab")
        click.echo(f"      2. Click 'Customize' → upload plugin folder:")
        click.echo(f"         {plugin_dir}")
        click.echo(f"      3. Or via CLI: claude plugins add {plugin_dir}")
        click.echo("")

        # Fallback for non-Cowork users: also register via stdio config
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
            return True # Already printed plugin instructions

        config_path.parent.mkdir(parents=True, exist_ok=True)
        self._merge_mcp_config(config_path, PRIMARY_MCP_SERVER, {
            "command": str(self.venv.python),
            "args": [str(adapter_path)],
        })
        return True

    def _register_codex(self) -> bool:
        """Register the Codex adapter in ~/.codex/config.toml."""
        adapter_path = (self._adapters_dir / "codex" / "adapter.py").resolve()
        config_path = Path.home() / ".codex" / "config.toml"
        self._ensure_codex_entry(config_path, adapter_path)
        install_codex_memory_skill(PROJECT_ROOT)
        click.echo(f"    [ok] Codex — registered at {config_path}")
        return True

    def _register_codex_desktop(self) -> bool:
        """Register Codex Desktop using the Codex adapter MCP entry."""
        adapter_path = (self._adapters_dir / "codex" / "adapter.py").resolve()
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
            click.echo("    [!] Codex Desktop unsupported on this platform; using Codex CLI config")
            return self._register_codex()

        config_path = None
        for candidate in config_candidates:
            if candidate.parent.exists() or candidate.exists():
                config_path = candidate
                break
        if config_path is None:
            config_path = config_candidates[-1]

        self._ensure_codex_entry(config_path, adapter_path)
        install_codex_memory_skill(PROJECT_ROOT)
        click.echo(f"    [ok] Codex Desktop — registered at {config_path}")
        return True

    def _ensure_codex_entry(self, config_path: Path, adapter_path: Path) -> None:
        """Ensure a Campy MCP entry exists in a Codex TOML config file."""
        config_path.parent.mkdir(parents=True, exist_ok=True)
        existing = config_path.read_text() if config_path.exists() else ""
        updated = _strip_codex_adapter_path_tables(existing, str(adapter_path))
        updated = _upsert_codex_mcp_block(updated, str(self.venv.python), str(adapter_path))
        config_path.write_text(updated)

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

        self._merge_mcp_config(config_path, PRIMARY_MCP_SERVER, {
            "command": str(self.venv.python),
            "args": [str(adapter_path)],
        })
        click.echo("    [ok] Gemini CLI — registered")
        return True

    def _register_chatgpt_desktop(self) -> bool:
        """Print setup instructions for ChatGPT Desktop (SSE connector)."""
        click.echo("    [ok] ChatGPT Desktop — SSE endpoint ready")
        click.echo("")
        click.echo("    To connect ChatGPT Desktop:")
        click.echo("      1. Open ChatGPT Desktop")
        click.echo("      2. Go to Settings → MCP Servers (or Apps → Add Connector)")
        click.echo("      3. Add server URL: http://127.0.0.1:7799/sse")
        click.echo("      4. Save — all SideQuest tools will appear automatically")
        click.echo("")
        return True

    def _register_vscode(self) -> bool:
        """Register VS Code/Copilot MCP config; capture fallback is daemon-side."""
        adapter_path = (self._adapters_dir / "codex" / "adapter.py").resolve()
        ok = register_vscode(str(adapter_path))
        if ok:
            click.echo("    [ok] VS Code — MCP server registered")
        return ok

    def _register_openclaw(self) -> bool:
        """Install/configure the OpenClaw extension and restart the gateway."""
        from campy.cli.setup import _register_openclaw
        _register_openclaw()
        click.echo("    [ok] OpenClaw — extension installed, config patched, gateway restarted")
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
        for stale in (PRIMARY_MCP_SERVER, LEGACY_MCP_SERVER, "sidequests-brain", "sidequests-brain-desktop"):
            servers.pop(stale, None)
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
            click.echo("      Start manually: campy start")
            return False

        click.echo("  Setting up launchd service...")
        plist_path = self._write_plist()
        click.echo(f"    Plist: {plist_path}")

        from campy.cli.launchd import is_loaded, unload_plist, load_plist
        
        # 1. Best-effort stale process cleanup
        click.echo("    Cleaning up stale daemon processes...")
        subprocess.run(["pkill", "-f", "brain_daemon.py"], capture_output=True)
        subprocess.run(["pkill", "-f", "campy.daemon"], capture_output=True)

        # 2. Force reload sequence to ensure fresh tool registry
        click.echo("    Forcing daemon reload to refresh tool registry...")
        unload_plist() # Ignore failure if not loaded

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
        from campy.cli.launchd import LABEL, PLIST_PATH, LOG_PATH, resolve_system_python

        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        daemon_script = str(PROJECT_ROOT / "brain_daemon.py")
        system_python = resolve_system_python()

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

def _wait_for_daemon(max_wait: int = 20, interval: int = 2) -> bool:
    """Poll the daemon socket until it appears or max_wait seconds elapse."""
    import time as _time
    elapsed = 0
    while elapsed < max_wait:
        if SOCKET_PATH.exists():
            return True
        _time.sleep(interval)
        elapsed += interval
        click.echo(f"    ({elapsed}s) still waiting...")
    return False


def verify_llm_connectivity(llm_config: dict) -> tuple[bool, str]:
    """Return (ok, detail) by issuing a minimal request to chosen provider."""
    provider = llm_config.get("provider", "ollama")
    model = llm_config.get("model", "llama3.1:8b")
    
    if provider == "ollama":
        base_url = llm_config.get("base_url", "http://localhost:11434/v1")
        # Extract host:port from base_url to check if server is up
        try:
            # We already have is_running() but this is more explicit for the report
            # Strip /v1 to get base Ollama API
            check_url = base_url.replace("/v1", "")
            if not check_url.endswith("/"):
                check_url += "/"
            urllib.request.urlopen(f"{check_url}api/tags", timeout=3)
            return True, f"Ollama reachable at {base_url}"
        except Exception as e:
            return False, f"Ollama unreachable: {e}"
    
    else:
        # BYOK providers
        if OpenAI is None:
            return False, "openai SDK not installed"
            
        try:
            api_key = llm_config.get("api_key")
            base_url = llm_config.get("base_url")
            
            # If api_key is not in llm_config, try environment
            if not api_key:
                env_var = BYOKValidator.PROVIDERS.get(provider, {}).get("env_var")
                if env_var:
                    api_key = os.environ.get(env_var)
            
            if not api_key:
                return False, f"Missing API key for {provider}"

            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url

            client = OpenAI(**kwargs)
            client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
            )
            return True, f"{provider.title()} ({model}) connected"
        except Exception as e:
            return False, f"{provider.title()} connection failed: {e}"


def run_install() -> None:
    """Main install orchestrator."""
    click.echo("\n" + "=" * 50)
    click.echo("  HippoCampy — Installation")
    click.echo("=" * 50 + "\n")

    results: list[InstallStepResult] = []
    total_steps = 8

    # Step 1: Provider Setup
    _print_step_header(1, total_steps, "LLM Provider Setup")
    click.echo("  HippoCampy needs a language model for advanced reasoning.")
    click.echo("  Options:")
    click.echo("    1) Ollama (free, local, private — recommended)")
    click.echo("    2) Bring Your Own API Key (OpenAI / Anthropic / Google)\n")

    choice = click.prompt(
        "  Choose",
        type=click.Choice(["1", "2"]),
        default="1"
    )

    llm_config: dict = {}
    provider_ok = False
    if choice == "1":
        click.echo("\n  Setting up Ollama...\n")
        ollama = OllamaInstaller()
        provider_ok = ollama.setup()
        if provider_ok:
            llm_config = {
                "provider": "ollama",
                "model": "llama3.1:8b",
                "base_url": "http://localhost:11434/v1",
            }
            results.append(InstallStepResult("LLM Provider", True, "Ollama local setup ok"))
        else:
            results.append(InstallStepResult("LLM Provider", False, "Ollama setup failed", "Check https://ollama.com"))
    else:
        click.echo("\n  Setting up cloud provider...\n")
        byok = BYOKValidator()
        try:
            llm_config = byok.setup()
            provider_ok = True
            results.append(InstallStepResult("LLM Provider", True, f"{llm_config['provider']} setup ok"))
        except Exception as e:
            results.append(InstallStepResult("LLM Provider", False, f"BYOK setup failed: {e}"))

    # Step 2: Connectivity
    _print_step_header(2, total_steps, "LLM Connectivity Check")
    if provider_ok:
        ok, detail = verify_llm_connectivity(llm_config)
        results.append(InstallStepResult("LLM Connectivity", ok, detail, "Check network or API key" if not ok else ""))
    else:
        results.append(InstallStepResult("LLM Connectivity", False, "skipped due to earlier failure"))

    # Step 3: Python Environment
    _print_step_header(3, total_steps, "Python Environment & Dependencies")
    venv = VenvManager()
    venv_ok = venv.create()
    if venv_ok:
        deps_ok = venv.install_deps()
        if deps_ok:
            venv.install_spacy_model()
            venv.prewarm_embeddings()
            results.append(InstallStepResult("Python Environment", True, "Venv and dependencies ok"))
        else:
            results.append(InstallStepResult("Python Environment", False, "Dependency install failed", "Check network/pip"))
            venv_ok = False
    else:
        results.append(InstallStepResult("Python Environment", False, "Venv creation failed"))

    # Step 4: Configuration
    _print_step_header(4, total_steps, "Configuration Writing")
    if provider_ok:
        try:
            ConfigWriter.write(llm_config)
            results.append(InstallStepResult("Configuration", True, f"Written to {CONFIG_PATH}"))
        except Exception as e:
            results.append(InstallStepResult("Configuration", False, f"Failed: {e}"))
    else:
        results.append(InstallStepResult("Configuration", False, "skipped due to earlier failure"))

    # Step 5: Schema Init
    _print_step_header(5, total_steps, "Database Schema Initialization")
    if venv_ok:
        schema_init = SchemaInitializer(venv)
        if schema_init.init():
            results.append(InstallStepResult("Database Schema", True, "Kuzu schema initialized"))
        else:
            results.append(InstallStepResult("Database Schema", False, "Schema init failed", "Check the Campy daemon log"))
    else:
        results.append(InstallStepResult("Database Schema", False, "skipped due to earlier failure"))

    # Step 6: Adapter Registration
    _print_step_header(6, total_steps, "Adapter Registration")
    if venv_ok:
        registrar = AdapterRegistrar(venv)
        reg_results = registrar.register_all()
        results.append(InstallStepResult("Adapters", True, f"Registered {len(reg_results)} adapters"))
    else:
        results.append(InstallStepResult("Adapters", False, "skipped due to earlier failure"))

    # Step 7: Daemon Setup
    _print_step_header(7, total_steps, "Brain Daemon Setup")
    daemon_ok = False
    if venv_ok:
        daemon = DaemonSetup(venv)
        daemon_ok = daemon.setup()
        results.append(InstallStepResult("Daemon Setup", daemon_ok, "Daemon started via launchd" if daemon_ok else "Setup failed"))
    else:
        results.append(InstallStepResult("Daemon Setup", False, "skipped due to earlier failure"))

    # Step 8: Smoke Test
    _print_step_header(8, total_steps, "Final Smoke Test")
    smoke_ok = False
    if daemon_ok:
        click.echo("  Waiting for daemon to initialize...")
        ready = _wait_for_daemon(max_wait=20, interval=2)
        if ready:
            try:
                from campy.cli.smoke_test import check_status
                smoke_ok = check_status()
                if smoke_ok:
                    results.append(InstallStepResult("Smoke Test", True, "All systems nominal"))
                else:
                    results.append(InstallStepResult("Smoke Test", False, "Health checks failed", "Run 'campy status'"))
            except Exception as e:
                results.append(InstallStepResult("Smoke Test", False, f"Smoke test failed: {e}", "Run 'campy status'"))
        else:
            results.append(InstallStepResult("Smoke Test", False, "Daemon socket timeout", "Check the Campy daemon log"))
    else:
        results.append(InstallStepResult("Smoke Test", False, "skipped due to earlier failure"))

    # Final Report
    all_critical_passed = _print_install_report(results)

    if all_critical_passed:
        click.echo(f"\n  Installation complete! Brain is running.")
        click.echo(f"  Commands:")
        click.echo(f"    campy status        — check daemon health")
        click.echo(f"    campy review        — review open loops")
    else:
        raise click.ClickException("Installation completed with failures. See report above.")
