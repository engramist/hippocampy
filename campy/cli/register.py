from pathlib import Path
import json
import logging
import os
import re
import subprocess
import sys
import tomllib
from typing import Dict, Any, Optional
from importlib import resources
from campy.branding import (
    LEGACY_MCP_SERVER,
    LEGACY_SKILL_NAME,
    PRIMARY_MCP_SERVER,
    PRIMARY_SKILL_NAME,
)


def _repo_root_for_adapter(adapter_path: str) -> Path:
    """Return the sidequests-brain repo root for a top-level adapter path."""
    path = Path(adapter_path).expanduser().resolve()
    # Expected shape: <repo>/adapters/<client>/adapter.py
    try:
        return path.parents[2]
    except IndexError:
        return Path.cwd()


def _python_for_adapter(adapter_path: str) -> str:
    """Prefer the repo venv so client adapters see SideQuests dependencies."""
    repo_root = _repo_root_for_adapter(adapter_path)
    for candidate in (
        repo_root / ".venv" / "bin" / "python",
        repo_root / ".venv" / "bin" / "python3.12",
    ):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def _strip_codex_adapter_path_tables(content: str, adapter_path: str) -> str:
    """Remove malformed TOML tables like ["/repo/adapters/codex/adapter.py"]."""
    escaped = re.escape(str(Path(adapter_path).expanduser().resolve()))
    pattern = re.compile(rf'^\s*\["{escaped}"\]\s*\n?', re.MULTILINE)
    return pattern.sub("", content)


def _upsert_codex_mcp_block(content: str, python_exe: str, adapter_path: str) -> str:
    """Replace existing Campy/legacy SideQuests Codex MCP blocks."""
    for server_name in (PRIMARY_MCP_SERVER, LEGACY_MCP_SERVER, "sidequests-brain", "sidequests-brain-desktop", "hippocampy"):
        block_pattern = re.compile(
            rf'^\s*\[mcp_servers\.{re.escape(server_name)}\]\s*\n'
            r'(?:^[^\[][^\n]*\n?)*',
            re.MULTILINE,
        )
        content = block_pattern.sub("", content).rstrip() + "\n"
    block = (
        f'\n[mcp_servers.{PRIMARY_MCP_SERVER}]\n'
        f'command = "{python_exe}"\n'
        f'args = ["-m", "campy.adapters.mcp_server"]\n'
    )
    return content + block


def install_codex_memory_skill(project_root: Path) -> Path | None:
    """Install the universal Campy memory policy as a Codex skill.

    If the destination already contains user-modified content, keep it intact and
    write the managed copy beside it as `SKILL.md.new`.
    """
    source = project_root / "skills" / PRIMARY_SKILL_NAME / "SKILL.md"
    if source.exists():
        source_text = source.read_text()
    else:
        try:
            source_text = (
                resources.files("campy.data")
                .joinpath(PRIMARY_SKILL_NAME, "SKILL.md")
                .read_text()
            )
        except Exception:
            try:
                source_text = (
                    resources.files("campy.data")
                    .joinpath(LEGACY_SKILL_NAME, "SKILL.md")
                    .read_text()
                )
            except Exception:
                return None

    target = Path.home() / ".codex" / "skills" / PRIMARY_SKILL_NAME / "SKILL.md"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    if target.exists() and target.read_text() != source_text:
        target = target.with_suffix(target.suffix + ".new")

    target.write_text(source_text)
    return target


def register_claude_code(adapter_path: str) -> bool:
    """Register Campy with Claude Code using 'claude mcp add'."""
    try:
        python_exe = _python_for_adapter(adapter_path)
        # Use module-mode registration
        cmd = ["claude", "mcp", "add", PRIMARY_MCP_SERVER, "--", python_exe, "-m", "campy.adapters.mcp_server"]
        logging.info(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logging.info(f"Claude Code registration output: {result.stdout}")
        _register_claude_code_hook(adapter_path)
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to register with Claude Code: {e.stderr}")
        if "already exists" in e.stderr.lower():
            _register_claude_code_hook(adapter_path)
            return True
        return False
    except FileNotFoundError:
        logging.error("Claude Code CLI ('claude') not found in PATH.")
        return False


def _register_claude_code_hook(adapter_path: str) -> None:
    """Best-effort passive user-turn hook registration for Claude Code."""
    try:
        repo_root = _repo_root_for_adapter(adapter_path)
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from adapters.claude_code.setup import register

        register(project_root=repo_root)
    except Exception:
        logging.exception("Claude Code hook registration skipped")


def register_claude_desktop(adapter_path: str, config_path: str) -> bool:
    """Register Campy with Claude Desktop by editing its config file."""
    try:
        python_exe = _python_for_adapter(adapter_path)
        if not os.path.exists(config_path):
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            config = {"mcpServers": {}}
        else:
            with open(config_path, "r") as f:
                try:
                    config = json.load(f)
                except json.JSONDecodeError:
                    config = {"mcpServers": {}}

        if "mcpServers" not in config:
            config["mcpServers"] = {}

        # Cleanup legacy names and converge to PRIMARY_MCP_SERVER ("campy")
        for legacy in ("sidequests", "sidequests-brain", "sidequests-brain-desktop", "hippocampy"):
            if legacy != PRIMARY_MCP_SERVER:
                config["mcpServers"].pop(legacy, None)

        config["mcpServers"][PRIMARY_MCP_SERVER] = {
            "command": python_exe,
            "args": ["-m", "campy.adapters.claude_desktop"]
        }

        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

        logging.info(f"Claude Desktop registration success: {config_path}")
        return True
    except Exception as e:
        logging.error(f"Failed to register with Claude Desktop: {str(e)}")
        return False


def register_chatgpt_desktop() -> bool:
    """
    Register Campy with ChatGPT Desktop.

    ChatGPT Desktop primarily uses MCP-over-SSE (Connectors).
    This function prints the necessary URL for manual registration.
    """
    print("\n  ChatGPT Desktop — Campy connector registration required:")
    print("  1. Open ChatGPT Desktop Settings > Apps > Add Connector")
    print("  2. Paste this URL: http://127.0.0.1:7799/sse")
    print("  (Requires the Brain Daemon to be running.)\n")
    return True


def register_codex(adapter_path: str) -> bool:
    """Register Campy with Codex by editing ~/.codex/config.toml."""
    try:
        python_exe = _python_for_adapter(adapter_path)
        canonical_adapter = str(Path(adapter_path).expanduser().resolve())
        project_root = _repo_root_for_adapter(canonical_adapter)
        config_path = Path(os.path.expanduser("~/.codex/config.toml"))
        config_path.parent.mkdir(parents=True, exist_ok=True)

        content = config_path.read_text() if config_path.exists() else ""
        content = _strip_codex_adapter_path_tables(content, canonical_adapter)
        content = _upsert_codex_mcp_block(content, python_exe, canonical_adapter)
        tomllib.loads(content)
        config_path.write_text(content)
        skill_path = install_codex_memory_skill(project_root)
        logging.info(f"Codex registration success: {config_path}")
        if skill_path:
            logging.info(f"Codex Campy memory skill installed: {skill_path}")
        return True
    except Exception as e:
        logging.error(f"Failed to register with Codex: {str(e)}")
        return False


def _vscode_mcp_config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "Code" / "User" / "mcp.json"
    return Path.home() / ".config" / "Code" / "User" / "mcp.json"


def register_vscode(adapter_path: str, config_path: str | None = None) -> bool:
    """Register Campy as a VS Code/Copilot MCP stdio server and add recall instructions."""
    try:
        python_exe = _python_for_adapter(adapter_path)
        path = Path(config_path).expanduser() if config_path else _vscode_mcp_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                config = json.loads(path.read_text())
            except json.JSONDecodeError:
                config = {}
        else:
            config = {}
        servers = config.setdefault("servers", {})
        servers.pop(LEGACY_MCP_SERVER, None)
        servers[PRIMARY_MCP_SERVER] = {
            "type": "stdio",
            "command": python_exe,
            "args": ["-m", "campy.adapters.mcp_server"],
        }
        path.write_text(json.dumps(config, indent=2) + "\n")
        logging.info(f"VS Code MCP registration success: {path}")
        
        # Also add recall instructions to copilot-instructions.md if .github exists
        repo_root = _repo_root_for_adapter(adapter_path)
        if (repo_root / ".github").is_dir():
            _add_copilot_recall_instructions(repo_root)
        
        return True
    except Exception as e:
        logging.error(f"Failed to register with VS Code: {str(e)}")
        return False


def _add_copilot_recall_instructions(repo_root: Path) -> None:
    """Add Campy recall instructions to .github/copilot-instructions.md."""
    instructions_path = repo_root / ".github" / "copilot-instructions.md"
    
    skill_source = repo_root / "campy" / "data" / "campy-memory" / "SKILL.md"
    if not skill_source.exists():
        return
    
    marker_start = "<!-- CAMPY-MEMORY-START -->"
    marker_end = "<!-- CAMPY-MEMORY-END -->"
    
    skill_content = skill_source.read_text()
    campy_block = f"{marker_start}\n## Campy Memory\n\n{skill_content}\n{marker_end}"
    
    if instructions_path.exists():
        existing = instructions_path.read_text()
        if marker_start in existing:
            pattern = re.compile(f"{re.escape(marker_start)}.*?{re.escape(marker_end)}", re.DOTALL)
            updated = pattern.sub(campy_block, existing)
        else:
            updated = existing + "\n\n" + campy_block + "\n"
        instructions_path.write_text(updated)
    # Don't create the file if .github/ doesn't exist — not our responsibility


def register_gemini_cli(adapter_path: str) -> bool:
    """Register Campy with Gemini CLI via GEMINI.md instructions."""
    try:
        repo_root = _repo_root_for_adapter(adapter_path)
        
        # Install universal memory skill content into GEMINI.md
        skill_source = repo_root / "campy" / "data" / "campy-memory" / "SKILL.md"
        if not skill_source.exists():
            logging.warning("Universal memory skill not found for Gemini CLI")
            return True  # Non-fatal — MCP server still works
        
        gemini_md = repo_root / "GEMINI.md"
        skill_content = skill_source.read_text()
        
        # Wrap in a Campy section
        campy_section = (
            "\n\n## Campy Memory Integration\n\n"
            "The Campy MCP server provides persistent AI memory. "
            "Follow the recall protocol below.\n\n"
            + skill_content
        )
        
        marker_start = "<!-- CAMPY-MEMORY-START -->"
        marker_end = "<!-- CAMPY-MEMORY-END -->"
        
        if gemini_md.exists():
            existing = gemini_md.read_text()
            if marker_start in existing:
                # Replace existing section
                pattern = re.compile(
                    f"{re.escape(marker_start)}.*?{re.escape(marker_end)}",
                    re.DOTALL,
                )
                updated = pattern.sub(
                    f"{marker_start}\n{campy_section}\n{marker_end}",
                    existing,
                )
            else:
                updated = existing + f"\n{marker_start}\n{campy_section}\n{marker_end}\n"
        else:
            updated = f"# Gemini CLI Instructions\n\n{marker_start}\n{campy_section}\n{marker_end}\n"
        
        gemini_md.write_text(updated)
        logging.info(f"Gemini CLI recall instructions written to {gemini_md}")
        return True
    except Exception as e:
        logging.error(f"Failed to register Gemini CLI: {e}")
        return False


def register_hermes(adapter_path: str = None) -> bool:
    """
    Register Campy memory with Hermes agent framework.
    
    Hermes agents can import and use the HermesAdapter to access
    Campy memory via the REST API endpoints.
    """
    try:
        # Verify that the adapter module is importable
        try:
            from adapters.hermes.adapter import HermesAdapter, get_adapter
            logging.info("Hermes adapter module verified")
        except ImportError as e:
            logging.warning(f"Hermes adapter import failed (may be OK): {e}")
            # Non-fatal — Hermes can still use the adapter if installed separately
        
        logging.info("Hermes agent adapter registered (ready for import)")
        return True
    except Exception as e:
        logging.error(f"Failed to register Hermes: {e}")
        return False

