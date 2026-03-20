Now I have a thorough understanding of the codebase. Let me compose the detailed implementation plan.

---

# Implementation Plan: `sidequests install` Command

## Overview

This plan replaces the current `sidequests setup` command with a new `sidequests install` command that provides a complete, single-command installation experience. The install command handles LLM provider choice, Python environment isolation, schema initialization, adapter registration, daemon setup, and smoke testing -- all idempotently.

The project root is `/Users/djs54/Library/CloudStorage/OneDrive-ChurchofJesusChrist/my-documents/SideQuest` (referred to as `$PROJECT` below).

---

## Architecture Decision: New File vs. Modify Existing

Create a **new file** `$PROJECT/sidequests/cli/install.py` rather than modifying `setup.py`. Rationale:
- `setup.py` has adapter registration logic that still works and is called by the install flow
- The install command is a superset -- it calls into setup logic but adds venv creation, Ollama install, BYOK validation, schema init, and model pre-warming
- Keep `setup.py` as a utility module called by `install.py`
- Modify `main.py` to add the `install` command (and keep `setup` as an alias)

---

## Implementation Order (Dependencies Shown)

```
Phase 1: Core install infrastructure (no external deps)
  1. sidequests/cli/install.py — OllamaInstaller class
  2. sidequests/cli/install.py — BYOKValidator class
  3. sidequests/cli/install.py — VenvManager class

Phase 2: Integration with existing modules
  4. sidequests/cli/install.py — SchemaInitializer class
  5. sidequests/cli/install.py — AdapterRegistrar class (wraps setup.py)
  6. sidequests/cli/install.py — DaemonSetup class (wraps launchd.py)

Phase 3: Orchestrator + CLI wiring
  7. sidequests/cli/install.py — run_install() orchestrator function
  8. sidequests/cli/main.py — add `install` command

Phase 4: Tests
  9. tests/test_install.py — full test coverage
```

---

## Phase 1: Core Install Infrastructure

### File: `$PROJECT/sidequests/cli/install.py`

This is the primary new file. All install logic lives here, organized as focused classes.

#### 1.1 Module Header and Constants

```python
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
from pathlib import Path
from typing import Optional

import click

# Canonical paths
SIDEQUESTS_HOME  = Path.home() / ".sidequests"
VENV_DIR         = SIDEQUESTS_HOME / "venv"
CONFIG_PATH      = SIDEQUESTS_HOME / "config.toml"
DB_PATH          = SIDEQUESTS_HOME / "brain.db"
SOCKET_PATH      = SIDEQUESTS_HOME / "brain.sock"
LOG_PATH         = SIDEQUESTS_HOME / "daemon.log"
PROJECT_ROOT     = Path(__file__).resolve().parent.parent.parent
```

#### 1.2 Class: `OllamaInstaller`

Handles Ollama detection, installation via Homebrew, model pull, and verification.

```python
class OllamaInstaller:
    """Install and configure Ollama for local LLM inference."""

    @staticmethod
    def is_installed() -> bool:
        """Return True if `ollama` binary is in PATH."""
        return shutil.which("ollama") is not None

    @staticmethod
    def is_running() -> bool:
        """Return True if Ollama server is responding at localhost:11434."""
        import urllib.request
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
        """
        Install Ollama via Homebrew. Returns True on success.

        Steps:
        1. Check if brew is available; if not, print manual install URL and return False
        2. Run `brew install ollama`
        3. Verify `ollama` is now in PATH

        Error handling:
        - brew not found: print "Install Homebrew first: https://brew.sh" + return False
        - brew install fails: print stderr + return False
        """
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
        """
        Ensure Ollama server is running.

        Steps:
        1. If is_running() is True, return True immediately
        2. Run `ollama serve` as a background process (detached)
        3. Poll is_running() up to 10 times with 1-second sleeps
        4. Return True if server responds, False if timeout

        Error handling:
        - subprocess.Popen fails: print error + return False
        """
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

        import time
        for _ in range(10):
            time.sleep(1)
            if self.is_running():
                click.echo("  [ok] Ollama server running")
                return True

        click.echo("  [!] Ollama server did not start within 10 seconds")
        return False

    def pull_model(self, model: str = "llama3.1:8b") -> bool:
        """
        Pull the specified model.

        Steps:
        1. If has_model(model) is True, print skip message + return True
        2. Run `ollama pull <model>` with live stdout passthrough
        3. Return True if returncode == 0

        Error handling:
        - pull fails: print stderr + return False
        - timeout after 600s: return False
        """
        if self.has_model(model):
            click.echo(f"  [=] Model {model} already available")
            return True

        click.echo(f"  Pulling {model} (this may take several minutes)...")
        result = subprocess.run(
            ["ollama", "pull", model],
            timeout=600
        )
        if result.returncode != 0:
            click.echo(f"  [!] Failed to pull {model}")
            return False

        click.echo(f"  [ok] Model {model} ready")
        return True

    def setup(self, model: str = "llama3.1:8b") -> bool:
        """
        Full Ollama setup pipeline.

        Returns True if Ollama is installed, running, and model is available.
        """
        if not self.is_installed():
            if not self.install():
                return False

        if not self.ensure_running():
            return False

        return self.pull_model(model)
```

**Key design notes:**
- `is_running()` uses `urllib.request` (stdlib) to avoid adding `requests` as a dependency
- `pull_model` runs without `capture_output=True` so the user sees download progress
- `ensure_running()` starts Ollama in a detached process group (`start_new_session=True`) so it persists after the installer exits
- All timeouts are generous -- 300s for brew install, 600s for model pull

#### 1.3 Class: `BYOKValidator`

Handles cloud provider API key collection and validation.

```python
class BYOKValidator:
    """Validate Bring Your Own Key configurations."""

    PROVIDERS = {
        "openai": {
            "env_var": "OPENAI_API_KEY",
            "base_url": None,  # uses SDK default
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
        """
        Ask the user which cloud provider they want to use.
        Returns one of: "openai", "anthropic", "google"

        Uses click.prompt with type=click.Choice.
        """
        return click.prompt(
            "Which provider?",
            type=click.Choice(["openai", "anthropic", "google"], case_sensitive=False),
        ).lower()

    def prompt_api_key(self, provider: str) -> str:
        """
        Ask the user for their API key. Uses click.prompt with hide_input=True.
        Also checks the corresponding env var first -- if set, asks to confirm.

        Returns the API key string.
        """
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
        """
        Validate the API key by making a minimal test call.

        Steps:
        1. Create an OpenAI client with the provider's base_url + api_key
        2. Call chat.completions.create with model=test_model, messages=[{"role":"user","content":"hi"}], max_tokens=1
        3. Return True if response received without auth error

        Error handling:
        - AuthenticationError: print "Invalid API key" + return False
        - Any other exception: print error + return False
        """
        try:
            from openai import OpenAI, AuthenticationError
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
        """
        Full BYOK setup. Returns a dict with keys: provider, model, api_key, base_url.
        Loops on invalid keys until the user provides a valid one or cancels (Ctrl+C).
        """
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
```

**Key design notes:**
- Uses `openai` SDK for validation -- it is already a project dependency
- `hide_input=True` on key prompt so the key does not appear in terminal history
- Loops on invalid keys rather than failing -- better UX
- Returns a dict the caller uses to write `sidequests.toml`

#### 1.4 Class: `VenvManager`

Creates and manages the isolated Python environment at `~/.sidequests/venv/`.

```python
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
        """
        Return the site-packages path for the venv.
        Uses the venv python to query sysconfig, not the current interpreter.
        """
        if self.exists():
            result = subprocess.run(
                [str(self.python), "-c",
                 "import sysconfig; print(sysconfig.get_path('purelib'))"],
                capture_output=True, text=True
            )
            return Path(result.stdout.strip())
        # Fallback: construct expected path
        py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
        return self.venv_dir / "lib" / py_ver / "site-packages"

    def create(self) -> bool:
        """
        Create the venv. Idempotent: skips if venv already exists.

        Steps:
        1. If self.exists(), print skip message + return True
        2. Create parent dirs
        3. Run `python3 -m venv <venv_dir>`
        4. Verify self.python exists

        Error handling:
        - subprocess fails: print error + return False
        """
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
        """
        Install project dependencies into the venv.

        Steps:
        1. pip install the project in editable mode: pip install -e PROJECT_ROOT
        2. This pulls all dependencies from pyproject.toml
        3. Verify kuzu can be imported

        Error handling:
        - pip fails: print error + return False
        """
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
        """
        Download spaCy en_core_web_md model.

        Steps:
        1. Check if model is already installed: python -c "import spacy; spacy.load('en_core_web_md')"
        2. If success, skip
        3. Otherwise run: python -m spacy download en_core_web_md

        Error handling:
        - download fails: print error + return False (non-fatal -- system degrades)
        """
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
        """
        Pre-warm sentence-transformers model (first load triggers download).

        Steps:
        1. Run: python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
        2. This downloads ~80MB on first run, cached thereafter

        Error handling:
        - fails: print warning + return False (non-fatal)
        """
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
```

**Key design notes:**
- Venv lives at `~/.sidequests/venv/` -- outside any TCC-protected directory (fixes ISSUE-008)
- All subprocess calls use the venv's own python/pip, not the system interpreter
- `install_deps` uses `requirements.txt` (pinned versions) then installs the project itself
- `prewarm_embeddings` and `install_spacy_model` are separate steps so failures are isolated
- Each method returns `bool` so the orchestrator can track what succeeded

---

## Phase 2: Integration with Existing Modules

#### 2.1 Class: `ConfigWriter`

Writes `sidequests.toml` to `~/.sidequests/config.toml`.

```python
class ConfigWriter:
    """Write sidequests.toml configuration."""

    @staticmethod
    def write(llm_config: dict, config_path: Path = CONFIG_PATH) -> Path:
        """
        Write sidequests.toml with the chosen LLM provider settings.

        Parameters:
            llm_config: dict with keys: provider, model, base_url (optional),
                        api_key (optional -- stored as env var reference, NOT literal key),
                        env_var (optional -- name of env var for api_key)

        Steps:
        1. Read the template sidequests.toml from PROJECT_ROOT/sidequests.toml
        2. Replace [llm] provider and model values
        3. If Ollama: keep base_url as-is
        4. If BYOK: set provider, model; add comment about env var; remove base_url
        5. Write to config_path
        6. Return config_path

        IMPORTANT: Never write the API key literally into the TOML file.
        Cloud provider keys are read from env vars at runtime.
        If the user provided a key interactively, write it to a .env file
        at ~/.sidequests/.env and print instructions to add to shell profile.

        Error handling:
        - Template not found: write a minimal config from scratch
        """
        config_path.parent.mkdir(parents=True, exist_ok=True)

        template = PROJECT_ROOT / "sidequests.toml"
        if template.exists():
            content = template.read_text()
        else:
            content = _MINIMAL_TOML_TEMPLATE

        # Replace provider and model
        provider = llm_config.get("provider", "ollama")
        model = llm_config.get("model", "llama3.1:8b")

        # Simple string replacement on the template
        import re
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
            # Remove or comment out base_url for cloud providers
            content = re.sub(
                r'^base_url\s*=\s*"[^"]*"',
                f'# base_url not needed for {provider}',
                content, count=1, flags=re.MULTILINE
            )

        config_path.write_text(content)
        click.echo(f"  [ok] Config written: {config_path}")

        # Handle API key persistence for BYOK
        if llm_config.get("api_key") and llm_config.get("env_var"):
            env_var = llm_config["env_var"]
            api_key = llm_config["api_key"]

            # Check if env var is already set in the environment
            if not os.environ.get(env_var):
                env_file = SIDEQUESTS_HOME / ".env"
                # Append if file exists, create if not
                with open(env_file, "a") as f:
                    f.write(f'{env_var}="{api_key}"\n')
                env_file.chmod(0o600)  # restrict permissions
                click.echo(f"  [ok] API key saved to {env_file} (chmod 600)")
                click.echo(f"  Add to your shell profile: export {env_var}=$(cat {env_file} | grep {env_var} | cut -d'\"' -f2)")

        return config_path
```

The minimal template constant:

```python
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
```

#### 2.2 Class: `SchemaInitializer`

Runs Kuzu schema init using the venv's Python.

```python
class SchemaInitializer:
    """Initialize the Kuzu database schema."""

    def __init__(self, venv: VenvManager):
        self.venv = venv

    def init(self) -> bool:
        """
        Initialize Kuzu schema by running schema.py init via the venv python.

        Steps:
        1. Run a Python script via subprocess that:
           a. Imports KuzuClient and init_schema
           b. Opens/creates the DB at ~/.sidequests/brain.db
           c. Calls init_schema(db, seed_path, embedding_model)
        2. This is idempotent (uses IF NOT EXISTS throughout)

        Error handling:
        - Import error: dependency not installed -- print + return False
        - Schema error: print traceback + return False
        """
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

        result = subprocess.run(
            [str(self.venv.python), "-c", init_script],
            capture_output=True, text=True, timeout=120
        )

        if result.returncode != 0 or "SCHEMA_OK" not in result.stdout:
            click.echo(f"  [!] Schema init failed:")
            # Print last 500 chars of stderr
            click.echo(f"      {result.stderr.strip()[-500:]}")
            return False

        click.echo("  [ok] Kuzu schema initialized")
        return True
```

#### 2.3 Class: `AdapterRegistrar`

Wraps the existing `setup.py` logic but fixes ISSUE-009 (global scope for Claude Code).

```python
class AdapterRegistrar:
    """Register MCP adapters with detected AI clients."""

    def __init__(self, venv: VenvManager):
        self.venv = venv
        self._adapters_dir = PROJECT_ROOT / "adapters"

    def register_all(self) -> dict[str, bool]:
        """
        Auto-detect installed clients and register adapters.

        Returns dict of {client_name: success_bool}.

        Steps:
        1. Call detect.detect_installed_clients()
        2. For each detected client, call the appropriate register method
        3. Return results dict
        """
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
        """
        Register Claude Code adapter with --scope user (global, not project-local).
        Fixes ISSUE-009.

        Steps:
        1. Run: claude mcp add sidequests-brain --scope user -- <venv_python> <adapter.py>
        2. If `claude` not in PATH, fall back to writing ~/.claude.json directly
        3. Also register the UserPromptSubmit hook in ~/.claude/settings.json

        Returns True on success.
        """
        adapter_path = (self._adapters_dir / "claude_code" / "adapter.py").resolve()

        # Try `claude mcp add` first (preferred -- handles all edge cases)
        claude_bin = shutil.which("claude")
        if claude_bin:
            # Remove existing registration first (idempotent)
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
            # Fallback: write ~/.claude.json directly
            config_path = Path.home() / ".claude.json"
            self._merge_mcp_json(config_path, adapter_path)

        # Register UserPromptSubmit hook
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
        """
        Register UserPromptSubmit hook in ~/.claude/settings.json.
        Reuses logic from adapters/claude_code/setup.py::_write_hook_config()
        but with the venv python path.
        """
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

        # Remove old registrations, add fresh
        user_prompt_hooks[:] = [
            entry for entry in user_prompt_hooks
            if "hook_user_turn" not in str(entry)
        ]
        user_prompt_hooks.append(hook_entry)

        settings_path.write_text(json.dumps(settings, indent=2))

    def _register_claude_desktop(self) -> bool:
        """
        Register Claude Desktop adapter.
        Writes to ~/Library/Application Support/Claude/claude_desktop_config.json.
        Uses venv python as the command.
        """
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
```

#### 2.4 Class: `DaemonSetup`

Wraps `launchd.py` but updates plist to use the venv at `~/.sidequests/venv/`.

```python
class DaemonSetup:
    """Set up Brain Daemon as a launchd service."""

    def __init__(self, venv: VenvManager):
        self.venv = venv

    def setup(self) -> bool:
        """
        Write launchd plist and start the daemon.

        Steps:
        1. Write plist at ~/Library/LaunchAgents/ai.sidequests.brain.plist
           - ProgramArguments: [system_python, brain_daemon.py]
           - EnvironmentVariables: PYTHONPATH = <venv_site_packages>:<project_root>
           - Also include any SIDEQUESTS_HOME/.env vars in EnvironmentVariables
        2. If already loaded, unload first (force refresh)
        3. Load the plist
        4. Wait 3 seconds, then check if daemon started

        Error handling:
        - plist write fails: return False
        - launchctl load fails: print manual command + return False
        """
        if platform.system() != "Darwin":
            click.echo("  [!] launchd only available on macOS")
            click.echo("      Start manually: sidequests start")
            return False

        click.echo("  Setting up launchd service...")

        # Write plist with corrected paths
        plist_path = self._write_plist()
        click.echo(f"    Plist: {plist_path}")

        # Unload if already loaded (idempotent refresh)
        from sidequests.cli.launchd import LABEL, is_loaded, unload_plist
        if is_loaded():
            unload_plist()

        # Load
        from sidequests.cli.launchd import load_plist
        if load_plist():
            click.echo("  [ok] Brain Daemon started via launchd")
            return True
        else:
            click.echo(f"  [!] launchctl load failed")
            click.echo(f"      Try: launchctl load {plist_path}")
            return False

    def _write_plist(self) -> Path:
        """
        Write the launchd plist, overriding launchd.py's write_plist()
        to use the venv at ~/.sidequests/venv/ (not project-local venv).

        Key differences from launchd.py:write_plist():
        - PYTHONPATH uses self.venv.site_packages_dir() (at ~/.sidequests/venv/...)
        - Adds env vars from ~/.sidequests/.env if it exists
        """
        import plistlib
        from sidequests.cli.launchd import LABEL, PLIST_PATH, LOG_PATH

        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        daemon_script = str(PROJECT_ROOT / "brain_daemon.py")
        system_python = shutil.which("python3.12") or shutil.which("python3") or sys.executable

        site_packages = str(self.venv.site_packages_dir())
        pythonpath = f"{site_packages}:{PROJECT_ROOT}"

        env_vars = {"PYTHONPATH": pythonpath}

        # Load .env file for BYOK API keys
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
```

---

## Phase 3: Orchestrator and CLI Wiring

#### 3.1 Function: `run_install()`

The main orchestrator that sequences all phases.

```python
def run_install() -> None:
    """
    Main install orchestrator. Runs all phases in sequence.

    Phase 1: LLM provider selection (interactive)
    Phase 2: Python venv creation + dependency installation
    Phase 3: Config file writing
    Phase 4: Kuzu schema initialization
    Phase 5: MCP adapter registration
    Phase 6: launchd daemon setup
    Phase 7: Smoke test

    Each phase prints its status. Failures in non-critical phases
    (spaCy, embedding pre-warm) print warnings but don't abort.
    Failures in critical phases (venv, deps, schema) abort with instructions.
    """
    click.echo("\n" + "=" * 50)
    click.echo("  SideQuests Brain — Installation")
    click.echo("=" * 50 + "\n")

    # ── Phase 1: LLM Provider ──────────────────────────────────────────
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

    # ── Phase 2: Python Environment ──────────────────────────────────────
    click.echo("Step 2/7: Python Environment\n")
    venv = VenvManager()

    if not venv.create():
        click.echo("\n  [!] Cannot create Python environment. Aborting.")
        sys.exit(1)

    if not venv.install_deps():
        click.echo("\n  [!] Dependency installation failed. Aborting.")
        sys.exit(1)

    # Non-critical: spaCy model and embedding pre-warm
    venv.install_spacy_model()
    venv.prewarm_embeddings()
    click.echo()

    # ── Phase 3: Configuration ──────────────────────────────────────
    click.echo("Step 3/7: Configuration\n")
    ConfigWriter.write(llm_config)
    click.echo()

    # ── Phase 4: Database Schema ──────────────────────────────────────
    click.echo("Step 4/7: Database Schema\n")
    schema_init = SchemaInitializer(venv)
    if not schema_init.init():
        click.echo("\n  [!] Schema initialization failed.")
        click.echo("      The daemon will retry on startup. Continuing...\n")
    click.echo()

    # ── Phase 5: Adapter Registration ──────────────────────────────────
    click.echo("Step 5/7: Adapter Registration\n")
    registrar = AdapterRegistrar(venv)
    registrar.register_all()
    click.echo()

    # ── Phase 6: Daemon Setup ──────────────────────────────────────
    click.echo("Step 6/7: Brain Daemon\n")
    daemon = DaemonSetup(venv)
    daemon_ok = daemon.setup()
    click.echo()

    # ── Phase 7: Smoke Test ──────────────────────────────────────
    click.echo("Step 7/7: Smoke Test\n")
    if daemon_ok:
        import time
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

    # ── Summary ──────────────────────────────────────────────────
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
```

#### 3.2 Modify: `$PROJECT/sidequests/cli/main.py`

Add the `install` command. This is a minimal change.

**What to add** (after the existing `setup` command, around line 38):

```python
@cli.command()
def install() -> None:
    """One-command installer: LLM setup, dependencies, schema, adapters, daemon."""
    from sidequests.cli.install import run_install
    run_install()
```

Keep the existing `setup` command for backward compatibility. Add a deprecation notice to its docstring:

```python
def setup(target: str, project_root: str | None) -> None:
    """[Deprecated — use `sidequests install`] Detect AI clients, register adapters, and start the Brain Daemon."""
```

---

## Phase 4: Tests

### File: `$PROJECT/tests/test_install.py`

Comprehensive test file. All tests use mocks -- no real Ollama, Homebrew, launchd, or network calls.

```python
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
from pathlib import Path
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
```

#### Test Structure (organized by class):

**4.1 OllamaInstaller Tests**

```python
class TestOllamaInstaller:

    def test_is_installed_true(self):
        """Returns True when ollama is in PATH."""
        with patch("shutil.which", return_value="/opt/homebrew/bin/ollama"):
            from sidequests.cli.install import OllamaInstaller
            assert OllamaInstaller.is_installed() is True

    def test_is_installed_false(self):
        """Returns False when ollama is not in PATH."""
        with patch("shutil.which", return_value=None):
            from sidequests.cli.install import OllamaInstaller
            assert OllamaInstaller.is_installed() is False

    def test_is_running_true(self):
        """Returns True when Ollama server responds."""
        with patch("urllib.request.urlopen") as mock_url:
            mock_url.return_value.__enter__ = lambda s: s
            mock_url.return_value.__exit__ = MagicMock(return_value=False)
            from sidequests.cli.install import OllamaInstaller
            assert OllamaInstaller.is_running() is True

    def test_is_running_false(self):
        """Returns False when Ollama server is unreachable."""
        with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError):
            from sidequests.cli.install import OllamaInstaller
            assert OllamaInstaller.is_running() is False

    def test_has_model_true(self):
        """Returns True when model appears in ollama list output."""
        mock_result = MagicMock(stdout="NAME\nllama3.1:8b\n", returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            from sidequests.cli.install import OllamaInstaller
            assert OllamaInstaller.has_model("llama3.1:8b") is True

    def test_has_model_false(self):
        """Returns False when model not in ollama list output."""
        mock_result = MagicMock(stdout="NAME\nmistral:7b\n", returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            from sidequests.cli.install import OllamaInstaller
            assert OllamaInstaller.has_model("llama3.1:8b") is False

    def test_install_no_homebrew(self):
        """Returns False and prints message when brew not available."""
        with patch("shutil.which", return_value=None):
            from sidequests.cli.install import OllamaInstaller
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

        with patch("shutil.which", side_effect=which_side_effect):
            mock_result = MagicMock(returncode=0)
            with patch("subprocess.run", return_value=mock_result):
                from sidequests.cli.install import OllamaInstaller
                inst = OllamaInstaller()
                assert inst.install() is True

    def test_install_brew_fails(self):
        """Returns False when brew install returns non-zero."""
        def which_side_effect(name):
            return "/opt/homebrew/bin/brew" if name == "brew" else None

        with patch("shutil.which", side_effect=which_side_effect):
            mock_result = MagicMock(returncode=1, stderr="Error")
            with patch("subprocess.run", return_value=mock_result):
                from sidequests.cli.install import OllamaInstaller
                inst = OllamaInstaller()
                assert inst.install() is False

    def test_pull_model_already_exists(self):
        """Skips pull when model already available."""
        mock_result = MagicMock(stdout="NAME\nllama3.1:8b\n", returncode=0)
        with patch("subprocess.run", return_value=mock_result):
            from sidequests.cli.install import OllamaInstaller
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
            from sidequests.cli.install import OllamaInstaller
            inst = OllamaInstaller()
            assert inst.pull_model("llama3.1:8b") is True
```

**4.2 BYOKValidator Tests**

```python
class TestBYOKValidator:

    def test_validate_key_success(self):
        """Returns True when API call succeeds."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock()

        with patch("sidequests.cli.install.OpenAI", return_value=mock_client):
            from sidequests.cli.install import BYOKValidator
            v = BYOKValidator()
            assert v.validate_key("openai", "sk-test123") is True

    def test_validate_key_auth_error(self):
        """Returns False on authentication error."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("401 Unauthorized")

        with patch("sidequests.cli.install.OpenAI", return_value=mock_client):
            from sidequests.cli.install import BYOKValidator
            v = BYOKValidator()
            assert v.validate_key("openai", "bad-key") is False

    def test_prompt_api_key_from_env(self, monkeypatch):
        """Uses env var when user confirms."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
        with patch("click.confirm", return_value=True):
            from sidequests.cli.install import BYOKValidator
            v = BYOKValidator()
            assert v.prompt_api_key("openai") == "sk-from-env"

    def test_prompt_api_key_manual(self, monkeypatch):
        """Prompts manually when env var not set."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("click.prompt", return_value="sk-manual"):
            from sidequests.cli.install import BYOKValidator
            v = BYOKValidator()
            assert v.prompt_api_key("openai") == "sk-manual"
```

**4.3 VenvManager Tests**

```python
class TestVenvManager:

    def test_exists_true(self, tmp_path):
        """Returns True when venv python3 binary exists."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        from sidequests.cli.install import VenvManager
        vm = VenvManager(venv_dir=tmp_path)
        assert vm.exists() is True

    def test_exists_false(self, tmp_path):
        """Returns False when venv does not exist."""
        from sidequests.cli.install import VenvManager
        vm = VenvManager(venv_dir=tmp_path / "nonexistent")
        assert vm.exists() is False

    def test_create_skips_existing(self, tmp_path):
        """Skips creation when venv already exists."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        from sidequests.cli.install import VenvManager
        vm = VenvManager(venv_dir=tmp_path)
        assert vm.create() is True

    def test_create_new_venv(self, tmp_path):
        """Creates venv when it does not exist."""
        venv_dir = tmp_path / "new_venv"
        mock_result = MagicMock(returncode=0)

        with patch("subprocess.run", return_value=mock_result):
            from sidequests.cli.install import VenvManager
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
            from sidequests.cli.install import VenvManager
            vm = VenvManager(venv_dir=tmp_path)
            assert vm.install_deps() is True

    def test_install_deps_pip_failure(self, tmp_path):
        """Returns False when pip install fails."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "pip3").touch()
        mock_result = MagicMock(returncode=1, stderr="ERROR: No matching distribution")

        with patch("subprocess.run", return_value=mock_result):
            from sidequests.cli.install import VenvManager
            vm = VenvManager(venv_dir=tmp_path)
            assert vm.install_deps() is False

    def test_install_spacy_already_present(self, tmp_path):
        """Skips download when model already installed."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        mock_result = MagicMock(returncode=0)

        with patch("subprocess.run", return_value=mock_result):
            from sidequests.cli.install import VenvManager
            vm = VenvManager(venv_dir=tmp_path)
            assert vm.install_spacy_model() is True

    def test_prewarm_embeddings_success(self, tmp_path):
        """Returns True when embedding pre-warm succeeds."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        mock_result = MagicMock(returncode=0)

        with patch("subprocess.run", return_value=mock_result):
            from sidequests.cli.install import VenvManager
            vm = VenvManager(venv_dir=tmp_path)
            assert vm.prewarm_embeddings() is True
```

**4.4 ConfigWriter Tests**

```python
class TestConfigWriter:

    def test_write_ollama_config(self, tmp_path):
        """Writes correct config for Ollama provider."""
        config_path = tmp_path / "config.toml"
        from sidequests.cli.install import ConfigWriter
        ConfigWriter.write(
            {"provider": "ollama", "model": "llama3.1:8b"},
            config_path=config_path
        )
        content = config_path.read_text()
        assert 'provider = "ollama"' in content
        assert 'model = "llama3.1:8b"' in content

    def test_write_byok_config(self, tmp_path):
        """Writes correct config for cloud provider."""
        config_path = tmp_path / "config.toml"
        from sidequests.cli.install import ConfigWriter
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
        with patch("sidequests.cli.install.SIDEQUESTS_HOME", tmp_path):
            from sidequests.cli.install import ConfigWriter
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
        from sidequests.cli.install import ConfigWriter
        ConfigWriter.write(
            {"provider": "ollama", "model": "llama3.1:8b"},
            config_path=config_path
        )
        ConfigWriter.write(
            {"provider": "ollama", "model": "llama3.1:8b"},
            config_path=config_path
        )
        content = config_path.read_text()
        assert content.count('provider = "ollama"') == 1
```

**4.5 SchemaInitializer Tests**

```python
class TestSchemaInitializer:

    def test_init_success(self, tmp_path):
        """Returns True when schema init script succeeds."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        mock_result = MagicMock(returncode=0, stdout="...SCHEMA_OK\n", stderr="")

        with patch("subprocess.run", return_value=mock_result):
            from sidequests.cli.install import VenvManager, SchemaInitializer
            vm = VenvManager(venv_dir=tmp_path)
            si = SchemaInitializer(vm)
            assert si.init() is True

    def test_init_failure(self, tmp_path):
        """Returns False when schema init script fails."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        mock_result = MagicMock(returncode=1, stdout="", stderr="ImportError: kuzu")

        with patch("subprocess.run", return_value=mock_result):
            from sidequests.cli.install import VenvManager, SchemaInitializer
            vm = VenvManager(venv_dir=tmp_path)
            si = SchemaInitializer(vm)
            assert si.init() is False
```

**4.6 AdapterRegistrar Tests**

```python
class TestAdapterRegistrar:

    def test_claude_code_global_scope(self, tmp_path):
        """Claude Code registers with --scope user, not project-local."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()

        calls = []
        def mock_run(*args, **kwargs):
            calls.append(args[0] if args else kwargs.get("args"))
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            with patch("shutil.which", return_value="/usr/local/bin/claude"):
                from sidequests.cli.install import VenvManager, AdapterRegistrar
                vm = VenvManager(venv_dir=tmp_path)
                reg = AdapterRegistrar(vm)
                result = reg._register_claude_code()
                assert result is True
                # Verify --scope user was passed
                add_call = [c for c in calls if c and "add" in str(c)]
                assert any("--scope" in str(c) and "user" in str(c) for c in add_call)

    def test_claude_desktop_writes_config(self, tmp_path):
        """Claude Desktop writes to the correct config file."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()

        config_path = tmp_path / "claude_desktop_config.json"

        with patch("platform.system", return_value="Darwin"):
            with patch("sidequests.cli.install.Path.home", return_value=tmp_path):
                from sidequests.cli.install import VenvManager, AdapterRegistrar
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

    def test_detect_no_clients(self):
        """Returns empty dict when no clients detected."""
        with patch("sidequests.cli.detect.detect_installed_clients",
                   return_value={"claude-code": False, "claude-desktop": False,
                                 "codex": False, "chatgpt-desktop": False,
                                 "gemini-cli": False}):
            from sidequests.cli.install import VenvManager, AdapterRegistrar
            vm = MagicMock()
            reg = AdapterRegistrar(vm)
            results = reg.register_all()
            assert results == {}
```

**4.7 DaemonSetup Tests**

```python
class TestDaemonSetup:

    def test_plist_uses_venv_site_packages(self, tmp_path, monkeypatch):
        """Plist PYTHONPATH points to ~/.sidequests/venv/ site-packages."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()
        monkeypatch.setattr("sidequests.cli.launchd.PLIST_PATH",
                           tmp_path / "test.plist")
        monkeypatch.setattr("sidequests.cli.launchd.LOG_PATH",
                           tmp_path / "test.log")

        with patch("shutil.which", return_value="/usr/bin/python3"):
            from sidequests.cli.install import VenvManager, DaemonSetup
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
        monkeypatch.setattr("sidequests.cli.launchd.PLIST_PATH",
                           tmp_path / "test.plist")
        monkeypatch.setattr("sidequests.cli.launchd.LOG_PATH",
                           tmp_path / "test.log")

        env_file = tmp_path / ".env"
        env_file.write_text('OPENAI_API_KEY="sk-test123"\n')

        with patch("shutil.which", return_value="/usr/bin/python3"):
            with patch("sidequests.cli.install.SIDEQUESTS_HOME", tmp_path):
                from sidequests.cli.install import VenvManager, DaemonSetup
                vm = VenvManager(venv_dir=tmp_path)
                with patch.object(vm, "site_packages_dir",
                                return_value=tmp_path / "lib" / "python3.12" / "site-packages"):
                    ds = DaemonSetup(vm)
                    plist_path = ds._write_plist()

                    import plistlib
                    with open(plist_path, "rb") as f:
                        plist = plistlib.load(f)

                    assert plist["EnvironmentVariables"]["OPENAI_API_KEY"] == "sk-test123"
```

**4.8 Idempotency Tests**

```python
class TestIdempotency:

    def test_full_install_idempotent(self, tmp_path):
        """Running install twice does not corrupt state."""
        # This is a high-level test that mocks all subprocess calls
        # and verifies config files are consistent after two runs.
        config_path = tmp_path / "config.toml"

        from sidequests.cli.install import ConfigWriter
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
            from sidequests.cli.install import VenvManager
            vm = VenvManager(venv_dir=tmp_path)
            assert vm.create() is True
            mock_run.assert_not_called()
```

**4.9 Failure Mode Tests**

```python
class TestFailureModes:

    def test_ollama_pull_timeout(self):
        """Returns False when ollama pull exceeds timeout."""
        def run_side_effect(*args, **kwargs):
            if "list" in str(args):
                return MagicMock(stdout="NAME\n", returncode=0)
            raise subprocess.TimeoutExpired(cmd="ollama pull", timeout=600)

        with patch("subprocess.run", side_effect=run_side_effect):
            from sidequests.cli.install import OllamaInstaller
            inst = OllamaInstaller()
            assert inst.pull_model("llama3.1:8b") is False

    def test_schema_init_timeout(self, tmp_path):
        """Returns False when schema init exceeds timeout."""
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "python3").touch()

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="python", timeout=120)):
            from sidequests.cli.install import VenvManager, SchemaInitializer
            vm = VenvManager(venv_dir=tmp_path)
            si = SchemaInitializer(vm)
            assert si.init() is False
```

---

## Summary of All File Changes

| File | Action | Description |
|------|--------|-------------|
| `sidequests/cli/install.py` | **CREATE** | New file: 6 classes + orchestrator (~500 lines) |
| `sidequests/cli/main.py` | **MODIFY** | Add `install` command (3 lines), deprecation note on `setup` |
| `tests/test_install.py` | **CREATE** | New file: ~35 test functions across 9 test classes (~400 lines) |

No other files need modification. The install module calls into existing modules (`detect.py`, `launchd.py`, `smoke_test.py`) without changing them.

---

## Key Design Decisions for Sonnet to Follow

1. **All external operations go through `subprocess.run()`** -- the venv's python, not the current interpreter, runs deps/spaCy/embeddings. This ensures isolation.

2. **API keys are NEVER written to TOML files.** They go to `~/.sidequests/.env` with `chmod 600`, and the launchd plist reads them into `EnvironmentVariables`.

3. **Claude Code registration uses `--scope user`** (global) via `claude mcp add`, NOT project-local `.mcp.json`. This fixes ISSUE-009.

4. **The venv lives at `~/.sidequests/venv/`**, not in the project directory. This fixes ISSUE-008 (TCC).

5. **Each class method returns `bool`** so the orchestrator can distinguish critical failures (venv, deps) from non-critical ones (spaCy, embedding pre-warm, schema init).

6. **Idempotency first.** Every method checks if its work is already done before acting. The command is safe to run repeatedly.

7. **`click.echo()` for all output, not `print()`.** Consistent with the existing CLI pattern in `main.py`.

---

### Critical Files for Implementation

- `/Users/djs54/Library/CloudStorage/OneDrive-ChurchofJesusChrist/my-documents/SideQuest/sidequests/cli/install.py` - New file to create: all install logic (6 classes + orchestrator)
- `/Users/djs54/Library/CloudStorage/OneDrive-ChurchofJesusChrist/my-documents/SideQuest/sidequests/cli/main.py` - Add `install` command entry point (3 lines)
- `/Users/djs54/Library/CloudStorage/OneDrive-ChurchofJesusChrist/my-documents/SideQuest/tests/test_install.py` - New file to create: comprehensive test suite
- `/Users/djs54/Library/CloudStorage/OneDrive-ChurchofJesusChrist/my-documents/SideQuest/sidequests/cli/launchd.py` - Reference for plist generation pattern (read-only, not modified)
- `/Users/djs54/Library/CloudStorage/OneDrive-ChurchofJesusChrist/my-documents/SideQuest/sidequests/cli/setup.py` - Reference for adapter registration patterns (read-only, not modified)
