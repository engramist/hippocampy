"""Register Campy memory adapter with OpenClaw."""
from pathlib import Path
import json


def register_openclaw(adapter_path: str = None) -> bool:
    """
    Register Campy memory into OpenClaw config.
    
    OpenClaw config is typically at:
      ~/.openclaw/openclaw.json
    
    Adds a "campy-memory" capability to the MCP server registry.
    """
    import os
    
    if adapter_path is None:
        adapter_path = os.path.expanduser("~/.openclaw")
    
    config_path = Path(adapter_path) / "openclaw.json"
    
    if not config_path.exists():
        print(f"[yellow]OpenClaw config not found at {config_path}[/yellow]")
        return False
    
    try:
        config = json.loads(config_path.read_text())
    except Exception as e:
        print(f"[red]Failed to load OpenClaw config: {e}[/red]")
        return False
    
    # Ensure mcpServers section exists
    if "mcpServers" not in config:
        config["mcpServers"] = {}
    
    # Add campy-memory MCP server entry
    config["mcpServers"]["campy-memory"] = {
        "command": "python",
        "args": ["-m", "campy.cli.main", "mcp"],
        "description": "Campy memory recall and decision routing"
    }
    
    # Write back
    try:
        config_path.write_text(json.dumps(config, indent=2))
        print(f"[green]✓ Registered Campy memory in OpenClaw[/green]")
        return True
    except Exception as e:
        print(f"[red]Failed to write OpenClaw config: {e}[/red]")
        return False
