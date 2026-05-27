import typer
import os
import asyncio
import logging
import platform
import subprocess
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.logging import RichHandler
from pathlib import Path

from campy.cli.detect import detect_all, detect_claude_desktop
from campy.cli.register import (
    register_claude_code,
    register_claude_desktop,
    register_chatgpt_desktop,
    register_codex,
    register_gemini_cli,
    register_vscode,
    register_hermes,
)
from campy.cli.register_openclaw import register_openclaw
from campy.cli.launchd import setup_daemon
from campy.cli.smoke_test import run_smoke_tests, check_status
from campy.cli.wiki import app as wiki_app
from campy.cli.arc import app as arc_app
from campy.cli.recall import app as recall_app
from campy.cli.context import app as context_app
from campy.cli.trigger import app as trigger_app
from campy.branding import PRODUCT_NAME, SHORT_NAME
from mcp_engine.config import load_config

app = typer.Typer(help=f"{PRODUCT_NAME} AI Memory System CLI")
# Backward-compatible entrypoint for installed console scripts that import `cli`.
cli = app
console = Console()

@app.callback()
def main_callback(ctx: typer.Context):
    """
    Initialize CLI context and load configuration.
    """
    try:
        ctx.obj = {"config": load_config()}
    except Exception:
        ctx.obj = {"config": {}}

# Set up logging
FORMAT = "%(message)s"
logging.basicConfig(
    level="INFO", format=FORMAT, datefmt="[%X]", handlers=[RichHandler(rich_tracebacks=True)]
)

@app.command()
def setup(
    target: Optional[str] = typer.Option(None, help="Specific client to register (claude-code, claude-desktop, etc.)")
):
    """
    Automated setup to detect and register Campy with AI clients.
    """
    console.print(f"[bold blue]{PRODUCT_NAME} Setup[/bold blue]")

    # Check OS
    system = platform.system()
    if system not in ["Darwin"]:
        console.print(f"[yellow]Note: Full automated setup is currently optimized for macOS. {system} registration may require manual steps.[/yellow]")

    # Get absolute paths
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    claude_code_adapter = os.path.join(repo_root, "adapters/claude_code/adapter.py")
    claude_desktop_adapter = os.path.join(repo_root, "adapters/claude_desktop/adapter.py")
    codex_adapter = os.path.join(repo_root, "adapters/codex/adapter.py")
    gemini_adapter = os.path.join(repo_root, "adapters/gemini_cli/adapter.py")
    brain_daemon_path = os.path.join(repo_root, "brain_daemon.py")

    # Client detection
    clients = detect_all()

    results = {}

    if target:
        # Register specific target
        if target == "claude-code":
            results["Claude Code"] = register_claude_code(claude_code_adapter)
        elif target == "claude-desktop":
            config_path = detect_claude_desktop()
            results["Claude Desktop"] = register_claude_desktop(claude_desktop_adapter, config_path)
        elif target == "chatgpt-desktop":
            results["ChatGPT Desktop"] = register_chatgpt_desktop()
        elif target == "codex":
            results["Codex"] = register_codex(codex_adapter)
        elif target == "gemini-cli":
            results["Gemini CLI"] = register_gemini_cli(gemini_adapter)
        elif target == "vscode":
            results["VS Code"] = register_vscode(codex_adapter)
        elif target == "openclaw":
            results["OpenClaw"] = register_openclaw()
        elif target == "hermes":
            results["Hermes"] = register_hermes()
        else:
            console.print(f"[red]Error: Unknown target '{target}'[/red]")
            raise typer.Exit(code=1)
    else:
        # Auto-detect and register
        if clients.get("claude_code"):
            console.print("[green]Detected Claude Code. Registering...[/green]")
            results["Claude Code"] = register_claude_code(claude_code_adapter)

        if clients.get("claude_desktop"):
            console.print("[green]Detected Claude Desktop. Registering...[/green]")
            config_path = detect_claude_desktop()
            results["Claude Desktop"] = register_claude_desktop(claude_desktop_adapter, config_path)

        if clients.get("chatgpt_desktop"):
            console.print("[green]Detected ChatGPT Desktop. Instructions provided.[/green]")
            results["ChatGPT Desktop"] = register_chatgpt_desktop()

        if clients.get("codex"):
            console.print("[green]Detected Codex. Registering...[/green]")
            results["Codex"] = register_codex(codex_adapter)

        if clients.get("gemini_cli"):
            console.print("[green]Detected Gemini CLI. Registering...[/green]")
            results["Gemini CLI"] = register_gemini_cli(gemini_adapter)

        if clients.get("vscode"):
            console.print("[green]Detected VS Code. Registering MCP server...[/green]")
            results["VS Code"] = register_vscode(codex_adapter)

        if clients.get("openclaw"):
            console.print("[green]Detected OpenClaw. Registering...[/green]")
            results["OpenClaw"] = register_openclaw()

        if clients.get("hermes"):
            console.print("[green]Detected Hermes. Registering...[/green]")
            results["Hermes"] = register_hermes()

    # Daemon setup (macOS only)
    if system == "Darwin":
        console.print("[blue]Setting up Brain Daemon auto-start...[/blue]")
        results["Daemon (launchd)"] = setup_daemon(brain_daemon_path)

    # Smoke tests
    console.print("\n[bold]Running Smoke Tests...[/bold]")
    # We use a short sleep to give launchd time to start the process
    if system == "Darwin":
        import time
        time.sleep(1)

    smoke_results = asyncio.run(run_smoke_tests())

    # Summary Table
    table = Table(title="Setup Summary")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="magenta")

    for component, success in results.items():
        status = "[green]Pass[/green]" if success else "[red]Fail[/red]"
        table.add_row(component, status)

    for component, success in smoke_results.items():
        status = "[green]Pass[/green]" if success else "[red]Fail[/red]"
        table.add_row(component, status)

    console.print(table)

    # Overall success depends on all explicit results and all smoke tests
    if all(results.values()) and all(smoke_results.values()):
        console.print(f"\n[bold green]Setup complete! {SHORT_NAME} is ready to use.[/bold green]")
    else:
        console.print("\n[bold yellow]Setup finished with some warnings or errors. Check logs for details.[/bold yellow]")

@app.command()
def install(
    plugin: bool = typer.Option(False, "--plugin", help="Also install plugin for detected agents"),
    plugin_dir: Optional[str] = typer.Option(None, help="Path to plugin directory (auto-detected if omitted)"),
):
    """
    One-command installer for HippoCampy.
    """
    from campy.cli.install import run_install
    from campy.cli.plugin_installer import install_plugin_for_agents
    
    run_install()
    
    if plugin:
        install_plugin_for_agents(target=None, plugin_dir=plugin_dir)

@app.command()
def uninstall(
    keep_data: bool = typer.Option(True, "--keep-data/--delete-data", help="Whether to keep the memory data"),
    remove_ollama_model: bool = typer.Option(False, help="Whether to remove the Ollama model"),
    ollama_model: str = typer.Option("qwen2.5:3b", help="Ollama model to remove"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt")
):
    """
    Uninstall Campy and remove adapter registrations.
    """
    if not yes:
        confirm = typer.confirm("Are you sure you want to uninstall Campy?")
        if not confirm:
            raise typer.Abort()

    from campy.cli.uninstall import run_uninstall
    run_uninstall(keep_data=keep_data, remove_ollama_model=remove_ollama_model, ollama_model=ollama_model)

@app.command()
def start():
    """
    Start the HippoCampy memory daemon.
    """
    system = platform.system()
    if system == "Darwin":
        from campy.cli.launchd import load_plist
        if load_plist():
            console.print("[green]Brain Daemon started via launchd.[/green]")
        else:
            console.print("[red]Failed to start Brain Daemon via launchd.[/red]")
    else:
        # Fallback for other systems
        repo_root = Path(__file__).parent.parent.parent
        brain_daemon_path = repo_root / "brain_daemon.py"
        import sys
        subprocess.Popen([sys.executable, str(brain_daemon_path)], start_new_session=True)
        console.print("[green]Brain Daemon started.[/green]")

@app.command()
def stop():
    """
    Stop the HippoCampy memory daemon.
    """
    system = platform.system()
    if system == "Darwin":
        from campy.cli.launchd import unload_plist
        if unload_plist():
            console.print("[green]Brain Daemon stopped via launchd.[/green]")
        else:
            console.print("[red]Failed to stop Brain Daemon via launchd.[/red]")
    else:
        # Fallback for other systems
        subprocess.run(["pkill", "-f", "brain_daemon.py"])
        console.print("[green]Brain Daemon stopped.[/green]")

@app.command()
def status(
    watch: bool = typer.Option(False, "--watch", "-w", help="Live-updating phase display"),
):
    """
    Check the health and status of the HippoCampy memory daemon.

    With --watch, shows a live-updating phase indicator via SSE.
    """
    import httpx
    import sys

    HEARTBEAT_URL = "http://127.0.0.1:7799/api/v1/heartbeat"
    STREAM_URL = "http://127.0.0.1:7799/api/v1/activity/stream"

    PHASE_COLORS = {
        "idle": "green",
        "encoding": "yellow",
        "recalling": "blue",
        "sweeping": "magenta",
    }

    def _format_phase(data: dict) -> str:
        phase = data.get("phase", "unknown")
        uptime = data.get("uptime_s", 0)
        color = PHASE_COLORS.get(phase, "white")
        return f"[{color}]🧠 {phase}[/{color}] · {uptime:.0f}s"

    if not watch:
        # One-shot mode: hit heartbeat endpoint, fall back to legacy check
        try:
            r = httpx.get(HEARTBEAT_URL, timeout=2.0)
            body = r.json()
            if body.get("ok"):
                console.print(_format_phase(body["data"]))
                return
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        except Exception:
            pass

        # Fall back to legacy status check
        console.print(f"[bold blue]{PRODUCT_NAME} Status[/bold blue]")
        if not check_status():
            console.print("[red]🧠 offline[/red]")
            raise typer.Exit(code=1)
        return

    # Watch mode: subscribe to SSE stream
    console.print("[dim]Watching Campy phase changes (Ctrl+C to stop)...[/dim]")
    try:
        with httpx.stream("GET", STREAM_URL, timeout=None) as response:
            event_type = ""
            for line in response.iter_lines():
                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:") and event_type in ("phase", "heartbeat"):
                    import json as json_mod
                    data = json_mod.loads(line[5:].strip())
                    sys.stdout.write(f"\r{' ' * 60}\r")
                    console.print(_format_phase(data), end="")
                    sys.stdout.flush()
    except KeyboardInterrupt:
        console.print()
    except (httpx.ConnectError, httpx.TimeoutException):
        console.print("[red]🧠 offline[/red]")
        raise typer.Exit(code=1)

@app.command()
def doctor(
    repair: bool = typer.Option(False, "--repair", help="Attempt safe repairs"),
    lines: Optional[int] = typer.Option(None, "--lines", help="Show last N activity lines"),
    json_output: bool = typer.Option(False, "--json", help="Output results as JSON"),
):
    """
    Diagnose Campy daemon, config, runtime paths, and MCP registrations.
    """
    from campy.cli.doctor import run_doctor

    if not run_doctor(repair=repair, lines=lines, json_output=json_output):
        raise typer.Exit(code=1)

@app.command()
def activity(
    ctx: typer.Context,
    lines: int = typer.Option(40, "--lines", "-n", help="Number of recent activity lines to show first"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Keep streaming new activity"),
    json_output: bool = typer.Option(False, "--json", help="Print raw JSONL records"),
):
    """
    Watch Campy memory activity without tailing the noisy daemon log.
    """
    from mcp_engine.activity_log import (
        activity_log_path,
        follow_records,
        format_activity,
        read_recent,
    )

    config = (ctx.obj or {}).get("config", {})
    path = activity_log_path(config)
    if not path.exists():
        console.print(f"[yellow]No activity log yet at {path}.[/yellow]")
        console.print("Start the daemon, then run this again with --follow.")
        if not follow:
            return

    for record in read_recent(path, lines):
        console.print_json(data=record) if json_output else console.print(format_activity(record))

    if follow:
        console.print(f"[dim]Following {path} - press Ctrl-C to stop.[/dim]")
        try:
            for record in follow_records(path):
                console.print_json(data=record) if json_output else console.print(format_activity(record))
        except KeyboardInterrupt:
            return

@app.command()
def smoke(
    arc_world_model_tools: bool = typer.Option(False, "--arc-world-model-tools", help="Check for ARC world-model tools")
):
    """
    Run diagnostic smoke tests.
    """
    console.print(f"[bold blue]{PRODUCT_NAME} Smoke Test[/bold blue]")

    results = asyncio.run(run_smoke_tests())

    if arc_world_model_tools:
        from campy.cli.smoke_test import check_arc_tools
        arc_res = check_arc_tools()
        results["ARC World-Model Tools"] = arc_res["ok"]
        if not arc_res["ok"]:
            console.print(f"[yellow]Note: {arc_res['detail']}[/yellow]")

    table = Table(title="Smoke Test Results")
    table.add_column("Check", style="cyan")
    table.add_column("Status", style="magenta")

    for check, success in results.items():
        status = "[green]Pass[/green]" if success else "[red]Fail[/red]"
        table.add_row(check, status)

    console.print(table)

    if all(results.values()):
        console.print("\n[bold green]All checks passed![/bold green] 🚀")
    else:
        console.print("\n[bold red]Some checks failed. Check daemon logs for details.[/bold red]")
        raise typer.Exit(code=1)

@app.command()
def review():
    """
    Review open loops and pending tasks in the Brain.
    """
    from campy.cli.smoke_test import _send
    res = _send("tools/call", {"name": "get_open_loops", "arguments": {}})
    if "error" in res:
        console.print(f"[red]Error: {res['error']['message']}[/red]")
        raise typer.Exit(code=1)

    loops = res.get("result", {}).get("open_loops", [])
    if not loops:
        console.print("No open loops found.")
        return

    table = Table(title="Open Loops")
    table.add_column("Type", style="cyan")
    table.add_column("Detail", style="magenta")

    for loop in loops:
        text = loop.get("text_raw", "")
        table.add_row("Loop", text[:100] + "..." if len(text) > 100 else text)

    console.print(table)

tool_app = typer.Typer(help="Manage MCP tools")
app.add_typer(tool_app, name="tool")

app.add_typer(wiki_app, name="wiki")
app.add_typer(arc_app, name="arc")
app.add_typer(recall_app, name="memory")
app.add_typer(context_app, name="context")
app.add_typer(trigger_app, name="trigger")

@tool_app.command("list")
def tool_list():
    """List available MCP tools."""
    from campy.cli.smoke_test import _send
    res = _send("tools/list")
    if "error" in res:
        console.print(f"[red]Error: {res['error']['message']}[/red]")
        raise typer.Exit(code=1)

    tools = res.get("result", {}).get("tools", [])
    table = Table(title="Available Tools")
    table.add_column("Name", style="cyan")
    table.add_column("Description", style="magenta")

    for tool in tools:
        table.add_row(tool["name"], tool.get("description", ""))

    console.print(table)


# Shortcut commands for recall (also available via "campy memory recall", etc.)
@app.command()
def recall(
    query: str = typer.Argument(..., help="What to search for"),
    scope: str = typer.Option("both", "--scope", help="Search scope"),
    format: str = typer.Option("rich", "--format", help="Output format"),
    session_id: Optional[str] = typer.Option(None, help="Session ID"),
):
    """Quick recall from memory."""
    from campy.cli.recall import recall as _recall
    _recall(query=query, scope=scope, format=format, session_id=session_id)


@app.command()
def bundle(
    query: str = typer.Argument(..., help="Context to compile"),
    token_budget: int = typer.Option(32000, "--token-budget", help="Token budget"),
    agent_type: str = typer.Option("generic", "--agent-type", help="Agent type"),
    format: str = typer.Option("rich", "--format", help="Output format"),
):
    """Compile full context bundle."""
    from campy.cli.recall import bundle as _bundle
    _bundle(query=query, token_budget=token_budget, agent_type=agent_type, format=format)


@app.command()
def timeline(
    since: Optional[str] = typer.Option(None, "--since", help="ISO timestamp"),
    limit: int = typer.Option(20, "--limit", help="Max events"),
    quest_id: Optional[str] = typer.Option(None, "--quest-id", help="Filter by quest"),
    format: str = typer.Option("rich", "--format", help="Output format"),
):
    """View memory timeline."""
    from campy.cli.recall import timeline as _timeline
    _timeline(since=since, limit=limit, quest_id=quest_id, format=format)


@app.command(name="diff")
def diff_cmd(
    since: Optional[str] = typer.Option(None, "--since", help="ISO timestamp"),
    format: str = typer.Option("rich", "--format", help="Output format"),
):
    """Show memory changes since timestamp."""
    from campy.cli.recall import diff as _diff
    _diff(since=since, format=format)


@app.command()
def decide(
    query: str = typer.Argument(..., help="Question to route"),
    format: str = typer.Option("rich", "--format", help="Output format"),
    session_id: Optional[str] = typer.Option(None, help="Session ID"),
):
    """Ask memory router which tool to use."""
    from campy.cli.recall import decide as _decide
    _decide(query=query, format=format, session_id=session_id)


@app.command(name="context-health")
def context_cmd(
    format: str = typer.Option("rich", "--format", help="Output format"),
    session_id: Optional[str] = typer.Option(None, help="Session ID"),
):
    """Check context health."""
    from campy.cli.recall import context as _context
    _context(format=format, session_id=session_id)


if __name__ == "__main__":
    app()
