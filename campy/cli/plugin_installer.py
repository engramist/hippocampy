"""Install Campy plugin into AI agents."""
import json
import logging
import shutil
from pathlib import Path
from typing import Optional
from datetime import datetime

from rich.console import Console
from campy.cli.detect import detect_all

console = Console()
logger = logging.getLogger(__name__)


# Upstream process-skill names that can confuse users when Campy variants are installed.
# We archive these (move, not delete) in Codex so the picker has one clear Campy option.
CODEX_LEGACY_PROCESS_SKILL_NAMES = {
    "diagnose",
    "grill",
    "grill-me",
    "grill-with-docs",
    "handoff",
    "improve-architecture",
    "improve-codebase-architecture",
    "tdd",
}


def _archive_codex_skill_dirs(skills_root: Path, skill_names: set[str]) -> int:
    """Archive known duplicate skill directories under a timestamped folder."""
    to_archive: list[Path] = []
    for name in sorted(skill_names):
        candidate = skills_root / name
        if candidate.is_dir():
            to_archive.append(candidate)

    if not to_archive:
        return 0

    archive_root = skills_root / "_archived_by_campy"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = archive_root / stamp
    archive_dir.mkdir(parents=True, exist_ok=True)

    moved = 0
    for src in to_archive:
        dst = archive_dir / src.name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.move(str(src), str(dst))
        moved += 1
    return moved


def _copy_skills_tree(plugin_dir: Path, target_skills_dir: Path) -> bool:
    """Copy all skill directories from plugin source to target location."""
    skills_src = plugin_dir / "skills"
    if not skills_src.exists():
        logger.error(f"Skills source not found: {skills_src}")
        return False
    try:
        target_skills_dir.parent.mkdir(parents=True, exist_ok=True)
        if target_skills_dir.exists():
            shutil.rmtree(target_skills_dir)
        shutil.copytree(skills_src, target_skills_dir)
        return True
    except Exception as e:
        logger.error(f"Failed to copy skills to {target_skills_dir}: {e}")
        return False


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
        if not _copy_skills_tree(plugin_dir, target_dir / "skills"):
            return False
        logger.info(f"Claude Code plugin installed to {target_dir}")
        return True
    except Exception as e:
        logger.error(f"Failed to install Claude Code plugin: {e}")
        return False


def install_codex_plugin(plugin_dir: Path) -> bool:
    """Install all Campy skills for Codex CLI."""
    try:
        skills_src = plugin_dir / "skills"
        if not skills_src.exists():
            logger.error(f"Skills source not found: {skills_src}")
            return False
        target = Path.home() / ".codex" / "skills"
        target.mkdir(parents=True, exist_ok=True)
        # Archive known non-Campy process-skill duplicates to reduce picker ambiguity.
        archived = _archive_codex_skill_dirs(target, CODEX_LEGACY_PROCESS_SKILL_NAMES)
        if archived:
            logger.info(f"Codex: archived {archived} legacy process skill(s) under {target / '_archived_by_campy'}")
        # Remove legacy single-skill directory
        legacy = target / "campy-memory"
        if legacy.exists():
            shutil.rmtree(legacy)
        # Copy each skill directory individually (preserve non-Campy skills)
        count = 0
        for skill_dir in sorted(skills_src.iterdir()):
            if skill_dir.is_dir():
                dst = target / skill_dir.name
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(skill_dir, dst)
                count += 1
        logger.info(f"Codex: {count} skills installed to {target}")
        # Install hooks
        hooks_src = plugin_dir.parent / "adapters" / "codex" / "hooks"
        if hooks_src.exists():
            hooks_dst = Path.home() / ".codex" / "hooks" / "campy"
            hooks_dst.mkdir(parents=True, exist_ok=True)
            hook_count = 0
            for hook_file in sorted(hooks_src.glob("*.py")):
                if hook_file.name == "__init__.py":
                    continue
                dst = hooks_dst / hook_file.name
                shutil.copy2(hook_file, dst)
                dst.chmod(0o755)
                hook_count += 1
            logger.info(f"Codex: {hook_count} hooks installed to {hooks_dst}")
            # Write hook config
            try:
                from adapters.codex.setup import _write_hook_config
                _write_hook_config()
            except Exception as e:
                logger.warning(f"Codex hook config not written: {e}")
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
    """Install all Campy skills for Gemini CLI."""
    try:
        skills_src = plugin_dir / "skills"
        if not skills_src.exists():
            logger.error(f"Skills source not found: {skills_src}")
            return False
        target = Path.home() / ".gemini" / "skills"
        target.mkdir(parents=True, exist_ok=True)
        # Copy each skill directory individually (preserve non-Campy skills)
        count = 0
        for skill_dir in sorted(skills_src.iterdir()):
            if skill_dir.is_dir():
                dst = target / skill_dir.name
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(skill_dir, dst)
                count += 1
        logger.info(f"Gemini CLI: {count} skills installed to {target}")
        # Install hooks
        hooks_src = plugin_dir.parent / "adapters" / "gemini_cli" / "hooks"
        if hooks_src.exists():
            hooks_dst = Path.home() / ".gemini" / "hooks" / "campy"
            hooks_dst.mkdir(parents=True, exist_ok=True)
            hook_count = 0
            for hook_file in sorted(hooks_src.glob("*.py")):
                if hook_file.name == "__init__.py":
                    continue
                dst = hooks_dst / hook_file.name
                shutil.copy2(hook_file, dst)
                dst.chmod(0o755)
                hook_count += 1
            logger.info(f"Gemini CLI: {hook_count} hooks installed to {hooks_dst}")
            # Write hook config
            try:
                from adapters.gemini_cli.setup import _write_hook_config
                _write_hook_config()
            except Exception as e:
                logger.warning(f"Gemini CLI hook config not written: {e}")
        return True
    except Exception as e:
        logger.error(f"Failed to install Gemini CLI plugin: {e}")
        return False


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
