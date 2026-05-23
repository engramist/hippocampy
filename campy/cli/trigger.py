"""Campy trigger management — add, list, remove, and compile associative triggers."""

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
    from mcp_engine.graph.kuzu_client import KuzuClient
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
    rows = await db.execute_read(
        "MATCH (p:Procedure) WHERE p.name = $name AND p.archived = false "
        "RETURN p.procedure_id AS id, p.name AS name",
        {"name": name},
    )
    if not rows:
        return {"error": f"No active Procedure found with name: {name!r}"}

    proc_id = rows[0]["id"]
    await db.execute_write(
        "MATCH (p:Procedure {procedure_id: $pid}) "
        "SET p.trigger_pattern = $pattern, "
        "    p.trigger_hook_type = $hook_type, "
        "    p.trigger_tool = $tool, "
        "    p.trigger_project_scope = $scope",
        {"pid": proc_id, "pattern": pattern, "hook_type": hook_type, "tool": tool, "scope": scope},
    )
    return {"name": rows[0]["name"]}


async def _bind_lesson_trigger(db, lesson_id: str, pattern: str, hook_type: str, tool: str, scope: str) -> dict:
    """Find a Lesson by ID and set its trigger columns."""
    rows = await db.execute_read(
        "MATCH (l:Lesson {lesson_id: $lid}) WHERE l.archived = false "
        "RETURN l.lesson_id AS id, l.text_raw AS text",
        {"lid": lesson_id},
    )
    if not rows:
        return {"error": f"No active Lesson found with ID: {lesson_id!r}"}

    await db.execute_write(
        "MATCH (l:Lesson {lesson_id: $lid}) "
        "SET l.trigger_pattern = $pattern, "
        "    l.trigger_hook_type = $hook_type, "
        "    l.trigger_tool = $tool, "
        "    l.trigger_project_scope = $scope",
        {"lid": lesson_id, "pattern": pattern, "hook_type": hook_type, "tool": tool, "scope": scope},
    )
    text = rows[0].get("text", "")
    name = text[:60] + "..." if len(text) > 60 else text
    return {"name": name}


@app.command("list")
def list_triggers():
    """Show all active triggers across Procedures and Lessons."""
    from mcp_engine.graph.kuzu_client import KuzuClient
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
    triggers = []

    proc_rows = await db.execute_read(
        "MATCH (p:Procedure) "
        "WHERE p.archived = false "
        "  AND p.trigger_pattern IS NOT NULL "
        "  AND p.trigger_pattern <> '' "
        "RETURN p.procedure_id AS id, p.name AS name, "
        "       p.trigger_pattern AS pattern, p.trigger_hook_type AS hook_type, "
        "       p.trigger_tool AS tool, p.trigger_project_scope AS scope, "
        "       p.pathway_strength AS strength "
        "ORDER BY p.pathway_strength DESC"
    )
    for row in proc_rows:
        triggers.append({
            "source_type": "Procedure",
            "name": row.get("name", ""),
            "pattern": row.get("pattern", ""),
            "hook_type": row.get("hook_type", ""),
            "tool": row.get("tool", ""),
            "scope": row.get("scope", ""),
            "strength": row.get("strength", 0),
        })

    lesson_rows = await db.execute_read(
        "MATCH (l:Lesson) "
        "WHERE l.archived = false "
        "  AND l.trigger_pattern IS NOT NULL "
        "  AND l.trigger_pattern <> '' "
        "RETURN l.lesson_id AS id, l.text_raw AS text, "
        "       l.trigger_pattern AS pattern, l.trigger_hook_type AS hook_type, "
        "       l.trigger_tool AS tool, l.trigger_project_scope AS scope, "
        "       l.pathway_strength AS strength "
        "ORDER BY l.pathway_strength DESC"
    )
    for row in lesson_rows:
        text = row.get("text", "")
        name = text[:40] + "..." if len(text) > 40 else text
        triggers.append({
            "source_type": "Lesson",
            "name": name,
            "pattern": row.get("pattern", ""),
            "hook_type": row.get("hook_type", ""),
            "tool": row.get("tool", ""),
            "scope": row.get("scope", ""),
            "strength": row.get("strength", 0),
        })

    return triggers


@app.command()
def remove(
    procedure: Optional[str] = typer.Option(None, "--procedure", help="Procedure name to unbind"),
    lesson: Optional[str] = typer.Option(None, "--lesson", help="Lesson ID to unbind"),
):
    """Remove trigger binding from a Procedure or Lesson."""
    from mcp_engine.graph.kuzu_client import KuzuClient
    from campy.paths import get_database_path

    if not procedure and not lesson:
        console.print("[red]Error:[/red] Specify --procedure or --lesson")
        raise typer.Exit(1)

    db_path = get_database_path()
    if not db_path.exists():
        console.print("[red]Error:[/red] Campy database not found.")
        raise typer.Exit(1)

    db = KuzuClient(str(db_path))

    try:
        if procedure:
            asyncio.run(db.execute_write(
                "MATCH (p:Procedure) WHERE p.name = $name "
                "SET p.trigger_pattern = '', "
                "    p.trigger_hook_type = '', "
                "    p.trigger_tool = '', "
                "    p.trigger_project_scope = ''",
                {"name": procedure},
            ))
            console.print(f"[green]✓[/green] Trigger removed from Procedure: {procedure}")
        else:
            asyncio.run(db.execute_write(
                "MATCH (l:Lesson {lesson_id: $lid}) "
                "SET l.trigger_pattern = '', "
                "    l.trigger_hook_type = '', "
                "    l.trigger_tool = '', "
                "    l.trigger_project_scope = ''",
                {"lid": lesson},
            ))
            console.print(f"[green]✓[/green] Trigger removed from Lesson: {lesson}")
    finally:
        db.close()


@app.command("compile")
def compile_cmd():
    """Force-compile the trigger manifest from graph state."""
    from mcp_engine.trigger_manifest import compile_manifest
    from mcp_engine.graph.kuzu_client import KuzuClient
    from mcp_engine.config import load_config
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
