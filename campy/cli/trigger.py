"""Campy trigger management — add, list, remove, and compile associative triggers."""

from __future__ import annotations

from campy.brain.hippocampus.graph.gateway import get_gateway

import typer
import asyncio
from typing import Optional
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Manage Campy associative triggers")
console = Console()


@app.command()
def add(
    pattern: str = typer.Option(..., "--pattern", "-p", help="Regex to match tool input/output"),
    hook_type: str = typer.Option("PreToolUse", "--hook", "-h", help="PreToolUse or PostToolUse"),
    tool: str = typer.Option("", "--tool", "-t", help="Tool to match (Bash, Edit, Write, or empty for all)"),
    scope: str = typer.Option("", "--scope", "-s", help="Project path scope (empty for all)"),
    procedure: Optional[str] = typer.Option(None, "--procedure", help="Procedure name to bind trigger to"),
    lesson: Optional[str] = typer.Option(None, "--lesson", help="Lesson ID to bind trigger to"),
):
    """Bind a trigger pattern to a Procedure or Lesson node."""
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
    from campy.paths import get_database_path

    if not procedure and not lesson:
        console.print("[red]Error:[/red] Specify --procedure or --lesson")
        raise typer.Exit(1)

    if procedure and lesson:
        console.print("[red]Error:[/red] Specify only one of --procedure or --lesson")
        raise typer.Exit(1)

    if hook_type not in ("PreToolUse", "PostToolUse"):
        console.print(f"[red]Error:[/red] --hook must be PreToolUse or PostToolUse, got {hook_type!r}")
        raise typer.Exit(1)

    db_path = get_database_path()
    if not db_path.exists():
        console.print("[red]Error:[/red] Campy database not found. Is the daemon running?")
        raise typer.Exit(1)

    db = KuzuClient(str(db_path))

    try:
        if procedure:
            result = asyncio.run(_bind_procedure_trigger(db, procedure, pattern, hook_type, tool, scope))
        else:
            result = asyncio.run(_bind_lesson_trigger(db, lesson, pattern, hook_type, tool, scope))

        if result.get("error"):
            console.print(f"[red]Error:[/red] {result['error']}")
            raise typer.Exit(1)

        node_type = "Procedure" if procedure else "Lesson"
        node_name = result.get("name", procedure or lesson)
        console.print(f"[green]✓[/green] Trigger bound to {node_type}: {node_name}")
        console.print(f"  Pattern: [cyan]{pattern}[/cyan]")
        console.print(f"  Hook: {hook_type} | Tool: {tool or '(all)'} | Scope: {scope or '(all)'}")
    finally:
        db.close()


async def _bind_procedure_trigger(db, name: str, pattern: str, hook_type: str, tool: str, scope: str) -> dict:
    """Find a Procedure by name and set its trigger columns."""
    gw = get_gateway(db)
    rows = await gw.run("cli.trigger_find_procedure", name=name)
    if not rows:
        return {"error": f"No active Procedure found with name: {name!r}"}

    first = rows[0]
    proc_id = first["id"] if isinstance(first, dict) else first[0]
    proc_name = first["name"] if isinstance(first, dict) else first[1]
    await gw.run(
        "cli.trigger_update_procedure",
        pid=proc_id, pattern=pattern, hook_type=hook_type, tool=tool, scope=scope,
    )
    return {"name": proc_name}


async def _bind_lesson_trigger(db, lesson_id: str, pattern: str, hook_type: str, tool: str, scope: str) -> dict:
    """Find a Lesson by ID and set its trigger columns."""
    gw = get_gateway(db)
    rows = await gw.run("cli.trigger_find_lesson", lid=lesson_id)
    if not rows:
        return {"error": f"No active Lesson found with ID: {lesson_id!r}"}

    await gw.run(
        "cli.trigger_update_lesson",
        lid=lesson_id, pattern=pattern, hook_type=hook_type, tool=tool, scope=scope,
    )
    first = rows[0]
    text = first.get("text", "") if isinstance(first, dict) else (first[1] or "")
    name = text[:60] + "..." if len(text) > 60 else text
    return {"name": name}


@app.command("list")
def list_triggers():
    """Show all active triggers across Procedures and Lessons."""
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
    from campy.paths import get_database_path

    db_path = get_database_path()
    if not db_path.exists():
        console.print("[red]Error:[/red] Campy database not found. Is the daemon running?")
        raise typer.Exit(1)

    db = KuzuClient(str(db_path), read_only=True)

    try:
        results = asyncio.run(_fetch_all_triggers(db))
    finally:
        db.close()

    if not results:
        console.print("[dim]No triggers configured.[/dim]")
        return

    table = Table(title="Campy Triggers")
    table.add_column("Type", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Pattern", style="green")
    table.add_column("Hook", style="yellow")
    table.add_column("Tool")
    table.add_column("Scope")
    table.add_column("Strength", justify="right")

    for r in results:
        table.add_row(
            r["source_type"],
            r["name"][:40],
            r["pattern"],
            r["hook_type"],
            r["tool"] or "(all)",
            r["scope"] or "(all)",
            f"{r['strength']:.2f}",
        )

    console.print(table)


async def _fetch_all_triggers(db) -> list[dict]:
    """Query all Procedure and Lesson nodes with trigger patterns."""
    gw = get_gateway(db)
    triggers = []

    proc_rows = await gw.run("cli.trigger_list_procedures")
    for row in proc_rows:
        triggers.append({
            "source_type": "Procedure",
            "name": row.get("name", "") if isinstance(row, dict) else row[1],
            "pattern": row.get("pattern", "") if isinstance(row, dict) else row[2],
            "hook_type": row.get("hook_type", "") if isinstance(row, dict) else row[3],
            "tool": row.get("tool", "") if isinstance(row, dict) else row[4],
            "scope": row.get("scope", "") if isinstance(row, dict) else row[5],
            "strength": row.get("strength", 0) if isinstance(row, dict) else row[6],
        })

    lesson_rows = await gw.run("cli.trigger_list_lessons")
    for row in lesson_rows:
        text = row.get("text", "") if isinstance(row, dict) else (row[1] or "")
        name = text[:40] + "..." if len(text) > 40 else text
        triggers.append({
            "source_type": "Lesson",
            "name": name,
            "pattern": row.get("pattern", "") if isinstance(row, dict) else row[2],
            "hook_type": row.get("hook_type", "") if isinstance(row, dict) else row[3],
            "tool": row.get("tool", "") if isinstance(row, dict) else row[4],
            "scope": row.get("scope", "") if isinstance(row, dict) else row[5],
            "strength": row.get("strength", 0) if isinstance(row, dict) else row[6],
        })

    return triggers


@app.command()
def remove(
    procedure: Optional[str] = typer.Option(None, "--procedure", help="Procedure name to unbind"),
    lesson: Optional[str] = typer.Option(None, "--lesson", help="Lesson ID to unbind"),
):
    """Remove trigger binding from a Procedure or Lesson."""
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
    from campy.paths import get_database_path

    if not procedure and not lesson:
        console.print("[red]Error:[/red] Specify --procedure or --lesson")
        raise typer.Exit(1)

    db_path = get_database_path()
    if not db_path.exists():
        console.print("[red]Error:[/red] Campy database not found.")
        raise typer.Exit(1)

    db = KuzuClient(str(db_path))

    gw = get_gateway(db)
    try:
        if procedure:
            asyncio.run(gw.run(
                "cli.trigger_remove_procedure",
                name=procedure,
            ))
            console.print(f"[green]✓[/green] Trigger removed from Procedure: {procedure}")
        else:
            asyncio.run(gw.run(
                "cli.trigger_remove_lesson",
                lid=lesson,
            ))
            console.print(f"[green]✓[/green] Trigger removed from Lesson: {lesson}")
    finally:
        db.close()


@app.command("compile")
def compile_cmd():
    """Force-compile the trigger manifest from graph state."""
    from campy.brain.thalamus.trigger_manifest import compile_manifest
    from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
    from campy.brain.brainstem.config import load_config
    from campy.paths import get_database_path

    db_path = get_database_path()
    if not db_path.exists():
        console.print("[red]Error:[/red] Campy database not found.")
        raise typer.Exit(1)

    db = KuzuClient(str(db_path), read_only=True)
    config = load_config()

    try:
        result = asyncio.run(compile_manifest(db, config))
        console.print(
            f"[green]✓[/green] Compiled {result['triggers_compiled']} triggers "
            f"({result['procedures']} procedures, {result['lessons']} lessons)"
        )
        console.print(f"  Manifest: {result['manifest_path']}")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    finally:
        db.close()
