"""Install Campy plugin into AI agents."""
import json
import logging
import shutil
from pathlib import Path
from typing import Optional

from rich.console import Console
from campy.cli.detect import detect_all

console = Console()
logger = logging.getLogger(__name__)


def find_plugin_dir(hint: Optional[str] = None) -> Optional[Path]:
    """Locate the plugin/ directory in the repo or bundled package data."""
    if hint:
        p = Path(hint).expanduser().resolve()
        if (p / ".claude-plugin" / "plugin.json").exists():
            return p
    # Walk up from this file to find repo root plugin/ dir
    here = Path(__file__).resolve()
    for parent in [here.parent, here.parent.parent, here.parent.parent.parent]:
        candidate = parent / "plugin"
        if (candidate / ".claude-plugin" / "plugin.json").exists():
            return candidate
    # Fallback: bundled plugin data inside the installed package
    # Note: bundled copy uses "claude-plugin/" (no dot) because setuptools
    # skips hidden directories. install_claude_code_plugin handles both names.
    try:
        from importlib import resources
        pkg_plugin = resources.files("campy.data").joinpath("plugin")
        pkg_path = Path(str(pkg_plugin))
        if (pkg_path / "claude-plugin" / "plugin.json").exists():
            return pkg_path
        if (pkg_path / ".claude-plugin" / "plugin.json").exists():
            return pkg_path
    except Exception:
        pass
    return None


def install_claude_code_plugin(plugin_dir: Path, target_dir: Path) -> bool:
    """Install plugin files for Claude Code."""
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        # Copy .claude-plugin/ (bundled copy may be "claude-plugin/" without dot)
        plugin_meta_src = plugin_dir / ".claude-plugin"
        if not plugin_meta_src.exists():
            plugin_meta_src = plugin_dir / "claude-plugin"
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

    clients = detect_all()
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
