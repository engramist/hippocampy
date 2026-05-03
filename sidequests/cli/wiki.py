import os
import platform
import subprocess
import logging
from pathlib import Path
import typer

logger = logging.getLogger(__name__)

app = typer.Typer(help="Manage the SideQuests Brain Wiki projection.")

def get_persona_config(ctx: typer.Context, persona_name: str = "default") -> dict:
    wiki_cfg = ctx.obj.get("config", {}).get("wiki_projection", {})
    personas = wiki_cfg.get("personas", [])
    
    if not personas:
        # Fallback to top-level default config
        return {
            "name": "default",
            "vault_dir": wiki_cfg.get("vault_dir", "wiki"),
            "output_dir": wiki_cfg.get("output_dir", "wiki/personas/default"),
            "obsidian_vault_name": wiki_cfg.get("obsidian_vault_name", "SideQuests Brain")
        }
    
    # Search for persona by name
    for p in personas:
        if p.get("name") == persona_name:
            # Inject vault_dir and obsidian_vault_name if missing
            if "vault_dir" not in p:
                p["vault_dir"] = wiki_cfg.get("vault_dir", "wiki")
            if "obsidian_vault_name" not in p:
                p["obsidian_vault_name"] = wiki_cfg.get("obsidian_vault_name", "SideQuests Brain")
            return p
            
    return None

@app.command("path")
def wiki_path(
    ctx: typer.Context,
    persona: str = typer.Option("default", help="Persona projection to locate")
):
    """Print the absolute path to the generated wiki vault or persona home."""
    p_cfg = get_persona_config(ctx, persona)
    if not p_cfg:
        typer.secho(f"Error: Persona '{persona}' not found in config.", fg=typer.colors.RED)
        raise typer.Exit(1)
        
    output_dir = Path(p_cfg.get("output_dir")).resolve()
    typer.echo(str(output_dir))

@app.command("status")
def wiki_status(
    ctx: typer.Context,
    persona: str = typer.Option("default", help="Persona projection to check")
):
    """Report the current status of the wiki projection."""
    wiki_cfg = ctx.obj.get("config", {}).get("wiki_projection", {})
    enabled = wiki_cfg.get("enabled", False)
    
    p_cfg = get_persona_config(ctx, persona)
    if not p_cfg:
        typer.secho(f"Error: Persona '{persona}' not found in config.", fg=typer.colors.RED)
        raise typer.Exit(1)
        
    vault_dir = Path(p_cfg.get("vault_dir", "wiki")).resolve()
    output_dir = Path(p_cfg.get("output_dir")).resolve()
    
    typer.echo(f"Wiki Projection: {'ENABLED' if enabled else 'DISABLED'}")
    typer.echo(f"Vault Path:      {vault_dir}")
    typer.echo(f"Persona:         {persona}")
    typer.echo(f"Persona Path:    {output_dir}")
    
    if output_dir.exists():
        page_count = len(list(output_dir.rglob("*.md")))
        typer.echo(f"Total Pages:     {page_count}")
        
        # Check for generated_at in Home.md
        home_path = output_dir / "Home.md"
        if home_path.exists():
            try:
                with open(home_path, 'r') as f:
                    for line in f:
                        if "(" in line and ")" in line and "# " in line:
                            # Heuristic for title (date)
                            ts = line.split("(", 1)[1].split(")", 1)[0]
                            typer.echo(f"Last Generated:  {ts}")
                            break
            except Exception:
                pass
    else:
        typer.echo("Persona status:  NOT GENERATED")

@app.command("open")
def wiki_open(
    ctx: typer.Context,
    persona: str = typer.Option("default", help="Persona projection to open")
):
    """Open the wiki in Obsidian or the default file browser."""
    p_cfg = get_persona_config(ctx, persona)
    if not p_cfg:
        typer.secho(f"Error: Persona '{persona}' not found in config.", fg=typer.colors.RED)
        raise typer.Exit(1)
        
    vault_dir = Path(p_cfg.get("vault_dir", "wiki")).resolve()
    output_dir = Path(p_cfg.get("output_dir")).resolve()
    vault_name = p_cfg.get("obsidian_vault_name", "SideQuests Brain")

    if not output_dir.exists():
        typer.secho(f"Error: Persona directory {output_dir} does not exist. Run a sweep first.", fg=typer.colors.RED)
        raise typer.Exit(1)

    system = platform.system()
    opened = False

    if system == "Darwin":  # macOS
        try:
            import urllib.parse
            encoded_vault = urllib.parse.quote(vault_name)
            # Try to open specific file if persona is not default
            rel_home = os.path.relpath(output_dir / "Home.md", vault_dir)
            encoded_file = urllib.parse.quote(rel_home)
            uri = f"obsidian://open?vault={encoded_vault}&file={encoded_file}"
            
            subprocess.run(["open", uri], check=True, capture_output=True)
            typer.echo(f"Attempted to open Obsidian vault: {vault_name} at {rel_home}")
            opened = True
        except Exception:
            subprocess.run(["open", str(output_dir)])
            opened = True
    elif system == "Windows":
        os.startfile(str(output_dir))
        opened = True
    elif system == "Linux":
        try:
            subprocess.run(["xdg-open", str(output_dir)], check=True)
            opened = True
        except Exception:
            pass

    if opened:
        typer.echo(f"Opened wiki folder: {output_dir}")
    else:
        typer.echo(f"Could not open automatically. Path: {output_dir}")
