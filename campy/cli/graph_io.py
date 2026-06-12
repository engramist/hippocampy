"""CLI helpers for exporting and importing the Campy graph."""

from __future__ import annotations

from pathlib import Path

import httpx
import typer
from rich.console import Console

from campy.brain.hippocampus.graph.export import export_graph, import_graph
from campy.paths import get_database_path

console = Console()


def _daemon_is_running() -> bool:
    try:
        response = httpx.get("http://127.0.0.1:7799/api/v1/heartbeat", timeout=0.5)
        return bool(response.json().get("ok"))
    except Exception:
        return False


def export_graph_cmd(
    out: str = typer.Option(..., "--out", help="Directory to write the graph dump"),
    db_path: str = typer.Option(
        "",
        "--db-path",
        help="Path to the Kuzu database file (defaults to the active Campy database)",
    ),
) -> None:
    """Export the full graph to engine-neutral JSONL."""
    resolved_db_path = Path(db_path).expanduser() if db_path else get_database_path()
    if not resolved_db_path.exists():
        console.print("[red]Error:[/red] Campy database not found. Is the daemon running?")
        raise typer.Exit(code=1)

    if _daemon_is_running():
        console.print("[yellow]Warning:[/yellow] daemon is running; exporting in read-only mode.")

    result = export_graph(resolved_db_path, Path(out).expanduser())
    console.print(f"[green]✓[/green] Exported graph to {Path(out).expanduser()}")
    console.print(f"  Node tables: {len(result['node_tables'])}")
    console.print(f"  Rel tables: {len(result['rel_tables'])}")


def import_graph_cmd(
    dump_dir: str = typer.Option(..., "--in", help="Directory containing manifest.json and JSONL files"),
    db_path: str = typer.Option(..., "--db", help="Path to the new empty Kuzu database file"),
) -> None:
    """Restore a graph dump into an empty database."""
    resolved_dump_dir = Path(dump_dir).expanduser()
    resolved_db_path = Path(db_path).expanduser()

    if not (resolved_dump_dir / "manifest.json").exists():
        console.print("[red]Error:[/red] manifest.json not found in dump directory.")
        raise typer.Exit(code=1)

    if resolved_db_path.exists() and resolved_db_path.stat().st_size > 0:
        console.print("[red]Error:[/red] target database already exists and is not empty.")
        raise typer.Exit(code=1)

    result = import_graph(resolved_db_path, resolved_dump_dir)
    console.print(f"[green]✓[/green] Restored graph into {resolved_db_path}")
    console.print(f"  Node rows loaded: {result['node_rows_loaded']}")
    console.print(f"  Rel rows loaded: {result['rel_rows_loaded']}")
