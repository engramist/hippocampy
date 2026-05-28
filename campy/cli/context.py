"""Campy context file management — generate CONTEXT.md, ADRs, and agent pointers from graph."""

import typer
import asyncio
from pathlib import Path
from typing import Optional
from rich.console import Console

app = typer.Typer(help="Campy context file management")
console = Console()


@app.command()
def regen(
    project: Optional[str] = typer.Option(
        None, "--project", "-p",
        help="Project path (defaults to current directory)"
    ),
):
    """Regenerate CONTEXT.md, ADRs, and agent pointers from the knowledge graph."""
    from campy.brain.thalamus.file_bridge import regen_all
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
    from campy.paths import get_database_path

    project_path = Path(project) if project else Path.cwd()
    db_path = get_database_path()

    if not db_path.exists():
        console.print("[red]Error:[/red] Campy database not found. Is the daemon running?")
        raise typer.Exit(1)

    db = KuzuClient(str(db_path), read_only=True)

    try:
        result = asyncio.run(regen_all(project_path, db))
        console.print(f"[green]✓[/green] Generated: {result['context_md']}")
        console.print(f"[green]✓[/green] ADRs: {result['adrs_generated']} files")
        if result['pointers_modified']:
            console.print(f"[green]✓[/green] Pointers added to: {', '.join(result['pointers_modified'])}")
        else:
            console.print("[dim]  No pointer files needed updating[/dim]")
    except Exception as e:
        console.print(f"[red]Error during regeneration:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@app.command()
def status(
    project: Optional[str] = typer.Option(
        None, "--project", "-p",
        help="Project path (defaults to current directory)"
    ),
):
    """Show status of Campy-managed context files."""
    project_path = Path(project) if project else Path.cwd()

    context_md = project_path / "CONTEXT.md"
    adr_dir = project_path / "docs" / "adr"

    console.print(f"[bold]Context files for:[/bold] {project_path}")
    console.print()

    if context_md.exists():
        stat = context_md.stat()
        from datetime import datetime
        mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        console.print(f"  CONTEXT.md: [green]exists[/green] (modified {mtime})")
    else:
        console.print("  CONTEXT.md: [yellow]not generated[/yellow]")

    if adr_dir.exists():
        adr_count = len(list(adr_dir.glob("*.md")))
        console.print(f"  docs/adr/:  [green]{adr_count} ADRs[/green]")
    else:
        console.print("  docs/adr/:  [yellow]not generated[/yellow]")

    for filename in ["CLAUDE.md", "AGENTS.md", "GEMINI.md"]:
        filepath = project_path / filename
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8")
            has_pointer = "memory_decision" in content
            status_str = "[green]has Campy pointer[/green]" if has_pointer else "[yellow]no Campy pointer[/yellow]"
            console.print(f"  {filename}:  {status_str}")
