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

from sidequests.cli.detect import detect_all, detect_claude_desktop
from sidequests.cli.register import (
    register_claude_code,
    register_claude_desktop,
    register_chatgpt_desktop,
    register_codex,
    register_gemini_cli,
    register_vscode,
)
from sidequests.cli.launchd import setup_daemon
from sidequests.cli.smoke_test import run_smoke_tests, check_status
from sidequests.cli.wiki import app as wiki_app
from sidequests.cli.arc import app as arc_app
from mcp_engine.config import load_config

app = typer.Typer(help="SideQuests AI Memory System CLI")
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
    Automated setup to detect and register SideQuests with AI clients.
    """
    console.print("[bold blue]SideQuests Setup[/bold blue] 🧠")

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
        console.print("\n[bold green]Setup complete! SideQuests is ready to use.[/bold green] 🚀")
    else:
        console.print("\n[bold yellow]Setup finished with some warnings or errors. Check logs for details.[/bold yellow]")

@app.command()
def install():
    """
    One-command installer for SideQuests Brain.
    """
    from sidequests.cli.install import run_install
    run_install()

@app.command()
def uninstall(
    keep_data: bool = typer.Option(True, "--keep-data/--delete-data", help="Whether to keep the memory data"),
    remove_ollama_model: bool = typer.Option(False, help="Whether to remove the Ollama model"),
    ollama_model: str = typer.Option("qwen2.5:3b", help="Ollama model to remove"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt")
):
    """
    Uninstall SideQuests and remove adapter registrations.
    """
    if not yes:
        confirm = typer.confirm("Are you sure you want to uninstall SideQuests?")
        if not confirm:
            raise typer.Abort()

    from sidequests.cli.uninstall import run_uninstall
    run_uninstall(keep_data=keep_data, remove_ollama_model=remove_ollama_model, ollama_model=ollama_model)

@app.command()
def start():
    """
    Start the SideQuests Brain Daemon.
    """
    system = platform.system()
    if system == "Darwin":
        from sidequests.cli.launchd import load_plist
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
    Stop the SideQuests Brain Daemon.
    """
    system = platform.system()
    if system == "Darwin":
        from sidequests.cli.launchd import unload_plist
        if unload_plist():
            console.print("[green]Brain Daemon stopped via launchd.[/green]")
        else:
            console.print("[red]Failed to stop Brain Daemon via launchd.[/red]")
    else:
        # Fallback for other systems
        subprocess.run(["pkill", "-f", "brain_daemon.py"])
        console.print("[green]Brain Daemon stopped.[/green]")

@app.command()
def status():
    """
    Check the health and status of the SideQuests Brain Daemon.
    """
    console.print("[bold blue]SideQuests Status[/bold blue] 🧠")
    if not check_status():
        console.print("[red]Daemon is not responding or not healthy.[/red]")
        raise typer.Exit(code=1)

@app.command()
def smoke(
    arc_world_model_tools: bool = typer.Option(False, "--arc-world-model-tools", help="Check for ARC world-model tools")
):
    """
    Run diagnostic smoke tests.
    """
    console.print("[bold blue]SideQuests Smoke Test[/bold blue] 🧠")

    results = asyncio.run(run_smoke_tests())

    if arc_world_model_tools:
        from sidequests.cli.smoke_test import check_arc_tools
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
    from sidequests.cli.smoke_test import _send
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

@tool_app.command("list")
def tool_list():
    """List available MCP tools."""
    from sidequests.cli.smoke_test import _send
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

if __name__ == "__main__":
    app()
