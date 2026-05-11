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
    """Replace any existing SideQuests Codex MCP block with the canonical one."""
    block_pattern = re.compile(
        r'^\s*\[mcp_servers\.sidequests\]\s*\n'
        r'(?:^[^\[][^\n]*\n?)*',
        re.MULTILINE,
    )
    content = block_pattern.sub("", content).rstrip() + "\n"
    block = (
        f'\n[mcp_servers.sidequests]\n'
        f'command = "{python_exe}"\n'
        f'args = ["{adapter_path}"]\n'
    )
    return content + block


def install_codex_memory_skill(project_root: Path) -> Path | None:
    """Install the universal SideQuests memory policy as a Codex skill.

    If the destination already contains user-modified content, keep it intact and
    write the managed copy beside it as `SKILL.md.new`.
    """
    source = project_root / "skills" / "sidequests-memory" / "SKILL.md"
    if source.exists():
        source_text = source.read_text()
    else:
        try:
            source_text = (
                resources.files("sidequests.data")
                .joinpath("sidequests-memory", "SKILL.md")
                .read_text()
            )
        except Exception:
            return None

    target = Path.home() / ".codex" / "skills" / "sidequests-memory" / "SKILL.md"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    if target.exists() and target.read_text() != source_text:
        target = target.with_suffix(target.suffix + ".new")

    target.write_text(source_text)
    return target


def register_claude_code(adapter_path: str) -> bool:
    """Register SideQuests with Claude Code using 'claude mcp add'."""
    try:
        python_exe = _python_for_adapter(adapter_path)
        cmd = ["claude", "mcp", "add", "sidequests", "--", python_exe, adapter_path]
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
    """Register SideQuests with Claude Desktop by editing its config file."""
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

        config["mcpServers"]["sidequests-brain"] = {
            "command": python_exe,
            "args": [adapter_path]
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
    Register SideQuests with ChatGPT Desktop.

    ChatGPT Desktop primarily uses MCP-over-SSE (Connectors).
    This function prints the necessary URL for manual registration.
    """
    print("\n  ChatGPT Desktop — registration required:")
    print("  1. Open ChatGPT Desktop Settings > Apps > Add Connector")
    print("  2. Paste this URL: http://127.0.0.1:7799/sse")
    print("  (Requires the Brain Daemon to be running.)\n")
    return True


def register_codex(adapter_path: str) -> bool:
    """Register SideQuests with Codex by editing ~/.codex/config.toml."""
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
            logging.info(f"Codex SideQuests memory skill installed: {skill_path}")
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
    """Register SideQuests as a VS Code/Copilot MCP stdio server."""
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
        servers["sidequests"] = {
            "type": "stdio",
            "command": python_exe,
            "args": ["-m", "sidequests.adapters.mcp_server"],
        }
        path.write_text(json.dumps(config, indent=2) + "\n")
        logging.info(f"VS Code MCP registration success: {path}")
        return True
    except Exception as e:
        logging.error(f"Failed to register with VS Code: {str(e)}")
        return False


def register_gemini_cli(adapter_path: str) -> bool:
    """Register with Gemini CLI (self)."""
    try:
        return True
    except Exception:
        return False
