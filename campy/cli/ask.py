"""
campy/cli/ask.py — CLI front door for `campy ask`.

Human-facing command: the user runs `campy ask "what did we decide about auth?"`
and gets a memory-grounded answer in plain text.

This is the non-coder "chat with your project's brain" entry point.
The implementation delegates entirely to run_ask() — no logic lives here.
"""

import asyncio
import typer
from typing import Optional
from rich.console import Console

app = typer.Typer(help="Ask Campy a question grounded in project memory.")
console = Console()


@app.callback(invoke_without_command=True)
def ask(
    query: str = typer.Argument(..., help="Question to answer from project memory."),
    session_id: Optional[str] = typer.Option(
        None, "--session", "-s", help="Session ID for memory capture. Defaults to 'cli'."
    ),
    token_budget: int = typer.Option(
        32000, "--budget", "-b", help="Token budget for memory bundle before compression."
    ),
    ctx: typer.Context = typer.Option(None, hidden=True),
):
    """Ask Campy a question and get a memory-grounded answer."""
    config = {}
    if ctx and ctx.obj:
        config = ctx.obj.get("config", {})

    sid = session_id or "cli"

    try:
        from campy.brain.hippocampus.graph.kuzu_client import KuzuClient
        from campy.brain.brainstem.config import load_config
        from campy.brain.thalamus.ask import run_ask

        if not config:
            config = load_config()

        db_path = config.get("database", {}).get("path", "~/.campy/brain.db")
        import os
        db_path = os.path.expanduser(db_path)
        db = KuzuClient(db_path, read_only=True)

        answer = asyncio.run(
            run_ask(query=query, session_id=sid, db=db, config=config, token_budget=token_budget)
        )
        console.print(answer)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)
