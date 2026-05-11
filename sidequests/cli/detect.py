import shutil
import os
import platform
from typing import Dict

def detect_claude_code() -> bool:
    """Check for 'claude' CLI in PATH."""
    return shutil.which("claude") is not None

def detect_claude_desktop() -> str:
    """Check for Claude Desktop config location."""
    system = platform.system()
    if system == "Darwin":
        config_path = os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json")
    elif system == "Windows":
        config_path = os.path.expanduser("~/AppData/Roaming/Claude/claude_desktop_config.json")
    else:
        return ""
        
    if os.path.exists(config_path):
        return config_path
    return ""

def detect_chatgpt_desktop() -> bool:
    """Check for ChatGPT Desktop (placeholder for now)."""
    # Currently just checking if on macOS/Windows as a proxy for availability
    return platform.system() in ["Darwin", "Windows"]

def detect_codex() -> bool:
    """Check for Codex CLI in PATH."""
    return shutil.which("codex") is not None

def detect_codex_desktop() -> bool:
    """Check for Codex Desktop."""
    # Placeholder: usually shares config with codex CLI or has similar paths
    return detect_codex()

def detect_gemini_cli() -> bool:
    """Check for 'gemini' CLI in PATH."""
    return shutil.which("gemini") is not None

def detect_vscode() -> bool:
    """Check for VS Code CLI or a standard user config directory."""
    if shutil.which("code") is not None:
        return True
    system = platform.system()
    if system == "Darwin":
        return os.path.isdir(os.path.expanduser("~/Library/Application Support/Code/User"))
    if system == "Windows":
        return os.path.isdir(os.path.expanduser("~/AppData/Roaming/Code/User"))
    return os.path.isdir(os.path.expanduser("~/.config/Code/User"))

def detect_openclaw() -> bool:
    """Check for 'openclaw' CLI in PATH."""
    return shutil.which("openclaw") is not None

def detect_installed_clients() -> Dict[str, bool]:
    """
    Return a map of client-key to presence.
    Required by installer and tests.
    """
    return {
        "claude-code": detect_claude_code(),
        "claude-desktop": bool(detect_claude_desktop()),
        "codex": detect_codex(),
        "codex-desktop": detect_codex_desktop(),
        "chatgpt-desktop": detect_chatgpt_desktop(),
        "gemini-cli": detect_gemini_cli(),
        "vscode": detect_vscode(),
        "openclaw": detect_openclaw(),
    }

def detect_all() -> Dict[str, bool]:
    """Compatibility wrapper for Typer setup command."""
    results = detect_installed_clients()
    # Also provide underscore versions for the Typer command if it still uses them
    compat = {k.replace("-", "_"): v for k, v in results.items()}
    results.update(compat)
    return results
