"""CLI recall commands — query Campy memory from the terminal."""
import json
import sys
from datetime import datetime, timedelta
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

console = Console()

# Reuse the daemon communication pattern
DAEMON_URL = "http://127.0.0.1:7799"


def _send(method: str, params: dict = None) -> dict:
    """Send MCP JSON-RPC request to daemon."""
    import requests
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
    }
    if params:
        payload["params"] = params
    try:
        resp = requests.post(f"{DAEMON_URL}/mcp", json=payload, timeout=10)
        return resp.json()
    except requests.ConnectionError:
        return {"error": {"message": "Daemon not running. Start with: campy start"}}
    except Exception as e:
        return {"error": {"message": str(e)}}


def _call_tool(tool_name: str, arguments: dict) -> dict:
    """Call an MCP tool via the daemon."""
    return _send("tools/call", {"name": tool_name, "arguments": arguments})


def _format_result(result: dict, format_type: str) -> str:
    """Format tool result based on output format."""
    if format_type == "json":
        return json.dumps(result, indent=2)
    elif format_type == "prompt":
        # Bare text for hook injection
        content = result.get("result", result)
        if isinstance(content, dict):
            # Extract text content from various response shapes
            for key in ("text", "content", "summary", "markdown"):
                if key in content:
                    return str(content[key])
            return json.dumps(content)
        return str(content)
    else:
        return None  # Use Rich formatting


def _handle_error(result: dict) -> bool:
    """Print error and return True if result is an error."""
    if "error" in result:
        console.print(f"[red]Error: {result['error'].get('message', result['error'])}[/red]")
        return True
    return False


app = typer.Typer(help="Query Campy memory from the command line")


@app.command()
def recall(
    query: str = typer.Argument(..., help="What to search for in memory"),
    scope: str = typer.Option("both", help="Search scope: branch, global, or both"),
    format: str = typer.Option("rich", "--format", help="Output format: rich, json, prompt"),
    session_id: Optional[str] = typer.Option(None, help="Session ID"),
):
    """Quick semantic recall using current_truth."""
    args = {"query": query, "scope": scope}
    if session_id:
        args["session_id"] = session_id

    result = _call_tool("current_truth", args)
    if _handle_error(result):
        raise typer.Exit(code=1)

    formatted = _format_result(result, format)
    if formatted:
        console.print(formatted)
    else:
        # Rich format
        data = result.get("result", {})
        results_list = data.get("results", [])
        if not results_list:
            console.print("[dim]No results found.[/dim]")
            return

        table = Table(title=f"Recall: {query}")
        table.add_column("Type", style="cyan", width=12)
        table.add_column("Content", style="white")
        table.add_column("Confidence", style="magenta", width=12)

        for item in results_list:
            table.add_row(
                item.get("type", "unknown"),
                item.get("text_raw", item.get("summary", ""))[:120],
                f"{item.get('confidence', 'N/A')}",
            )
        console.print(table)


@app.command()
def bundle(
    query: str = typer.Argument(..., help="What context to compile"),
    token_budget: int = typer.Option(32000, help="Token budget for the bundle"),
    agent_type: str = typer.Option("generic", help="Agent type for formatting"),
    format: str = typer.Option("rich", "--format", help="Output format: rich, json, prompt"),
):
    """Compile a full context bundle from all memory types."""
    result = _call_tool("compile_context", {
        "query": query,
        "token_budget": token_budget,
        "agent_type": agent_type,
    })
    if _handle_error(result):
        raise typer.Exit(code=1)

    formatted = _format_result(result, format)
    if formatted:
        console.print(formatted)
    else:
        data = result.get("result", {})
        console.print(Markdown(f"## Bundle: {query}\n"))
        sections = data.get("sections", [])
        for section in sections:
            console.print(f"\n[bold cyan]{section.get('type', 'unknown')}[/bold cyan]")
            for item in section.get("content", []):
                console.print(f"  • {str(item)[:100]}")
        console.print(f"\n[dim]Tokens: {data.get('total_token_estimate', '?')} / {data.get('token_budget', '?')}[/dim]")


@app.command()
def timeline(
    since: Optional[str] = typer.Option(None, "--since", help="ISO timestamp to start from"),
    limit: int = typer.Option(20, help="Max events to return"),
    quest_id: Optional[str] = typer.Option(None, help="Filter by quest"),
    format: str = typer.Option("rich", "--format", help="Output format"),
):
    """View temporal timeline of memory events."""
    args = {"limit": limit}
    if since:
        args["since_iso"] = since
    if quest_id:
        args["quest_id"] = quest_id

    result = _call_tool("reconstruct_timeline", args)
    if _handle_error(result):
        raise typer.Exit(code=1)

    formatted = _format_result(result, format)
    if formatted:
        console.print(formatted)
    else:
        events = result.get("result", {}).get("events", [])
        table = Table(title="Timeline")
        table.add_column("Time", style="cyan", width=20)
        table.add_column("Type", style="magenta", width=12)
        table.add_column("Summary", style="white")
        for event in events:
            table.add_row(
                event.get("timestamp", "?"),
                event.get("type", "?"),
                str(event.get("summary", ""))[:80],
            )
        console.print(table)


@app.command()
def diff(
    since: Optional[str] = typer.Option(None, "--since", help="ISO timestamp (default: 24h ago)"),
    format: str = typer.Option("rich", "--format", help="Output format"),
):
    """Show what changed in memory since a timestamp."""
    if since is None:
        since = (datetime.utcnow() - timedelta(hours=24)).isoformat() + "Z"

    result = _call_tool("diff_since", {"since_iso": since})
    if _handle_error(result):
        raise typer.Exit(code=1)

    formatted = _format_result(result, format)
    if formatted:
        console.print(formatted)
    else:
        data = result.get("result", {})
        console.print(f"[bold]Changes since {since}[/bold]\n")
        for category in ["created", "updated", "deprecated"]:
            items = data.get(category, [])
            if items:
                console.print(f"[cyan]{category.title()} ({len(items)}):[/cyan]")
                for item in items:
                    console.print(f"  • {item.get('label', item.get('text_raw', str(item)))[:100]}")


@app.command()
def decide(
    query: str = typer.Argument(..., help="Question to route"),
    format: str = typer.Option("rich", "--format", help="Output format"),
    session_id: Optional[str] = typer.Option(None, help="Session ID"),
):
    """Ask the memory router which tool to use."""
    args = {"query": query}
    if session_id:
        args["session_id"] = session_id

    result = _call_tool("memory_decision", args)
    if _handle_error(result):
        raise typer.Exit(code=1)

    formatted = _format_result(result, format)
    if formatted:
        console.print(formatted)
    else:
        data = result.get("result", {})
        console.print(f"[bold cyan]Recommended tool:[/bold cyan] {data.get('recommended_tool', '?')}")
        console.print(f"[dim]Reasoning: {data.get('reasoning', 'N/A')}[/dim]")
        console.print(f"[dim]Confidence: {data.get('confidence', 'N/A')}[/dim]")


@app.command()
def context(
    format: str = typer.Option("rich", "--format", help="Output format"),
    session_id: Optional[str] = typer.Option(None, help="Session ID"),
):
    """Check current context health and status."""
    args = {}
    if session_id:
        args["session_id"] = session_id

    result = _call_tool("context_status", args)
    if _handle_error(result):
        raise typer.Exit(code=1)

    formatted = _format_result(result, format)
    if formatted:
        console.print(formatted)
    else:
        data = result.get("result", {})
        console.print("[bold]Context Status[/bold]")
        for key, value in data.items():
            console.print(f"  [cyan]{key}:[/cyan] {value}")
