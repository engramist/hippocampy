import os
import subprocess
import json
import logging
from typing import Dict, Any, Optional

def register_claude_code(adapter_path: str) -> bool:
    """Register SideQuests with Claude Code using 'claude mcp add'."""
    try:
        # Use absolute path to python executable
        import sys
        python_exe = sys.executable
        
        cmd = ["claude", "mcp", "add", "sidequests", "--", python_exe, adapter_path]
        logging.info(f"Running command: {' '.join(cmd)}")
        # Claude Code might prompt for confirmation, but 'add' is usually non-interactive or has flags.
        # We'll try to run it and capture output.
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logging.info(f"Claude Code registration output: {result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to register with Claude Code: {e.stderr}")
        # Even if it fails, it might be already registered.
        # Check if error message says it exists.
        if "already exists" in e.stderr.lower():
            return True
        return False
    except FileNotFoundError:
        logging.error("Claude Code CLI ('claude') not found in PATH.")
        return False

def register_claude_desktop(adapter_path: str, config_path: str) -> bool:
    """Register SideQuests with Claude Desktop by editing its config file."""
    try:
        import sys
        python_exe = sys.executable
        
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
        
        # Use sidequests-brain as key to match tests
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
    """
    Register SideQuests with Codex by editing its config file.
    Codex uses TOML at ~/.codex/config.toml
    """
    try:
        import sys
        python_exe = sys.executable
        config_path = os.path.expanduser("~/.codex/config.toml")
        
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        # Simple TOML appending if not using a toml library
        # B-1: Minimum safe changes.
        entry = f'\n[mcp_servers.sidequests]\ncommand = "{python_exe}"\nargs = ["{adapter_path}"]\n'
        
        content = ""
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                content = f.read()
        
        if "[mcp_servers.sidequests]" in content:
            # Already exists, we should probably replace it, but for B-1 idempotency:
            # If we want to be safe, we just don't add it again.
            logging.info("Codex registration already exists.")
            return True
            
        with open(config_path, "a") as f:
            f.write(entry)
            
        logging.info(f"Codex registration success: {config_path}")
        return True
    except Exception as e:
        logging.error(f"Failed to register with Codex: {str(e)}")
        return False

def register_gemini_cli(adapter_path: str) -> bool:
    """Register with Gemini CLI (self)."""
    try:
        # gemini activate-skill sidequests -- python adapter_path
        # Placeholder for actual command
        return True
    except Exception:
        return False
