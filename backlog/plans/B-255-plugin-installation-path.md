# B255 - Plugin Installation Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `campy install` to detect installed agents and install the Campy plugin (MCP server config + skills) into each.

**Architecture:** Add a `--plugin` flag to `campy install` that iterates over detected agents and calls per-agent plugin installation. Each agent gets the plugin's `.mcp.json` SSE config and skill files installed to its native location. `campy doctor` gains plugin status checks.

**Tech Stack:** Python, Typer CLI, Rich, JSON config manipulation, pathlib

---

### Task 1: Add `--plugin` Flag to CLI

**Files:**
- Modify: `campy/cli/main.py`

- [ ] **Step 1: Write the failing test**

Create `tests/cli/test_install_plugin.py`:

```python
import subprocess
import sys

def test_install_plugin_help():
    """campy install --help should mention --plugin flag."""
    result = subprocess.run(
        [sys.executable, "-m", "campy.cli.main", "install", "--help"],
        capture_output=True, text=True
    )
    assert "--plugin" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_install_plugin.py::test_install_plugin_help -v`
Expected: FAIL — `--plugin` not in help output

- [ ] **Step 3: Add install-plugin command to main.py**

In `campy/cli/main.py`, add a new command:

```python
@app.command(name="install-plugin")
def install_plugin(
    target: Optional[str] = typer.Option(None, help="Specific agent (claude-code, codex, gemini-cli, vscode)"),
    plugin_dir: Optional[str] = typer.Option(None, help="Path to plugin directory (auto-detected if omitted)"),
):
    """
    Install the Campy plugin (MCP config + skills) into detected AI agents.
    """
    from campy.cli.plugin_installer import install_plugin_for_agents
    install_plugin_for_agents(target=target, plugin_dir=plugin_dir)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/cli/test_install_plugin.py::test_install_plugin_help -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add campy/cli/main.py tests/cli/test_install_plugin.py
git commit -m "feat(B255): add install-plugin CLI command skeleton"
```

---

### Task 2: Create Plugin Installer Module

**Files:**
- Create: `campy/cli/plugin_installer.py`
- Test: `tests/cli/test_plugin_installer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_plugin_installer.py
import tempfile
from pathlib import Path
from campy.cli.plugin_installer import find_plugin_dir, install_claude_code_plugin

def test_find_plugin_dir():
    """Should find the plugin/ dir relative to repo root."""
    result = find_plugin_dir()
    assert result is not None
    assert (result / ".claude-plugin" / "plugin.json").exists()

def test_install_claude_code_plugin_creates_mcp_config(tmp_path):
    """Should create .mcp.json in the target directory."""
    plugin_dir = find_plugin_dir()
    target_dir = tmp_path / ".claude" / "plugins" / "hippocampy"
    install_claude_code_plugin(plugin_dir, target_dir)
    assert (target_dir / ".mcp.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_plugin_installer.py -v`
Expected: FAIL — `plugin_installer` module doesn't exist

- [ ] **Step 3: Implement plugin_installer.py**

```python
# campy/cli/plugin_installer.py
"""Install Campy plugin into AI agents."""
import json
import logging
import shutil
from pathlib import Path
from typing import Optional

from rich.console import Console
from campy.cli.detect import detect_installed_clients

console = Console()
logger = logging.getLogger(__name__)


def find_plugin_dir(hint: Optional[str] = None) -> Optional[Path]:
    """Locate the plugin/ directory in the repo."""
    if hint:
        p = Path(hint).expanduser().resolve()
        if (p / ".claude-plugin" / "plugin.json").exists():
            return p
    # Walk up from this file to find repo root
    here = Path(__file__).resolve()
    for parent in [here.parent, here.parent.parent, here.parent.parent.parent]:
        candidate = parent / "plugin"
        if (candidate / ".claude-plugin" / "plugin.json").exists():
            return candidate
    return None


def install_claude_code_plugin(plugin_dir: Path, target_dir: Path) -> bool:
    """Install plugin files for Claude Code."""
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        # Copy .claude-plugin/
        plugin_meta_src = plugin_dir / ".claude-plugin"
        plugin_meta_dst = target_dir / ".claude-plugin"
        if plugin_meta_dst.exists():
            shutil.rmtree(plugin_meta_dst)
        shutil.copytree(plugin_meta_src, plugin_meta_dst)
        # Copy .mcp.json
        mcp_src = plugin_dir / ".mcp.json"
        mcp_dst = target_dir / ".mcp.json"
        shutil.copy2(mcp_src, mcp_dst)
        # Copy skills/
        skills_src = plugin_dir / "skills"
        skills_dst = target_dir / "skills"
        if skills_dst.exists():
            shutil.rmtree(skills_dst)
        shutil.copytree(skills_src, skills_dst)
        logger.info(f"Claude Code plugin installed to {target_dir}")
        return True
    except Exception as e:
        logger.error(f"Failed to install Claude Code plugin: {e}")
        return False


def install_codex_plugin(plugin_dir: Path) -> bool:
    """Install memory skill for Codex."""
    try:
        skill_src = plugin_dir / "skills" / "recall" / "SKILL.md"
        if not skill_src.exists():
            logger.error("recall skill not found in plugin dir")
            return False
        target = Path.home() / ".codex" / "skills" / "campy-memory" / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_src, target)
        logger.info(f"Codex memory skill installed to {target}")
        return True
    except Exception as e:
        logger.error(f"Failed to install Codex plugin: {e}")
        return False


def install_vscode_plugin(plugin_dir: Path) -> bool:
    """Verify VS Code MCP config points to Campy daemon."""
    # VS Code MCP registration is handled by register_vscode()
    # This just verifies the .mcp.json connection works
    mcp_json = plugin_dir / ".mcp.json"
    if not mcp_json.exists():
        return False
    config = json.loads(mcp_json.read_text())
    url = config.get("mcpServers", {}).get("hippocampy", {}).get("url", "")
    if "127.0.0.1:7799" in url:
        logger.info("VS Code: MCP SSE endpoint configured correctly")
        return True
    return False


def install_gemini_plugin(plugin_dir: Path) -> bool:
    """Install recall instructions for Gemini CLI."""
    # Gemini reads GEMINI.md — recall config handled by register_gemini_cli()
    logger.info("Gemini CLI: plugin config deferred to register_gemini_cli()")
    return True


def install_plugin_for_agents(
    target: Optional[str] = None,
    plugin_dir: Optional[str] = None,
) -> dict:
    """Install plugin for all detected agents (or a specific target)."""
    pdir = find_plugin_dir(plugin_dir)
    if pdir is None:
        console.print("[red]Could not find plugin directory. Use --plugin-dir to specify.[/red]")
        return {}

    clients = detect_installed_clients()
    results = {}

    installers = {
        "claude-code": lambda: install_claude_code_plugin(
            pdir,
            Path.home() / ".claude" / "plugins" / "hippocampy",
        ),
        "codex": lambda: install_codex_plugin(pdir),
        "vscode": lambda: install_vscode_plugin(pdir),
        "gemini-cli": lambda: install_gemini_plugin(pdir),
    }

    if target:
        if target in installers:
            console.print(f"[blue]Installing plugin for {target}...[/blue]")
            results[target] = installers[target]()
        else:
            console.print(f"[red]Unknown target: {target}[/red]")
    else:
        for agent_key, installer in installers.items():
            if clients.get(agent_key) or clients.get(agent_key.replace("-", "_")):
                console.print(f"[green]Detected {agent_key}. Installing plugin...[/green]")
                results[agent_key] = installer()
            else:
                console.print(f"[dim]{agent_key} not detected, skipping.[/dim]")

    # Summary
    for agent, success in results.items():
        status = "[green]✓[/green]" if success else "[red]✗[/red]"
        console.print(f"  {status} {agent}")

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/cli/test_plugin_installer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add campy/cli/plugin_installer.py tests/cli/test_plugin_installer.py
git commit -m "feat(B255): implement plugin installer for all agents"
```

---

### Task 3: Add Plugin Status to Doctor

**Files:**
- Modify: `campy/cli/doctor.py`
- Test: `tests/cli/test_doctor_plugin.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/cli/test_doctor_plugin.py
from campy.cli.doctor import DoctorChecker

def test_doctor_has_plugin_check():
    """DoctorChecker should have a check_plugin_status method."""
    checker = DoctorChecker.__new__(DoctorChecker)
    assert hasattr(checker, "check_plugin_status")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/cli/test_doctor_plugin.py -v`
Expected: FAIL — `check_plugin_status` not found

- [ ] **Step 3: Add plugin status check to DoctorChecker**

In `campy/cli/doctor.py`, add to the `DoctorChecker` class:

```python
def check_plugin_status(self) -> bool:
    """Check if plugin is installed for detected agents."""
    from campy.cli.plugin_installer import find_plugin_dir
    from campy.cli.detect import detect_installed_clients

    plugin_dir = find_plugin_dir()
    if plugin_dir is None:
        self._warn("Plugin directory not found")
        return False

    clients = detect_installed_clients()
    all_ok = True

    if clients.get("claude-code") or clients.get("claude_code"):
        target = Path.home() / ".claude" / "plugins" / "hippocampy"
        if (target / ".mcp.json").exists():
            self._pass("Claude Code plugin installed")
        else:
            self._fail("Claude Code plugin NOT installed — run: campy install-plugin")
            all_ok = False

    if clients.get("codex"):
        skill = Path.home() / ".codex" / "skills" / "campy-memory" / "SKILL.md"
        if skill.exists():
            self._pass("Codex memory skill installed")
        else:
            self._fail("Codex memory skill NOT installed — run: campy install-plugin")
            all_ok = False

    return all_ok
```

Also add `check_plugin_status` call to `run_all_checks()`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/cli/test_doctor_plugin.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add campy/cli/doctor.py tests/cli/test_doctor_plugin.py
git commit -m "feat(B255): add plugin status check to campy doctor"
```

---

### Task 4: Integration Test

**Files:**
- Create: `tests/cli/test_install_plugin_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/cli/test_install_plugin_integration.py
import tempfile
from pathlib import Path
from campy.cli.plugin_installer import find_plugin_dir, install_claude_code_plugin

def test_full_plugin_install_to_temp_dir():
    """Full plugin install creates all expected files."""
    plugin_dir = find_plugin_dir()
    assert plugin_dir is not None

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "hippocampy"
        result = install_claude_code_plugin(plugin_dir, target)
        assert result is True
        assert (target / ".claude-plugin" / "plugin.json").exists()
        assert (target / ".mcp.json").exists()
        assert (target / "skills" / "recall" / "SKILL.md").exists()
        assert (target / "skills" / "memory-awareness" / "SKILL.md").exists()
        assert (target / "skills" / "quest-management" / "SKILL.md").exists()
        assert (target / "skills" / "status" / "SKILL.md").exists()

def test_install_is_idempotent():
    """Running install twice doesn't error or duplicate files."""
    plugin_dir = find_plugin_dir()
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "hippocampy"
        install_claude_code_plugin(plugin_dir, target)
        result = install_claude_code_plugin(plugin_dir, target)
        assert result is True
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/cli/test_install_plugin_integration.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/cli/test_install_plugin_integration.py
git commit -m "test(B255): add plugin installation integration tests"
```
