import typer
from typing import Optional
from pathlib import Path
from campy.cli.smoke_test import _send

app = typer.Typer(help="Manage ARC artifact ingestion and helpers")

@app.command("ingest-artifacts")
def ingest_artifacts(
    artifact_root: Optional[str] = typer.Option(None, "--artifact-root", "-r", help="Path to ARC_AGI root"),
    no_live_jsonl: bool = typer.Option(False, "--no-live-jsonl", help="Do not ingest .live.jsonl files"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Perform a dry run without writing to DB"),
    max_events: int = typer.Option(5000, "--max-events", help="Maximum number of events to ingest"),
):
    """Ingest ARC_AGI artifacts into SideQuests graph memory via the Brain Daemon."""
    params: dict = {}
    if artifact_root:
        params["artifact_root"] = str(Path(artifact_root).expanduser().resolve())
    params["include_live_jsonl"] = not bool(no_live_jsonl)
    params["dry_run"] = bool(dry_run)
    params["max_events"] = int(max_events)

    # ARC artifact ingestion can process large JSON/JSONL payloads.
    res = _send("ingest_arc_artifacts", params, timeout_seconds=600.0)
    if "error" in res:
        typer.secho(f"Error: {res['error'].get('message', res['error'])}", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    # Response is expected to be JSON-RPC style: {"result": {...}}
    summary = res.get("result") if isinstance(res, dict) and "result" in res else res
    if not summary:
        typer.secho("No result returned from daemon.", fg=typer.colors.RED)
        raise typer.Exit(code=1)

    typer.secho("ARC artifact ingestion complete", fg=typer.colors.GREEN)
    typer.echo(f"Artifacts scanned: {summary.get('artifacts_scanned', 0)}")
    typer.echo(f"Artifacts ingested: {summary.get('artifacts_ingested', 0)}")
    typer.echo(f"Runs upserted: {summary.get('runs_upserted', 0)}")
    typer.echo(f"Task results upserted: {summary.get('task_results_upserted', 0)}")
    typer.echo(f"Events upserted: {summary.get('events_upserted', 0)}")
    typer.echo(f"Malformed records skipped: {summary.get('malformed_records_skipped', 0)}")
    typer.echo(f"Missing files: {summary.get('missing_files', [])}")
    typer.echo(f"Dry run: {summary.get('dry_run', False)}")
